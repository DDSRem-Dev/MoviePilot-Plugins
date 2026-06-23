from collections import defaultdict
from pathlib import Path
from time import time
from typing import Dict, List, Optional, Set, Tuple

from p115client import P115Client, check_response
from p115client.tool.edit import update_name

from app.chain.storage import StorageChain
from app.chain.transfer import TransferChain, task_lock
from app.core.config import settings
from app.core.event import eventmanager
from app.core.metainfo import MetaInfoPath
from app.db.transferhistory_oper import TransferHistoryOper
from app.helper.directory import DirectoryHelper
from app.log import logger
from app.schemas import FileItem, Notification, TransferInfo
from app.schemas import TransferTask as MPTransferTask
from app.schemas.types import EventType, MediaType, NotificationType
from app.utils.string import StringUtils

from ...core.config import configer
from ...schemas.transfer import TransferTask
from . import linked_subtitle_audio
from .cache_updater import CacheUpdater
from .handler_linked_batch import TransferHandlerLinkedBatch


class TransferHandler:
    """
    115 整理执行器
    """

    def __init__(self, client: P115Client, storage_name: str = "115网盘Plus"):
        """
        初始化整理执行器

        :param client (P115Client): 115 客户端实例
        :param storage_name (str): 存储名称
        """
        self.client = client
        self.storage_name = storage_name
        self.storage_chain = StorageChain()
        self.history_oper = TransferHistoryOper()

        self.cache_updater = CacheUpdater.create(
            client=client, storage_name=storage_name
        )

        self._linked_batch = TransferHandlerLinkedBatch(self)

        logger.info(f"【整理接管】初始化整理执行器，存储: {storage_name}")

    @staticmethod
    def _is_subtitle_file(fileitem: FileItem) -> bool:
        """
        判断是否为字幕文件

        :param fileitem (FileItem): 文件项
        :return bool: 是否为字幕文件
        """
        if not fileitem.extension:
            return False
        return f".{fileitem.extension.lower()}" in settings.RMT_SUBEXT

    @staticmethod
    def _is_audio_file(fileitem: FileItem) -> bool:
        """
        判断是否为音频文件

        :param fileitem (FileItem): 文件项
        :return bool: 是否为音频文件
        """
        if not fileitem.extension:
            return False
        return f".{fileitem.extension.lower()}" in settings.RMT_AUDIOEXT

    @staticmethod
    def _is_media_file(fileitem: FileItem) -> bool:
        """
        与 TransferChain.__is_media_file 一致的主要媒体文件判定（文件项）

        :param fileitem (FileItem): 文件项
        :return bool: 是否为主要媒体文件
        """
        if fileitem.type == "dir":
            return StorageChain().is_bluray_folder(fileitem)
        if not fileitem.extension:
            return False
        return f".{fileitem.extension.lower()}" in settings.RMT_MEDIAEXT

    @staticmethod
    def _sort_tasks_for_batch(tasks: List[TransferTask]) -> List[TransferTask]:
        """
        批次内顺序：字幕 → 音频 → 其它 → 主视频

        主视频放最后，使 _record_history 里最后一个 finish_task 对应主视频；同一作业在字幕/音轨
        先完成后再 is_finished，才能通过 _is_media_file 门控发出 MetadataScrape

        :param tasks (List): 任务列表
        :return List: 排序后的新列表
        """

        def _key(t: TransferTask) -> Tuple[int, str]:
            fi = t.fileitem
            if TransferHandler._is_subtitle_file(fi):
                return (0, fi.path or "")
            if TransferHandler._is_audio_file(fi):
                return (1, fi.path or "")
            if TransferHandler._is_media_file(fi):
                return (3, fi.path or "")
            return (2, fi.path or "")

        return sorted(tasks, key=_key)

    @staticmethod
    def _create_mp_task(task: TransferTask) -> MPTransferTask:
        """
        创建 MoviePilot TransferTask 对象

        :param task (TransferTask): 插件任务对象

        :return MPTransferTask: MoviePilot TransferTask 对象
        """
        return MPTransferTask(
            fileitem=task.fileitem,
            mediainfo=task.mediainfo,
            meta=task.meta,
            transfer_batch_id=task.transfer_batch_id,
        )

    @staticmethod
    def _group_tasks_by_media(
        tasks: List[TransferTask],
    ) -> Dict[Tuple, List[TransferTask]]:
        """
        按媒体分组任务

        :param tasks (List): 任务列表

        :return Dict: 按媒体分组的任务字典，key 为 (media_id, season)
        """
        tasks_by_media: Dict[Tuple, List[TransferTask]] = defaultdict(list)
        for task in tasks:
            if task.mediainfo:
                key = (
                    task.mediainfo.tmdb_id or task.mediainfo.douban_id,
                    task.meta.begin_season,
                )
                tasks_by_media[key].append(task)
        return tasks_by_media

    def _remove_completed_jobs(
        self,
        tasks_by_media: Dict[Tuple, List[TransferTask]],
        task_action: str = "finish",
        check_method: str = "is_finished",
    ) -> int:
        """
        移除已完成的任务组

        :param tasks_by_media (Dict): 按媒体分组的任务字典
        :param task_action (str): 任务动作，'finish' 或 'fail'
        :param check_method (str): 检查方法，'is_finished' 或 'is_done'

        :return int: 移除的任务组数量
        """
        chain = TransferChain()
        removed_count = 0

        for (media_id, season), group_tasks in tasks_by_media.items():
            try:
                # 使用第一个任务作为代表
                sample_task = group_tasks[0]
                mp_sample_task = self._create_mp_task(sample_task)

                # 确保所有任务都已标记（finish 或 fail）
                for task in group_tasks:
                    try:
                        mp_task = self._create_mp_task(task)
                        if task_action == "finish":
                            chain.jobview.finish_task(mp_task)
                        elif task_action == "fail":
                            chain.jobview.fail_task(mp_task)
                    except Exception as e:
                        action_name = "完成" if task_action == "finish" else "失败"
                        logger.debug(
                            f"【整理接管】标记任务{action_name}失败 (任务: {task.fileitem.name}): {e}"
                        )

                # 检查是否所有相关任务都完成了
                check_func = getattr(chain.jobview, check_method)
                if check_func(mp_sample_task):
                    # 移除整个媒体组任务
                    with task_lock:
                        chain.jobview.remove_job(mp_sample_task)
                    removed_count += 1
            except Exception as e:
                logger.debug(
                    f"【整理接管】移除任务组失败 (media_id={media_id}, season={season}): {e}",
                    exc_info=True,
                )

        return removed_count

    def _get_folder(self, path: Path) -> Optional[FileItem]:
        """
        获取目录，如目录不存在则创建

        :param path (Path): 目录路径

        :return FileItem: 目录文件项，如果创建失败则返回None
        """
        folder_item = self.cache_updater._p115_api.get_item(path)
        if folder_item and folder_item.type == "dir":
            return folder_item

        try:
            resp = self.client.fs_makedirs_app(
                path.as_posix(), pid=0, **configer.get_ios_ua_app()
            )
            check_response(resp)
            logger.debug(f"【整理接管】get_folder 创建目录: {path} (ID: {resp['cid']})")
            modify_time = int(time())
            folder_item = FileItem(
                storage=self.storage_name,
                fileid=str(resp["cid"]),
                path=path.as_posix() + "/",
                name=path.name,
                basename=path.name,
                type="dir",
                modify_time=modify_time,
                pickcode=self.client.to_pickcode(resp["cid"]),
            )
            self.cache_updater.update_folder_cache(folder_item)
            return folder_item
        except Exception as e:
            logger.error(f"【整理接管】创建目录失败 ({path}): {e}", exc_info=True)
            return None

    @staticmethod
    def _pan_transfer_linked_subtitle_audio() -> bool:
        """
        是否启用字幕/音轨关联整理（与主视频同批）
        """
        return bool(configer.pan_transfer_linked_subtitle_audio)

    def process_batch(self, tasks: List[TransferTask]) -> None:
        """
        批量处理整理任务

        :param tasks (List): 任务列表
        """
        if not tasks:
            logger.warn("【整理接管】任务列表为空，跳过处理")
            return

        logger.info(f"【整理接管】开始批量处理 {len(tasks)} 个任务")

        remaining_tasks = list(tasks)
        if self._pan_transfer_linked_subtitle_audio():
            try:
                linked_subtitle_audio.discover_related_files(self, remaining_tasks)
            except Exception as e:
                error_msg = f"发现关联文件失败: {e}"
                logger.error(f"【整理接管】{error_msg}", exc_info=True)
                self._batch_record_failures(
                    [(task, error_msg) for task in remaining_tasks]
                )
                return
        else:
            remaining_tasks = self._sort_tasks_for_batch(tasks)
        failed_tasks: List[Tuple[TransferTask, str]] = []

        try:
            # 批量创建目标目录
            if remaining_tasks:
                try:
                    if self._pan_transfer_linked_subtitle_audio():
                        failed_in_step, remaining_tasks = (
                            self._linked_batch.batch_create_directories(remaining_tasks)
                        )
                    else:
                        failed_in_step, remaining_tasks = (
                            self._batch_create_directories(remaining_tasks)
                        )
                    failed_tasks.extend(failed_in_step)
                except Exception as e:
                    error_msg = f"批量创建目录失败: {e}"
                    logger.error(f"【整理接管】{error_msg}", exc_info=True)
                    # 所有剩余任务都失败
                    failed_tasks.extend([(task, error_msg) for task in remaining_tasks])
                    remaining_tasks = []
                    # 阻断后续步骤
                    self._batch_record_failures(failed_tasks)
                    return

            # 批量移动/复制文件
            if remaining_tasks:
                try:
                    if self._pan_transfer_linked_subtitle_audio():
                        failed_in_step, remaining_tasks = (
                            self._linked_batch.batch_move_or_copy(remaining_tasks)
                        )
                    else:
                        failed_in_step, remaining_tasks = self._batch_move_or_copy(
                            remaining_tasks
                        )
                    failed_tasks.extend(failed_in_step)
                except Exception as e:
                    error_msg = f"批量移动/复制文件失败: {e}"
                    logger.error(f"【整理接管】{error_msg}", exc_info=True)
                    # 所有剩余任务都失败
                    failed_tasks.extend([(task, error_msg) for task in remaining_tasks])
                    remaining_tasks = []
                    # 阻断后续步骤
                    self._batch_record_failures(failed_tasks)
                    return

            # 批量重命名文件
            if remaining_tasks:
                try:
                    if self._pan_transfer_linked_subtitle_audio():
                        failed_in_step, remaining_tasks = (
                            self._linked_batch.batch_rename_files(remaining_tasks)
                        )
                    else:
                        failed_in_step, remaining_tasks = self._batch_rename_files(
                            remaining_tasks
                        )
                    failed_tasks.extend(failed_in_step)
                except Exception as e:
                    error_msg = f"批量重命名文件失败: {e}"
                    logger.error(f"【整理接管】{error_msg}", exc_info=True)
                    # 所有剩余任务都失败
                    failed_tasks.extend([(task, error_msg) for task in remaining_tasks])
                    remaining_tasks = []
                    # 阻断后续步骤
                    self._batch_record_failures(failed_tasks)
                    return

            # 记录历史（只处理成功的任务）
            if remaining_tasks:
                try:
                    if self._pan_transfer_linked_subtitle_audio():
                        self._linked_batch.record_history(remaining_tasks)
                    else:
                        self._record_history(remaining_tasks)
                except Exception as e:
                    error_msg = f"记录历史失败: {e}"
                    logger.error(f"【整理接管】{error_msg}", exc_info=True)
                    # 所有剩余任务都失败
                    failed_tasks.extend([(task, error_msg) for task in remaining_tasks])
                    remaining_tasks = []

            # 批量记录所有失败的任务
            if failed_tasks:
                self._batch_record_failures(failed_tasks)

            success_count = len(remaining_tasks)
            fail_count = len(failed_tasks)
            logger.info(
                f"【整理接管】批量处理完成，成功: {success_count} 个，失败: {fail_count} 个"
            )

        except Exception as e:
            logger.error(f"【整理接管】批量处理异常: {e}", exc_info=True)
            # 所有剩余任务都失败
            error_msg = f"批量处理异常: {e}"
            failed_tasks.extend([(task, error_msg) for task in remaining_tasks])
            self._batch_record_failures(failed_tasks)

    def _batch_create_directories(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量创建目标目录

        :param tasks (List): 任务列表

        :return Tuple: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量创建目标目录")

        # 收集所有目标目录
        target_dirs: set[Path] = set()
        task_dirs_map: Dict[Path, List[TransferTask]] = defaultdict(list)
        for task in tasks:
            target_dir = task.target_dir
            target_dirs.add(target_dir)
            task_dirs_map[target_dir].append(task)

        # 搜集子目录
        leaf_dirs: set[Path] = set()
        for target_dir in target_dirs:
            is_parent = any(
                target_dir != other_dir and target_dir in other_dir.parents
                for other_dir in target_dirs
            )
            if not is_parent:
                leaf_dirs.add(target_dir)

        # 批量创建子目录（自动递归）
        created_count = 0
        failed_dirs: set[Path] = set()
        for target_dir in leaf_dirs:
            try:
                folder_item = self._get_folder(target_dir)
                if folder_item:
                    created_count += 1
                else:
                    logger.warn(f"【整理接管】创建目录失败: {target_dir}")
                    failed_dirs.add(target_dir)

            except Exception as e:
                logger.error(
                    f"【整理接管】创建目录失败 ({target_dir}): {e}",
                    exc_info=True,
                )
                failed_dirs.add(target_dir)

        logger.info(f"【整理接管】目录创建完成，共创建 {created_count} 个目录")

        # 收集失败的任务（如果任务的目标目录创建失败，则任务失败）
        failed_tasks: List[Tuple[TransferTask, str]] = []
        success_tasks: List[TransferTask] = []

        for task in tasks:
            task_failed = False
            # 检查主目录
            if task.target_dir in failed_dirs:
                failed_tasks.append((task, f"创建目标目录失败: {task.target_dir}"))
                task_failed = True

            if not task_failed:
                success_tasks.append(task)

        return failed_tasks, success_tasks

    def _batch_move_or_copy(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量移动/复制文件（按目标目录分组）

        :param tasks (List): 任务列表

        :return Tuple: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量移动/复制文件")

        task_main_file_status: Dict[str, bool] = {
            task.fileitem.path: False for task in tasks
        }
        task_failures: Dict[str, str] = {}

        operations: Dict[Tuple[Path, str], List[Tuple[FileItem, str, TransferTask]]] = (
            defaultdict(list)
        )

        for task in tasks:
            target_dir = task.target_dir
            transfer_type = task.transfer_type
            operations[(target_dir, transfer_type)].append(
                (task.fileitem, task.target_name, task)
            )

        for (target_dir, transfer_type), files in operations.items():
            try:
                try:
                    folder_item = self._get_folder(target_dir)
                    if not folder_item or not folder_item.fileid:
                        logger.error(
                            f"【整理接管】无法获取或创建目标目录: {target_dir}"
                        )
                        affected_tasks = []
                        seen_tasks = set()
                        for _, _, task in files:
                            task_id = (
                                task.fileitem.path if task and task.fileitem else None
                            )
                            if task_id and task_id not in seen_tasks:
                                affected_tasks.append(task)
                                seen_tasks.add(task_id)
                        for task in affected_tasks:
                            task_path = (
                                task.fileitem.path if task and task.fileitem else None
                            )
                            if task_path and task_path not in task_failures:
                                task_failures[task_path] = (
                                    f"无法获取或创建目标目录: {target_dir}"
                                )
                        continue
                    target_dir_id = int(folder_item.fileid)
                except Exception as e:
                    logger.error(
                        f"【整理接管】无法获取目标目录ID: {target_dir}, 错误: {e}"
                    )
                    affected_tasks = []
                    seen_tasks = set()
                    for _, _, task in files:
                        task_id = task.fileitem.path if task and task.fileitem else None
                        if task_id and task_id not in seen_tasks:
                            affected_tasks.append(task)
                            seen_tasks.add(task_id)
                    for task in affected_tasks:
                        task_path = (
                            task.fileitem.path if task and task.fileitem else None
                        )
                        if task_path and task_path not in task_failures:
                            task_failures[task_path] = (
                                f"无法获取目标目录ID: {target_dir}, 错误: {e}"
                            )
                    continue

                existing_files_map: Dict[str, FileItem] = {}
                try:
                    existing_files = self.cache_updater._p115_api.list(folder_item)
                    if existing_files:
                        for existing_file in existing_files:
                            if existing_file.type == "file":
                                existing_files_map[existing_file.name] = existing_file
                except Exception as list_error:
                    logger.warn(
                        f"【整理接管】批量列出目标目录文件失败 ({target_dir}): {list_error}，将跳过文件存在性检查"
                    )

                file_ids: List[int] = []
                file_mapping: Dict[int, Tuple[TransferTask, str, FileItem]] = {}
                files_to_delete: List[FileItem] = []
                version_delete_tasks: Dict[Path, List[Tuple[Path, TransferTask]]] = (
                    defaultdict(list)
                )

                for fileitem, target_name, task in files:
                    if not fileitem.fileid:
                        logger.warn(f"【整理接管】文件缺少 fileid: {fileitem.path}")
                        task_path = (
                            task.fileitem.path if task and task.fileitem else None
                        )
                        if task_path:
                            task_failures[task_path] = (
                                f"文件缺少 fileid: {fileitem.path}"
                            )
                        continue

                    existing_item = existing_files_map.get(target_name)

                    is_extra_file = False
                    if fileitem.extension:
                        file_ext = f".{fileitem.extension.lower()}"
                        is_extra_file = file_ext in (
                            settings.RMT_SUBEXT + settings.RMT_AUDIOEXT
                        )

                    if existing_item:
                        if is_extra_file:
                            logger.info(
                                f"【整理接管】目标文件已存在，附加文件强制覆盖: {target_dir / target_name}"
                            )
                            files_to_delete.append(existing_item)
                            existing_files_map.pop(target_name, None)
                        else:
                            overwrite_mode = task.overwrite_mode or "never"
                            over_flag = False
                            skip_reason: Optional[str] = None

                            # 触发 TransferOverwriteCheck 事件，允许插件介入覆盖判断
                            if overwrite_mode != "never":
                                try:
                                    from app.core.event import eventmanager
                                    from app.schemas import (
                                        TransferOverwriteCheckEventData,
                                    )
                                    from app.schemas.types import ChainEventType

                                    event_data = TransferOverwriteCheckEventData(
                                        fileitem=fileitem,
                                        target_item=existing_item,
                                        target_storage=self.storage_name,
                                        target_path=target_dir / target_name,
                                        overwrite_mode=overwrite_mode,
                                        transfer_type=transfer_type,
                                    )
                                    event = eventmanager.send_event(
                                        ChainEventType.TransferOverwriteCheck,
                                        event_data,
                                    )
                                    if event and event.event_data:
                                        event_data = event.event_data
                                        if event_data.overwrite is not None:
                                            if event_data.overwrite:
                                                over_flag = True
                                                logger.info(
                                                    f"【整理接管】插件强制覆盖: {target_dir / target_name}"
                                                )
                                            else:
                                                skip_reason = (
                                                    event_data.reason or "插件拒绝覆盖"
                                                )
                                                logger.info(
                                                    f"【整理接管】插件拒绝覆盖: {target_dir / target_name}，原因: {skip_reason}"
                                                )
                                        if event_data.source_size is not None:
                                            fileitem.size = event_data.source_size
                                        if event_data.target_size is not None:
                                            existing_item.size = event_data.target_size
                                except Exception:
                                    pass

                            if skip_reason:
                                task_path = (
                                    task.fileitem.path
                                    if task and task.fileitem
                                    else None
                                )
                                if task_path:
                                    task_failures[task_path] = skip_reason
                                continue
                            if over_flag:
                                files_to_delete.append(existing_item)
                                existing_files_map.pop(target_name, None)
                                continue

                            if overwrite_mode == "always":
                                over_flag = True
                                logger.info(
                                    f"【整理接管】目标文件已存在，覆盖模式=always，将覆盖: {target_dir / target_name}"
                                )
                            elif overwrite_mode == "size":
                                source_size = fileitem.size or 0
                                target_size = existing_item.size or 0
                                if source_size > target_size:
                                    over_flag = True
                                    logger.info(
                                        f"【整理接管】目标文件已存在，覆盖模式=size，"
                                        f"源文件更大 ({source_size} > {target_size})，"
                                        f"将覆盖: {target_dir / target_name}"
                                    )
                                else:
                                    skip_reason = "媒体库存在同名文件，且质量更好"
                                    logger.info(
                                        f"【整理接管】目标文件已存在，覆盖模式=size，"
                                        f"目标文件质量更好 ({target_size} >= {source_size})，"
                                        f"跳过: {target_dir / target_name}"
                                    )
                            elif overwrite_mode == "latest":
                                over_flag = True
                                logger.info(
                                    f"【整理接管】目标文件已存在，覆盖模式=latest，将覆盖: {target_dir / target_name}"
                                )
                            else:
                                skip_reason = "媒体库存在同名文件，当前覆盖模式为不覆盖"
                                logger.info(
                                    f"【整理接管】目标文件已存在，覆盖模式=never，跳过: {target_dir / target_name}"
                                )

                            if skip_reason:
                                task_path = (
                                    task.fileitem.path
                                    if task and task.fileitem
                                    else None
                                )
                                if task_path:
                                    task_failures[task_path] = skip_reason
                                continue
                            elif over_flag:
                                files_to_delete.append(existing_item)
                                existing_files_map.pop(target_name, None)
                    else:
                        if not is_extra_file and task.overwrite_mode == "latest":
                            version_delete_tasks[target_dir].append(
                                (target_dir / target_name, task)
                            )

                    file_id = int(fileitem.fileid)
                    file_ids.append(file_id)
                    file_mapping[file_id] = (task, target_name, fileitem)

                if files_to_delete:
                    logger.info(
                        f"【整理接管】批量删除 {len(files_to_delete)} 个已存在的目标文件"
                    )
                    delete_file_ids = []
                    delete_file_mapping: Dict[int, FileItem] = {}
                    for existing_item in files_to_delete:
                        if existing_item.fileid:
                            file_id_del = int(existing_item.fileid)
                            delete_file_ids.append(file_id_del)
                            delete_file_mapping[file_id_del] = existing_item

                    if delete_file_ids:
                        try:
                            resp = self.client.fs_delete(
                                delete_file_ids, **configer.get_ios_ua_app(app=False)
                            )
                            check_response(resp)
                            for file_id_del in delete_file_ids:
                                self.cache_updater.remove_cache(file_id_del)
                            logger.info(
                                f"【整理接管】批量删除成功: {len(delete_file_ids)} 个文件"
                            )
                        except Exception as batch_delete_error:
                            logger.error(
                                f"【整理接管】批量删除失败: {batch_delete_error}",
                                exc_info=True,
                            )
                            for file_id_del in delete_file_ids:
                                existing_item = delete_file_mapping.get(file_id_del)
                                if existing_item:
                                    file_id_to_remove = None
                                    for fid, (_, t_name, _) in file_mapping.items():
                                        if t_name == existing_item.name:
                                            file_id_to_remove = fid
                                            break
                                    if file_id_to_remove is not None:
                                        file_ids.remove(file_id_to_remove)
                                        file_mapping.pop(file_id_to_remove, None)

                if version_delete_tasks:
                    self._batch_delete_version_files(version_delete_tasks)

                if not file_ids:
                    continue

                if transfer_type == "move":
                    try:
                        resp = self.client.fs_move(
                            file_ids,
                            pid=target_dir_id,
                            **configer.get_ios_ua_app(app=False),
                        )
                        check_response(resp)
                        for file_id, (
                            task,
                            target_name,
                            fileitem,
                        ) in file_mapping.items():
                            try:
                                target_path = target_dir / target_name
                                new_fileitem = FileItem(
                                    storage=self.storage_name,
                                    path=str(target_path),
                                    name=target_name,
                                    fileid=str(file_id),
                                    type="file",
                                    size=fileitem.size,
                                    modify_time=fileitem.modify_time,
                                    pickcode=fileitem.pickcode,
                                )
                                self.cache_updater.update_file_cache(new_fileitem)
                            except Exception as cache_error:
                                logger.debug(
                                    f"【整理接管】更新移动文件缓存失败 (file_id: {file_id}): {cache_error}"
                                )
                        logger.info(
                            f"【整理接管】批量移动 {len(file_ids)} 个文件到 {target_dir}"
                        )
                        for file_id, (
                            task,
                            target_name,
                            fileitem,
                        ) in file_mapping.items():
                            task_path = (
                                task.fileitem.path if task and task.fileitem else None
                            )
                            if task_path:
                                task_main_file_status[task_path] = True
                    except Exception as batch_error:
                        logger.error(
                            f"【整理接管】批量移动失败: {batch_error}",
                            exc_info=True,
                        )
                        for file_id in file_ids:
                            task, target_name, _ = file_mapping.get(
                                file_id, (None, "", None)
                            )
                            if task:
                                task_path = (
                                    task.fileitem.path
                                    if task and task.fileitem
                                    else None
                                )
                                if task_path:
                                    task_failures[task_path] = (
                                        f"批量移动失败: {target_name}"
                                    )
                elif transfer_type == "copy":
                    try:
                        resp = self.client.fs_copy(
                            file_ids,
                            pid=target_dir_id,
                            **configer.get_ios_ua_app(app=False),
                        )
                        check_response(resp)
                        logger.info(
                            f"【整理接管】批量复制 {len(file_ids)} 个文件到 {target_dir}"
                        )
                        self._update_file_ids_after_copy(target_dir, file_mapping)
                        for file_id, (
                            task,
                            target_name,
                            fileitem,
                        ) in file_mapping.items():
                            try:
                                actual_fileid = task.fileitem.fileid
                                if actual_fileid:
                                    target_path = target_dir / target_name
                                    new_fileitem = FileItem(
                                        storage=self.storage_name,
                                        path=str(target_path),
                                        name=target_name,
                                        fileid=actual_fileid,
                                        type="file",
                                        size=fileitem.size,
                                        modify_time=fileitem.modify_time,
                                        pickcode=task.fileitem.pickcode,
                                    )
                                    self.cache_updater.update_file_cache(new_fileitem)
                                    task_path = (
                                        task.fileitem.path
                                        if task and task.fileitem
                                        else None
                                    )
                                    if task_path:
                                        task_main_file_status[task_path] = True
                            except Exception as cache_error:
                                logger.debug(
                                    f"【整理接管】更新复制文件缓存失败 (file_id: {file_id}): {cache_error}"
                                )
                    except Exception as batch_error:
                        logger.error(
                            f"【整理接管】批量复制失败: {batch_error}",
                            exc_info=True,
                        )
                        for file_id in file_ids:
                            task, target_name, _ = file_mapping.get(
                                file_id, (None, "", None)
                            )
                            if task:
                                task_path = (
                                    task.fileitem.path
                                    if task and task.fileitem
                                    else None
                                )
                                if task_path:
                                    task_failures[task_path] = (
                                        f"批量复制失败: {target_name}"
                                    )

            except Exception as e:
                logger.error(
                    f"【整理接管】批量移动/复制失败 (目录: {target_dir}, 类型: {transfer_type}): {e}",
                    exc_info=True,
                )
                affected_tasks = []
                seen_tasks = set()
                for _, _, task in files:
                    task_id = task.fileitem.path if task and task.fileitem else None
                    if task_id and task_id not in seen_tasks:
                        affected_tasks.append(task)
                        seen_tasks.add(task_id)

                for task in affected_tasks:
                    task_path = task.fileitem.path if task and task.fileitem else None
                    if task_path and task_path not in task_failures:
                        task_failures[task_path] = (
                            f"批量移动/复制失败 (目录: {target_dir}): {e}"
                        )

        failed_tasks: List[Tuple[TransferTask, str]] = []
        success_tasks: List[TransferTask] = []
        tasks_to_check: List[TransferTask] = []

        for task in tasks:
            task_path = task.fileitem.path if task and task.fileitem else None
            if task_path and task_path in task_failures:
                failed_tasks.append((task, task_failures[task_path]))
            elif task_path and task_main_file_status.get(task_path, False):
                success_tasks.append(task)
            else:
                if task.fileitem.fileid:
                    tasks_to_check.append(task)
                else:
                    failed_tasks.append((task, "主文件移动/复制未完成"))

        if tasks_to_check:
            tasks_by_dir: Dict[Path, List[TransferTask]] = defaultdict(list)
            for task in tasks_to_check:
                tasks_by_dir[task.target_dir].append(task)

            for target_dir, dir_tasks in tasks_by_dir.items():
                try:
                    folder_item = self._get_folder(target_dir)
                    if folder_item:
                        existing_files = self.cache_updater._p115_api.list(folder_item)
                        if existing_files:
                            existing_files_map = {
                                f.name: f for f in existing_files if f.type == "file"
                            }
                            for task in dir_tasks:
                                if task.target_name in existing_files_map:
                                    success_tasks.append(task)
                                else:
                                    failed_tasks.append((task, "主文件移动/复制未完成"))
                        else:
                            for task in dir_tasks:
                                failed_tasks.append((task, "主文件移动/复制未完成"))
                    else:
                        for task in dir_tasks:
                            failed_tasks.append((task, "主文件移动/复制未完成"))
                except Exception as e:
                    logger.warn(
                        f"【整理接管】批量检查文件存在性失败 (目录: {target_dir}): {e}"
                    )
                    for task in dir_tasks:
                        failed_tasks.append((task, "主文件移动/复制未完成"))

        logger.info(
            f"【整理接管】批量移动/复制完成，成功: {len(success_tasks)} 个，失败: {len(failed_tasks)} 个"
        )

        return failed_tasks, success_tasks

    def _batch_delete_version_files(
        self,
        version_delete_tasks: Dict[Path, List[Tuple[Path, TransferTask]]],
    ) -> None:
        """
        批量删除版本文件（latest 模式，目标文件不存在时）

        :param version_delete_tasks (Dict): 按目录分组的版本删除任务 {目录: [(目标路径, 任务), ...]}
        """
        for target_dir, tasks in version_delete_tasks.items():
            try:
                # 获取目标目录
                folder_item = self._get_folder(target_dir)
                if not folder_item:
                    logger.warn(f"【整理接管】无法获取目标目录: {target_dir}")
                    continue

                # 列出目录下所有文件
                files = self.cache_updater._p115_api.list(folder_item)
                if not files:
                    logger.debug(f"【整理接管】目录 {target_dir} 中没有文件")
                    continue

                # 收集需要删除的文件（按季集 Part 分组）
                files_to_delete_by_se: Dict[
                    Tuple[Optional[str], Optional[str], Optional[str]], List[FileItem]
                ] = defaultdict(list)

                # 收集所有目标文件的季集 Part 信息
                target_seasons_episodes: Set[
                    Tuple[Optional[str], Optional[str], Optional[str]]
                ] = set()
                for target_path, _ in tasks:
                    meta = MetaInfoPath(target_path)
                    target_seasons_episodes.add((meta.season, meta.episode, meta.part))

                if not target_seasons_episodes:
                    logger.debug(
                        f"【整理接管】目标文件无季集信息，跳过版本删除: {target_dir}"
                    )
                    continue

                logger.info(
                    f"【整理接管】覆盖模式=latest，正在删除目标目录中其它版本的文件: {target_dir}"
                )

                # 遍历目录中的文件，找出需要删除的版本文件
                for file in files:
                    if file.type != "file":
                        continue
                    if not file.extension:
                        continue
                    # 只处理媒体文件
                    file_ext = f".{file.extension.lower()}"
                    if file_ext not in settings.RMT_MEDIAEXT:
                        continue

                    # 识别文件中的季集 Part 信息
                    file_meta = MetaInfoPath(Path(file.path))
                    file_se: Tuple[Optional[str], Optional[str], Optional[str]] = (
                        file_meta.season,
                        file_meta.episode,
                        file_meta.part,
                    )

                    # 检查是否与任何目标文件的季集 Part 匹配
                    if file_se in target_seasons_episodes:
                        # 检查是否为目标文件本身（通过路径匹配）
                        is_target_file = False
                        for target_path, _ in tasks:
                            if Path(file.path) == target_path:
                                is_target_file = True
                                break

                        if not is_target_file:
                            files_to_delete_by_se[file_se].append(file)
                            logger.info(
                                f"【整理接管】发现同版本文件，将删除: {file.name}"
                            )

                # 批量删除所有收集到的版本文件
                all_files_to_delete = []
                for files_list in files_to_delete_by_se.values():
                    all_files_to_delete.extend(files_list)

                if not all_files_to_delete:
                    logger.debug(
                        f"【整理接管】目录 {target_dir} 中没有找到同版本的其他文件"
                    )
                    continue

                # 批量删除
                delete_file_ids = []
                for file in all_files_to_delete:
                    if file.fileid:
                        delete_file_ids.append(int(file.fileid))

                if delete_file_ids:
                    try:
                        resp = self.client.fs_delete(
                            delete_file_ids, **configer.get_ios_ua_app(app=False)
                        )
                        check_response(resp)
                        for file_id in delete_file_ids:
                            self.cache_updater.remove_cache(file_id)
                        logger.info(
                            f"【整理接管】批量删除版本文件成功: {len(delete_file_ids)} 个文件 (目录: {target_dir})"
                        )
                    except Exception as e:
                        logger.error(
                            f"【整理接管】批量删除版本文件失败: {e}", exc_info=True
                        )

            except Exception as e:
                logger.error(f"【整理接管】批量删除版本文件异常: {e}", exc_info=True)

    def _update_file_ids_after_copy(
        self,
        target_dir: Path,
        file_mapping: Dict[int, Tuple[TransferTask, str, FileItem]],
    ) -> None:
        """
        批量更新复制后的 文件 ID

        :param target_dir (Path): 目标目录
        :param file_mapping (Dict): 文件ID到 (任务, 目标文件名, 源文件项) 的映射
        """
        try:
            target_dir_fileitem = FileItem(
                storage=self.storage_name,
                path=str(target_dir) + "/",
                type="dir",
            )
            files = self.cache_updater._p115_api.list(target_dir_fileitem)

            if not files:
                logger.warn(f"【整理接管】目标目录 {target_dir} 为空，无法更新文件ID")
                return

            file_map: Dict[str, FileItem] = {
                f.name: f for f in files if f.type == "file"
            }

            for _file_id, (task, target_name, _fileitem) in file_mapping.items():
                # 复制后文件保留 115 源文件名，尚未重命名，用 fileitem.name 查找
                source_name = _fileitem.name
                if source_name in file_map:
                    new_fileitem = file_map[source_name]
                    if new_fileitem.fileid:
                        task.fileitem.fileid = new_fileitem.fileid
                        task.fileitem.pickcode = (
                            new_fileitem.pickcode or task.fileitem.pickcode
                        )
                        logger.debug(
                            f"【整理接管】更新文件ID: {source_name} -> {new_fileitem.fileid}"
                        )
                else:
                    logger.warn(
                        f"【整理接管】未找到复制后的文件: {source_name} (目录: {target_dir})"
                    )

        except Exception as e:
            logger.error(
                f"【整理接管】批量更新文件ID失败 (目录: {target_dir}): {e}",
                exc_info=True,
            )

    def _batch_rename_files(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量重命名文件

        :param tasks (List): 任务列表

        :return Tuple: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量重命名文件")

        rename_items: List[Tuple[int, str, TransferTask]] = []

        for task in tasks:
            if not task.need_rename:
                continue
            source_name = Path(task.fileitem.path).name
            target_name = task.target_name
            if source_name != target_name and task.fileitem.fileid:
                rename_items.append((int(task.fileitem.fileid), target_name, task))

        if not rename_items:
            logger.info("【整理接管】没有需要重命名的文件")
            return [], tasks

        try:
            update_name(
                self.client,
                [(file_id, new_name) for file_id, new_name, _ in rename_items],
                **configer.get_ios_ua_app(app=False),
            )
            for file_id, new_name, _ in rename_items:
                self.cache_updater.update_rename_cache(file_id, new_name)
            logger.info(
                f"【整理接管】批量重命名完成，共重命名 {len(rename_items)} 个文件"
            )
        except Exception as e:
            logger.error(f"【整理接管】批量重命名失败: {e}", exc_info=True)
            # 批量重命名失败，所有任务都失败
            failed_tasks: List[Tuple[TransferTask, str]] = []
            for _file_id, new_name, task in rename_items:
                task_path = task.fileitem.path if task and task.fileitem else None
                if task_path:
                    failed_tasks.append((task, f"批量重命名失败: {new_name}"))

            return failed_tasks, []

        # 所有重命名都成功
        return [], tasks

    def _record_history(self, tasks: List[TransferTask]) -> None:
        """
        记录转移历史

        :param tasks (List): 任务列表
        """
        logger.info("【整理接管】开始记录转移历史")

        # 跟踪成功处理的任务
        successfully_recorded_tasks: List[TransferTask] = []

        for task in tasks:
            try:
                target_fileitem, target_diritem = self._build_plugin_target_fileitems(
                    task
                )

                need_notify_val = (
                    task.need_notify if task.need_notify is not None else True
                )
                transferinfo = TransferInfo(
                    success=True,
                    fileitem=task.fileitem,
                    target_item=target_fileitem,
                    target_diritem=target_diritem,
                    transfer_type=task.transfer_type,
                    file_list=[task.fileitem.path],
                    file_list_new=[target_fileitem.path],
                    need_scrape=task.need_scrape,
                    need_notify=need_notify_val,
                )

                history = self.history_oper.add_success(
                    fileitem=task.fileitem,
                    mode=task.transfer_type,
                    meta=task.meta,
                    mediainfo=task.mediainfo,
                    transferinfo=transferinfo,
                    downloader=task.downloader,
                    download_hash=task.download_hash,
                )

                # 与 TransferChain.__default_callback 成功分支顺序一致：事件 → 登记清单 → finish_task
                fi = task.fileitem
                if self._is_media_file(fi):
                    complete_event = EventType.TransferComplete
                elif self._is_subtitle_file(fi):
                    complete_event = EventType.SubtitleTransferComplete
                elif self._is_audio_file(fi):
                    complete_event = EventType.AudioTransferComplete
                else:
                    complete_event = EventType.TransferComplete

                eventmanager.send_event(
                    complete_event,
                    {
                        "fileitem": task.fileitem,
                        "meta": task.meta,
                        "mediainfo": task.mediainfo,
                        "transferinfo": transferinfo,
                        "downloader": task.downloader,
                        "download_hash": task.download_hash,
                        "transfer_history_id": history.id if history else None,
                    },
                )

                try:
                    chain = TransferChain()
                    with task_lock:
                        target_dir_path = transferinfo.target_diritem.path
                        target_files = transferinfo.file_list_new
                        if chain._success_target_files.get(target_dir_path):
                            chain._success_target_files[target_dir_path].extend(
                                target_files
                            )
                        else:
                            chain._success_target_files[target_dir_path] = target_files
                except Exception as e:
                    logger.debug(
                        f"【整理接管】登记文件清单到 _success_target_files 失败: {e}"
                    )

                try:
                    chain = TransferChain()
                    mp_task = self._create_mp_task(task)
                    chain.jobview.finish_task(mp_task)
                    logger.debug(f"【整理接管】标记任务完成: {task.fileitem.path}")
                except Exception as e:
                    logger.warn(f"【整理接管】标记任务完成失败: {e}", exc_info=True)

                # 整理完成且有成功的任务时，执行 __do_finished 逻辑
                try:
                    chain = TransferChain()
                    mp_task = self._create_mp_task(task)
                    if chain.jobview.is_finished(mp_task):
                        with task_lock:
                            # 更新文件数量和大小
                            transferinfo.file_count = (
                                chain.jobview.count(
                                    task.mediainfo, task.meta.begin_season
                                )
                                or 1
                            )
                            transferinfo.total_size = (
                                chain.jobview.size(
                                    task.mediainfo, task.meta.begin_season
                                )
                                or task.fileitem.size
                                or 0
                            )

                            # 从 _success_target_files pop 文件清单
                            popped_files = chain._success_target_files.pop(
                                transferinfo.target_diritem.path, []
                            )
                            if popped_files:
                                transferinfo.file_list_new = popped_files

                            # 发送通知
                            if transferinfo.need_notify and (
                                task.background or not task.manual
                            ):
                                try:
                                    se_str = None
                                    if task.mediainfo.type == MediaType.TV:
                                        season_episodes = chain.jobview.season_episodes(
                                            task.mediainfo,
                                            task.meta.begin_season,
                                        )
                                        if season_episodes:
                                            se_str = f"{task.meta.season} {StringUtils.format_ep(season_episodes)}"
                                        else:
                                            se_str = f"{task.meta.season}"
                                    chain.send_transfer_message(
                                        meta=task.meta,
                                        mediainfo=task.mediainfo,
                                        transferinfo=transferinfo,
                                        season_episode=se_str,
                                        username=task.username,
                                    )
                                except Exception as e:
                                    logger.warn(
                                        f"【整理接管】发送通知失败: {e}",
                                        exc_info=True,
                                    )

                            # 发送刮削事件（与 MP __default_callback 一致：仅主视频）
                            if transferinfo.need_scrape and self._is_media_file(
                                task.fileitem
                            ):
                                try:
                                    eventmanager.send_event(
                                        EventType.MetadataScrape,
                                        {
                                            "meta": task.meta,
                                            "mediainfo": task.mediainfo,
                                            "fileitem": target_diritem,
                                            "file_list": transferinfo.file_list_new,
                                            "overwrite": False,
                                        },
                                    )
                                except Exception as e:
                                    logger.warn(
                                        f"【整理接管】发送刮削事件失败: {e}",
                                        exc_info=True,
                                    )
                except Exception as e:
                    logger.debug(f"【整理接管】执行完成逻辑失败: {e}", exc_info=True)

                logger.debug(
                    f"【整理接管】记录成功历史: {task.fileitem.name} -> {task.target_name}"
                )
                # 记录成功处理的任务
                successfully_recorded_tasks.append(task)

            except Exception as e:
                logger.error(
                    f"【整理接管】记录历史失败 (任务: {task.fileitem.name}): {e}",
                    exc_info=True,
                )
                self._record_fail(task, f"记录历史失败: {e}")

        # 所有任务处理完成后，统一批量删除空目录
        if successfully_recorded_tasks:
            self._batch_delete_empty_dirs(successfully_recorded_tasks)

        try:
            # 按媒体分组，每个媒体组只需要移除一次
            tasks_by_media = self._group_tasks_by_media(successfully_recorded_tasks)
            removed_count = self._remove_completed_jobs(
                tasks_by_media, task_action="finish", check_method="is_finished"
            )

            if removed_count > 0:
                logger.info(f"【整理接管】已移除 {removed_count} 个已完成的任务组")
        except Exception as e:
            logger.debug(f"【整理接管】移除任务失败: {e}", exc_info=True)

        logger.info("【整理接管】历史记录完成")

    def _batch_delete_empty_dirs(self, tasks: List[TransferTask]) -> None:
        """
        批量删除空目录

        :param tasks (List): 任务列表
        """
        try:
            chain = TransferChain()

            # 按媒体信息分组任务
            move_tasks = [task for task in tasks if task.transfer_type == "move"]
            if not move_tasks:
                logger.debug("【整理接管】没有移动模式的任务，跳过删除空目录")
                return

            tasks_by_media = self._group_tasks_by_media(move_tasks)

            if not tasks_by_media:
                logger.debug("【整理接管】没有有效的媒体任务，跳过删除空目录")
                return

            logger.info(
                f"【整理接管】开始批量删除空目录，共 {len(tasks_by_media)} 个媒体组"
            )

            # 收集所有需要删除的目录
            all_dir_items_to_delete: List[FileItem] = []
            checked_parent_dirs: Dict[str, List[FileItem]] = {}

            # 遍历每个媒体组
            for (media_id, season), group_tasks in tasks_by_media.items():
                # 使用第一个任务检查 is_success（同一组的所有任务应该有相同的 mediainfo）
                sample_task = group_tasks[0]
                mp_sample_task = MPTransferTask(
                    fileitem=sample_task.fileitem,
                    mediainfo=sample_task.mediainfo,
                    meta=sample_task.meta,
                )
                is_success = chain.jobview.is_success(mp_sample_task)
                logger.debug(
                    f"【整理接管】检查媒体组 (media_id={media_id}, season={season}) is_success={is_success}"
                )

                # 如果 is_success 为 False，检查任务状态详情
                if not is_success:
                    try:
                        # 使用 JobManager 的内部方法获取任务状态
                        __mediaid__ = chain.jobview._JobManager__get_media_id(
                            media=sample_task.mediainfo,
                            season=sample_task.meta.begin_season,
                        )
                        if __mediaid__ in chain.jobview._job_view:
                            job = chain.jobview._job_view[__mediaid__]
                            task_states = [
                                f"{t.fileitem.name if t.fileitem else 'None'}: {t.state}"
                                for t in job.tasks
                            ]
                            logger.warn(
                                f"【整理接管】任务状态详情 (media_id={media_id}, season={season}): {task_states}"
                            )
                        else:
                            logger.warn(
                                f"【整理接管】媒体组 (media_id={media_id}, season={season}) 不在 job_view 中，可能已被移除"
                            )
                            logger.info(
                                "【整理接管】任务不在 job_view 中，使用传入的任务列表删除空目录"
                            )
                            # 使用传入的 group_tasks 来收集需要删除的目录
                            for t in group_tasks:
                                if t.fileitem:
                                    parent_dir_item = (
                                        t.fileitem
                                        if t.fileitem.type == "dir"
                                        else self.cache_updater._p115_api.get_parent(
                                            t.fileitem
                                        )
                                    )
                                    if parent_dir_item and parent_dir_item.path:
                                        parent_dir_path = parent_dir_item.path
                                        if parent_dir_path not in checked_parent_dirs:
                                            collected_dirs = (
                                                self._collect_dirs_to_delete(t.fileitem)
                                            )
                                            checked_parent_dirs[parent_dir_path] = (
                                                collected_dirs
                                            )
                                            all_dir_items_to_delete.extend(
                                                collected_dirs
                                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"【整理接管】获取任务状态详情失败: {e}", exc_info=True
                        )

                if not is_success:
                    logger.warn(
                        f"【整理接管】媒体组 (media_id={media_id}, season={season}) 未全部成功，跳过删除空目录"
                    )
                    continue

                # 获取所有成功的任务
                success_tasks = chain.jobview.success_tasks(
                    sample_task.mediainfo, sample_task.meta.begin_season
                )
                logger.debug(
                    f"【整理接管】媒体组 (media_id={media_id}, season={season}) 有 {len(success_tasks)} 个成功任务"
                )

                for t in success_tasks:
                    # 收集需要删除的空目录（避免重复检查）
                    if t.fileitem:
                        logger.debug(
                            f"【整理接管】处理任务文件: {t.fileitem.path} (type: {t.fileitem.type})"
                        )
                        # 获取源文件的父目录作为检查键
                        parent_dir_item = (
                            t.fileitem
                            if t.fileitem.type == "dir"
                            else self.cache_updater._p115_api.get_parent(t.fileitem)
                        )
                        if parent_dir_item and parent_dir_item.path:
                            parent_dir_path = parent_dir_item.path
                            logger.debug(f"【整理接管】检查父目录: {parent_dir_path}")
                            # 如果这个父目录已经检查过，直接使用之前的结果
                            if parent_dir_path in checked_parent_dirs:
                                cached_dirs = checked_parent_dirs[parent_dir_path]
                                logger.debug(
                                    f"【整理接管】使用缓存的目录列表: {len(cached_dirs)} 个目录"
                                )
                                all_dir_items_to_delete.extend(cached_dirs)
                            else:
                                # 首次检查，收集所有需要删除的目录
                                logger.debug(
                                    f"【整理接管】首次检查目录: {parent_dir_path}"
                                )
                                collected_dirs = self._collect_dirs_to_delete(
                                    t.fileitem
                                )
                                logger.debug(
                                    f"【整理接管】收集到 {len(collected_dirs)} 个需要删除的目录: {[d.path for d in collected_dirs]}"
                                )
                                # 缓存结果
                                checked_parent_dirs[parent_dir_path] = collected_dirs
                                all_dir_items_to_delete.extend(collected_dirs)
                        else:
                            logger.debug(
                                f"【整理接管】无法获取父目录 (fileitem: {t.fileitem.path})"
                            )
                    else:
                        logger.debug(f"【整理接管】任务没有 fileitem (task: {t})")

            # 去重（使用 fileid 作为唯一标识）
            unique_dir_items = {}
            for dir_item in all_dir_items_to_delete:
                if dir_item.fileid:
                    unique_dir_items[int(dir_item.fileid)] = dir_item

            logger.info(
                f"【整理接管】收集到 {len(unique_dir_items)} 个需要删除的空目录"
            )

            # 批量删除空目录
            if unique_dir_items:
                # 按路径深度排序
                sorted_dir_items = sorted(
                    unique_dir_items.items(),
                    key=lambda x: len(Path(x[1].path).parts),
                    reverse=True,
                )
                dir_paths = [
                    unique_dir_items[dir_id].path for dir_id, _ in sorted_dir_items
                ]
                logger.info(
                    f"【整理接管】准备删除 {len(sorted_dir_items)} 个空目录: {dir_paths[:5]}..."
                )

                # 批量删除所有空目录
                deleted_count = 0
                # 按目录树分组
                dir_trees: Dict[Path, List[Tuple[int, FileItem]]] = defaultdict(list)
                for dir_id, dir_item in sorted_dir_items:
                    dir_path = Path(dir_item.path)
                    tree_root = None
                    parent_dirs = []
                    for other_id, other_item in sorted_dir_items:
                        other_path = Path(other_item.path)
                        if (
                            dir_path.is_relative_to(other_path)
                            and dir_path != other_path
                        ):
                            parent_dirs.append((other_id, other_item, other_path))
                    for parent_id, parent_item, parent_path in parent_dirs:
                        is_subdir = False
                        for (
                            other_parent_id,
                            other_parent_item,
                            other_parent_path,
                        ) in parent_dirs:
                            if parent_id == other_parent_id:
                                continue
                            if (
                                parent_path.is_relative_to(other_parent_path)
                                and parent_path != other_parent_path
                            ):
                                is_subdir = True
                                break
                        if not is_subdir:
                            if tree_root is None or len(parent_path.parts) < len(
                                tree_root.parts
                            ):
                                tree_root = parent_path
                    if tree_root is None:
                        tree_root = dir_path
                    dir_trees[tree_root].append((dir_id, dir_item))

                dir_ids_to_delete = []
                for tree_root, dirs_in_tree in dir_trees.items():
                    max_depth_in_tree = max(
                        len(Path(dir_item.path).parts) for _, dir_item in dirs_in_tree
                    )
                    min_depth_dirs_in_tree = [
                        (dir_id, dir_item)
                        for dir_id, dir_item in dirs_in_tree
                        if len(Path(dir_item.path).parts) == max_depth_in_tree
                    ]
                    tree_exists = True
                    for dir_id, dir_item in min_depth_dirs_in_tree:
                        try:
                            current_dir = self.cache_updater._p115_api.get_item(
                                Path(dir_item.path)
                            )
                            if not current_dir:
                                # 该目录树的最小深度目录已被删除，说明整个目录树都被删除了
                                tree_exists = False
                                logger.debug(
                                    f"【整理接管】目录树 {tree_root} 的最小深度目录已被删除 ({dir_item.path})，跳过该目录树"
                                )
                                break
                        except Exception as e:
                            logger.debug(
                                f"【整理接管】检查目录树 {tree_root} 的最小深度目录状态失败 ({dir_item.path}): {e}"
                            )
                            tree_exists = False
                            break

                    if tree_exists:
                        # 该目录树存在，收集该目录树的所有目录 ID
                        dir_ids_to_delete.extend([dir_id for dir_id, _ in dirs_in_tree])
                    else:
                        logger.debug(
                            f"【整理接管】目录树 {tree_root} 已被删除，跳过 {len(dirs_in_tree)} 个目录"
                        )

                if not dir_ids_to_delete:
                    logger.debug("【整理接管】所有目录树都已删除，无需删除")
                else:
                    # 一次性批量删除所有空目录
                    try:
                        resp = self.client.fs_delete(
                            dir_ids_to_delete, **configer.get_ios_ua_app(app=False)
                        )
                        check_response(resp)
                        for dir_id in dir_ids_to_delete:
                            self.cache_updater.remove_cache(dir_id)
                        deleted_count = len(dir_ids_to_delete)
                        logger.info(
                            f"【整理接管】批量删除空目录成功: {deleted_count} 个目录"
                        )
                    except Exception as batch_delete_error:
                        logger.error(
                            f"【整理接管】批量删除空目录失败: {batch_delete_error}",
                            exc_info=True,
                        )

                logger.info(
                    f"【整理接管】删除空目录完成: {deleted_count}/{len(sorted_dir_items)} 个目录"
                )
            else:
                logger.debug("【整理接管】没有需要删除的空目录")

        except Exception as e:
            logger.debug(f"【整理接管】批量删除空目录失败: {e}", exc_info=True)

    def _collect_dirs_to_delete(self, fileitem: FileItem) -> List[FileItem]:
        """
        收集需要删除的空目录

        :param fileitem (FileItem): 文件项

        :return List: 需要删除的目录列表
        """
        dirs_to_delete: List[FileItem] = []
        media_exts = (
            settings.RMT_MEDIAEXT
            + settings.DOWNLOAD_TMPEXT
            + settings.RMT_SUBEXT
            + settings.RMT_AUDIOEXT
        )
        fileitem_path = Path(fileitem.path) if fileitem.path else Path("")

        # 检查路径深度（不能删除根目录或一级目录）
        if len(fileitem_path.parts) <= 2:
            logger.debug(f"【整理接管】{fileitem.path} 根目录或一级目录不允许删除")
            return dirs_to_delete

        # 如果是目录类型且是蓝光原盘，需要特殊处理
        if fileitem.type == "dir":
            if self.storage_chain.is_bluray_folder(fileitem):
                # 蓝光原盘目录，直接返回（需要删除整个目录）
                dirs_to_delete.append(fileitem)
                return dirs_to_delete

        # 检查和删除上级空目录
        dir_item = (
            fileitem
            if fileitem.type == "dir"
            else self.cache_updater._p115_api.get_parent(fileitem)
        )
        if not dir_item:
            logger.debug(f"【整理接管】{fileitem.path} 上级目录不存在")
            return dirs_to_delete

        # 查找操作文件项匹配的配置目录 (资源目录、媒体库目录)
        associated_dir = max(
            (
                Path(p)
                for d in DirectoryHelper().get_dirs()
                for p in (d.download_path, d.library_path)
                if p and fileitem_path.is_relative_to(Path(p))
            ),
            key=lambda path: len(path.parts),
            default=None,
        )

        # 递归检查父目录
        while dir_item and len(Path(dir_item.path).parts) > 2:
            dir_path = Path(dir_item.path)

            if associated_dir and associated_dir.is_relative_to(dir_path):
                logger.debug(
                    f"【整理接管】{dir_item.path} 位于资源或媒体库目录结构中，不删除"
                )
                break

            # 如果不在资源/媒体库目录结构中，检查是否有任何文件（包括子目录、nfo、jpg等）
            elif not associated_dir:
                try:
                    dir_files = self.cache_updater._p115_api.list(dir_item)
                    if dir_files:
                        logger.debug(
                            f"【整理接管】{dir_item.path} 不是空目录（有 {len(dir_files)} 个文件），不删除"
                        )
                        break
                except Exception as e:
                    logger.debug(
                        f"【整理接管】检查目录文件列表失败 ({dir_item.path}): {e}",
                        exc_info=True,
                    )
                    break

            # 检查：目录存在媒体文件，则不删除
            def __any_file(_item: FileItem):
                """
                递归处理
                """
                _items = self.cache_updater._p115_api.list(_item)
                if _items:
                    if not media_exts:
                        return True
                    for t in _items:
                        if (
                            t.type == "file"
                            and t.extension
                            and f".{t.extension.lower()}" in media_exts
                        ):
                            return True
                        elif t.type == "dir":
                            if __any_file(t):
                                return True
                return False

            try:
                has_media = __any_file(dir_item)
                if has_media is not False:
                    logger.debug(f"【整理接管】{dir_item.path} 存在媒体文件，不删除")
                    break
            except Exception as e:
                logger.debug(
                    f"【整理接管】检查媒体文件失败 ({dir_item.path}): {e}",
                    exc_info=True,
                )
                break

            # 所有检查通过，可以删除此目录
            logger.debug(f"【整理接管】收集到需要删除的空目录: {dir_item.path}")
            dirs_to_delete.append(dir_item)

            # 继续检查父目录
            dir_item = self.cache_updater._p115_api.get_parent(dir_item)

        return dirs_to_delete

    def _build_plugin_target_fileitems(
        self, task: TransferTask
    ) -> Tuple[FileItem, FileItem]:
        """
        从插件整理任务构造目标文件与目标目录的 FileItem（与成功历史一致）

        :param task (TransferTask): 插件 TransferTask
        :return Tuple: (target_item, target_diritem)
        """
        target_fileitem = FileItem(
            storage=self.storage_name,
            path=str(task.target_path),
            name=task.target_name,
            fileid=task.fileitem.fileid,
            type="file",
            size=task.fileitem.size,
            modify_time=task.fileitem.modify_time,
            pickcode=task.fileitem.pickcode,
        )
        target_diritem = FileItem(
            storage=self.storage_name,
            path=str(task.target_dir) + "/",
            name=task.target_dir.name,
            type="dir",
        )
        return target_fileitem, target_diritem

    def _batch_record_failures(
        self, failed_tasks: List[Tuple[TransferTask, str]]
    ) -> None:
        """
        批量记录失败历史

        :param failed_tasks (List): 失败任务列表，每个元素为 (task, error_message)
        """
        if not failed_tasks:
            return

        logger.info(f"【整理接管】批量记录失败历史，共 {len(failed_tasks)} 个失败任务")

        # 先记录所有失败历史
        for task, message in failed_tasks:
            try:
                self._record_fail(task, message)
            except Exception as e:
                logger.error(
                    f"【整理接管】记录失败历史失败 (任务: {task.fileitem.name}): {e}",
                    exc_info=True,
                )

        # 按媒体分组，统一处理失败任务的移除
        try:
            # 提取任务列表（从 (task, message) 元组中提取）
            tasks = [task for task, _ in failed_tasks]
            # 按媒体分组，每个媒体组只需要移除一次
            tasks_by_media = self._group_tasks_by_media(tasks)
            removed_count = self._remove_completed_jobs(
                tasks_by_media, task_action="fail", check_method="is_done"
            )

            if removed_count > 0:
                logger.info(f"【整理接管】已移除 {removed_count} 个已完成的失败任务组")
        except Exception as e:
            logger.debug(f"【整理接管】移除失败任务失败: {e}", exc_info=True)

    def _record_fail(self, task: TransferTask, message: str) -> None:
        """
        记录失败历史并处理失败任务

        :param task (TransferTask): 任务
        :param message (str): 失败原因
        """
        try:
            try:
                target_item, target_diritem = self._build_plugin_target_fileitems(task)
            except Exception as e:
                logger.debug(
                    f"【整理接管】失败历史构造目标 FileItem 失败，使用精简字段: {e}",
                    exc_info=True,
                )
                target_item, target_diritem = None, None

            need_notify_val = task.need_notify if task.need_notify is not None else True
            src_path = task.fileitem.path
            transferinfo = TransferInfo(
                success=False,
                fileitem=task.fileitem,
                target_item=target_item,
                target_diritem=target_diritem,
                transfer_type=task.transfer_type,
                file_list=[src_path],
                file_list_new=[str(task.target_path)] if task.target_path else [],
                fail_list=[src_path],
                message=message,
                need_scrape=task.need_scrape,
                need_notify=need_notify_val,
            )

            # 记录失败历史
            history = self.history_oper.add_fail(
                fileitem=task.fileitem,
                mode=task.transfer_type or "",
                meta=task.meta,
                mediainfo=task.mediainfo,
                transferinfo=transferinfo,
                downloader=task.downloader,
                download_hash=task.download_hash,
            )

            # AI智能体自动重试整理
            if (
                history
                and settings.AI_AGENT_ENABLE
                and settings.AI_AGENT_RETRY_TRANSFER
            ):
                try:
                    import asyncio

                    from app.core import global_vars

                    chain = TransferChain()
                    group_key = (
                        task.download_hash or str(task.fileitem.path).rsplit("/", 1)[0]
                        if task.fileitem
                        else ""
                    )
                    asyncio.run_coroutine_threadsafe(
                        chain.retry_scheduler.schedule_retry(
                            history.id, group_key=group_key
                        ),
                        global_vars.loop,
                    )
                    logger.info(
                        f"【整理接管】已触发AI智能体重试整理历史记录 #{history.id}"
                    )
                except Exception as e:
                    logger.error(f"【整理接管】触发AI智能体重试整理失败: {e}")

            fi = task.fileitem
            if self._is_media_file(fi):
                fail_event = EventType.TransferFailed
            elif self._is_subtitle_file(fi):
                fail_event = EventType.SubtitleTransferFailed
            elif self._is_audio_file(fi):
                fail_event = EventType.AudioTransferFailed
            else:
                fail_event = EventType.TransferFailed

            eventmanager.send_event(
                fail_event,
                {
                    "fileitem": task.fileitem,
                    "meta": task.meta,
                    "mediainfo": task.mediainfo,
                    "transferinfo": transferinfo,
                    "downloader": task.downloader,
                    "download_hash": task.download_hash,
                    "transfer_history_id": history.id if history else None,
                },
            )

            # 发送失败通知
            try:
                chain = TransferChain()
                chain.post_message(
                    Notification(
                        mtype=NotificationType.Manual,
                        title=f"{task.mediainfo.title_year} {task.meta.season_episode} 入库失败！",
                        text=f"原因：{message or '未知'}",
                        image=task.mediainfo.get_message_image()
                        if task.mediainfo
                        else None,
                        username=task.username,
                        link=settings.MP_DOMAIN("#/history"),
                        save_history=False,
                    )
                )
            except Exception as e:
                logger.debug(f"【整理接管】发送失败通知失败: {e}", exc_info=True)

            # 标记任务失败
            try:
                chain = TransferChain()
                mp_task = self._create_mp_task(task)
                chain.jobview.fail_task(mp_task)
            except Exception as e:
                logger.debug(f"【整理接管】标记任务失败失败: {e}", exc_info=True)

            logger.debug(f"【整理接管】记录失败历史: {task.fileitem.name} - {message}")
        except Exception as e:
            logger.error(f"【整理接管】记录失败历史异常: {e}", exc_info=True)
