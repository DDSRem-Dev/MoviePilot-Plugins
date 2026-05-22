from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from p115client import check_response
from p115client.tool.edit import update_name

from app.chain.transfer import TransferChain, task_lock
from app.core.config import settings
from app.core.event import eventmanager
from app.log import logger
from app.schemas import FileItem, TransferInfo
from app.schemas.types import EventType, MediaType
from app.utils.string import StringUtils

from ...core.config import configer
from ...schemas.transfer import RelatedFile, TransferTask
from . import linked_subtitle_audio

if TYPE_CHECKING:
    from .handler import TransferHandler


class TransferHandlerLinkedBatch:
    """
    关联整理（related_files）路径下的批量实现，供 TransferHandler 委托调用
    """

    def __init__(self, handler: "TransferHandler") -> None:
        self._handler = handler

    def batch_create_directories(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量创建目标目录

        :param tasks: 任务列表

        :return: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量创建目标目录")

        # 收集所有目标目录（主文件与关联文件的父目录）
        target_dirs: set[Path] = set()
        for task in tasks:
            target_dirs.add(task.target_dir)
            for related_file in task.related_files:
                target_dirs.add(related_file.target_path.parent)

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
                folder_item = self._handler._get_folder(target_dir)
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
            else:
                # 检查关联文件的目录
                for related_file in task.related_files:
                    related_dir = related_file.target_path.parent
                    if related_dir in failed_dirs:
                        failed_tasks.append(
                            (task, f"创建关联文件目录失败: {related_dir}")
                        )
                        task_failed = True
                        break

            if not task_failed:
                success_tasks.append(task)

        return failed_tasks, success_tasks

    def batch_move_or_copy(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量移动/复制文件（按目标目录分组）

        :param tasks: 任务列表

        :return: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量移动/复制文件")

        # 跟踪每个任务的主文件处理状态（主文件失败则任务失败）
        task_main_file_status: Dict[str, bool] = {
            task.fileitem.path: False for task in tasks
        }
        # 跟踪每个任务的失败原因
        task_failures: Dict[str, str] = {}

        # 按目标目录和操作类型分组
        operations: Dict[
            Tuple[Path, str],
            List[Tuple[FileItem, str, TransferTask, bool, Optional[RelatedFile]]],
        ] = defaultdict(list)

        for task in tasks:
            target_dir = task.target_dir
            transfer_type = task.transfer_type

            # 主视频 (is_main=True, related_file=None)
            operations[(target_dir, transfer_type)].append(
                (task.fileitem, task.target_name, task, True, None)
            )

            # 关联文件 (is_main=False, related_file=related_file)
            for related_file in task.related_files:
                related_dir = related_file.target_path.parent
                operations[(related_dir, transfer_type)].append(
                    (
                        related_file.fileitem,
                        related_file.target_path.name,
                        task,
                        False,
                        related_file,
                    )
                )

        # 批量执行移动/复制
        for (target_dir, transfer_type), files in operations.items():
            try:
                # 获取目标目录的 fileid
                try:
                    folder_item = self._handler._get_folder(target_dir)
                    if not folder_item or not folder_item.fileid:
                        logger.error(
                            f"【整理接管】无法获取或创建目标目录: {target_dir}"
                        )
                        affected_tasks = []
                        seen_tasks = set()
                        for _, _, task, _, _ in files:
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
                    for _, _, task, _, _ in files:
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

                # 批量检查目标文件是否已存在
                existing_files_map: Dict[str, FileItem] = {}
                try:
                    existing_files = self._handler.cache_updater._p115_api.list(
                        folder_item
                    )
                    if existing_files:
                        # 创建文件名到 FileItem 的映射
                        for existing_file in existing_files:
                            if existing_file.type == "file":
                                existing_files_map[existing_file.name] = existing_file
                except Exception as list_error:
                    logger.warn(
                        f"【整理接管】批量列出目标目录文件失败 ({target_dir}): {list_error}，将跳过文件存在性检查"
                    )

                # 收集 文件 ID 和 文件信息 映射，并处理目标文件已存在的情况
                file_ids = []
                file_mapping: Dict[
                    int, Tuple[TransferTask, bool, str, Optional[RelatedFile]]
                ] = {}
                files_to_delete: List[FileItem] = []
                # 收集需要批量删除版本文件的任务（按目录分组）
                version_delete_tasks: Dict[Path, List[Tuple[Path, TransferTask]]] = (
                    defaultdict(list)
                )

                for fileitem, target_name, task, is_main, related_file in files:
                    if not fileitem.fileid:
                        logger.warn(f"【整理接管】文件缺少 fileid: {fileitem.path}")
                        # 如果是主文件缺少 fileid，标记任务失败
                        if is_main:
                            task_path = (
                                task.fileitem.path if task and task.fileitem else None
                            )
                            if task_path:
                                task_failures[task_path] = (
                                    f"文件缺少 fileid: {fileitem.path}"
                                )
                        continue

                    # 检查目标文件是否已存在
                    existing_item = existing_files_map.get(target_name)

                    # 判断是否为附加文件（字幕、音轨）
                    is_extra_file = False
                    if related_file:
                        # 关联文件（字幕、音轨）强制覆盖
                        is_extra_file = True
                    elif fileitem.extension:
                        # 检查文件扩展名是否为附加文件类型
                        file_ext = f".{fileitem.extension.lower()}"
                        is_extra_file = file_ext in (
                            settings.RMT_SUBEXT + settings.RMT_AUDIOEXT
                        )

                    if existing_item:
                        # 目标文件已存在
                        if is_extra_file:
                            # 附加文件强制覆盖
                            logger.info(
                                f"【整理接管】目标文件已存在，附加文件强制覆盖: {target_dir / target_name}"
                            )
                            files_to_delete.append(existing_item)
                            existing_files_map.pop(target_name, None)
                        else:
                            # 主视频文件，根据 overwrite_mode 决定是否覆盖
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
                                        target_storage=self._handler.storage_name,
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
                                        f"【整理接管】目标文件已存在，覆盖模式=size，源文件更大 ({source_size} > {target_size})，将覆盖: {target_dir / target_name}"
                                    )
                                else:
                                    skip_reason = "媒体库存在同名文件，且质量更好"
                                    logger.info(
                                        f"【整理接管】目标文件已存在，覆盖模式=size，目标文件质量更好 ({target_size} >= {source_size})，跳过: {target_dir / target_name}"
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
                            if over_flag:
                                files_to_delete.append(existing_item)
                                existing_files_map.pop(target_name, None)
                    else:
                        # 目标文件不存在，但如果是 latest 模式，需要删除其他版本文件
                        if not is_extra_file and task.overwrite_mode == "latest":
                            # 收集到批量删除列表，循环外统一处理
                            version_delete_tasks[target_dir].append(
                                (target_dir / target_name, task)
                            )

                    file_id = int(fileitem.fileid)
                    file_ids.append(file_id)
                    file_mapping[file_id] = (task, is_main, target_name, related_file)

                # 批量删除已存在的文件
                if files_to_delete:
                    logger.info(
                        f"【整理接管】批量删除 {len(files_to_delete)} 个已存在的目标文件"
                    )
                    # 收集需要删除的文件 ID
                    delete_file_ids = []
                    delete_file_mapping: Dict[int, FileItem] = {}  # file_id -> FileItem
                    for existing_item in files_to_delete:
                        if existing_item.fileid:
                            file_id = int(existing_item.fileid)
                            delete_file_ids.append(file_id)
                            delete_file_mapping[file_id] = existing_item

                    if delete_file_ids:
                        try:
                            # 批量删除
                            resp = self._handler.client.fs_delete(
                                delete_file_ids, **configer.get_ios_ua_app(app=False)
                            )
                            check_response(resp)
                            for file_id in delete_file_ids:
                                self._handler.cache_updater.remove_cache(file_id)
                            logger.info(
                                f"【整理接管】批量删除成功: {len(delete_file_ids)} 个文件"
                            )
                        except Exception as batch_delete_error:
                            logger.error(
                                f"【整理接管】批量删除失败: {batch_delete_error}",
                                exc_info=True,
                            )
                            # 批量删除失败，从待处理列表中移除对应的文件
                            for file_id in delete_file_ids:
                                existing_item = delete_file_mapping.get(file_id)
                                if existing_item:
                                    # 找到对应的 file_id 并移除
                                    file_id_to_remove = None
                                    for fid, (
                                        t,
                                        is_m,
                                        t_name,
                                        rf,
                                    ) in file_mapping.items():
                                        if t_name == existing_item.name:
                                            file_id_to_remove = fid
                                            break
                                    if file_id_to_remove:
                                        file_ids.remove(file_id_to_remove)
                                        file_mapping.pop(file_id_to_remove, None)

                # 批量删除版本文件（latest 模式，目标文件不存在时）
                if version_delete_tasks:
                    self._handler._batch_delete_version_files(version_delete_tasks)

                if not file_ids:
                    continue

                # 执行批量 移动 /复制
                if transfer_type == "move":
                    try:
                        resp = self._handler.client.fs_move(
                            file_ids,
                            pid=target_dir_id,
                            **configer.get_ios_ua_app(app=False),
                        )
                        check_response(resp)
                        for file_id, (
                            task,
                            is_main,
                            target_name,
                            related_file,
                        ) in file_mapping.items():
                            try:
                                target_path = target_dir / target_name
                                new_fileitem = FileItem(
                                    storage=self._handler.storage_name,
                                    path=str(target_path),
                                    name=target_name,
                                    fileid=str(file_id),
                                    type="file",
                                    size=task.fileitem.size
                                    if is_main
                                    else (
                                        related_file.fileitem.size
                                        if related_file
                                        else 0
                                    ),
                                    modify_time=task.fileitem.modify_time
                                    if is_main
                                    else (
                                        related_file.fileitem.modify_time
                                        if related_file
                                        else 0
                                    ),
                                    pickcode=task.fileitem.pickcode
                                    if is_main
                                    else (
                                        related_file.fileitem.pickcode
                                        if related_file
                                        else None
                                    ),
                                )
                                self._handler.cache_updater.update_file_cache(
                                    new_fileitem
                                )
                            except Exception as cache_error:
                                logger.debug(
                                    f"【整理接管】更新移动文件缓存失败 (file_id: {file_id}): {cache_error}"
                                )
                        logger.info(
                            f"【整理接管】批量移动 {len(file_ids)} 个文件到 {target_dir}"
                        )
                        # 标记所有文件移动成功
                        for file_id, (
                            task,
                            is_main,
                            target_name,
                            related_file,
                        ) in file_mapping.items():
                            if is_main:
                                task_path = (
                                    task.fileitem.path
                                    if task and task.fileitem
                                    else None
                                )
                                if task_path:
                                    task_main_file_status[task_path] = True
                    except Exception as batch_error:
                        logger.error(
                            f"【整理接管】批量移动失败: {batch_error}",
                            exc_info=True,
                        )
                        # 记录失败的主文件对应的任务
                        for file_id in file_ids:
                            task, is_main, target_name, related_file = file_mapping.get(
                                file_id, (None, False, "", None)
                            )
                            if task and is_main:
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
                        resp = self._handler.client.fs_copy(
                            file_ids,
                            pid=target_dir_id,
                            **configer.get_ios_ua_app(app=False),
                        )
                        check_response(resp)
                        logger.info(
                            f"【整理接管】批量复制 {len(file_ids)} 个文件到 {target_dir}"
                        )
                        self.update_file_ids_after_copy(target_dir, file_mapping)
                        for file_id, (
                            task,
                            is_main,
                            target_name,
                            related_file,
                        ) in file_mapping.items():
                            try:
                                actual_fileid = (
                                    task.fileitem.fileid
                                    if is_main
                                    else (
                                        related_file.fileitem.fileid
                                        if related_file
                                        else None
                                    )
                                )
                                if actual_fileid:
                                    target_path = target_dir / target_name
                                    new_fileitem = FileItem(
                                        storage=self._handler.storage_name,
                                        path=str(target_path),
                                        name=target_name,
                                        fileid=actual_fileid,
                                        type="file",
                                        size=task.fileitem.size
                                        if is_main
                                        else (
                                            related_file.fileitem.size
                                            if related_file
                                            else 0
                                        ),
                                        modify_time=task.fileitem.modify_time
                                        if is_main
                                        else (
                                            related_file.fileitem.modify_time
                                            if related_file
                                            else 0
                                        ),
                                        pickcode=task.fileitem.pickcode
                                        if is_main
                                        else (
                                            related_file.fileitem.pickcode
                                            if related_file
                                            else None
                                        ),
                                    )
                                    self._handler.cache_updater.update_file_cache(
                                        new_fileitem
                                    )
                                    # 标记主文件复制成功
                                    if is_main:
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
                        # 记录失败的主文件对应的任务
                        for file_id in file_ids:
                            task, is_main, target_name, related_file = file_mapping.get(
                                file_id, (None, False, "", None)
                            )
                            if task and is_main:
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
                for _, _, task, _, _ in files:
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

        # 收集失败和成功的任务
        failed_tasks: List[Tuple[TransferTask, str]] = []
        success_tasks: List[TransferTask] = []
        # 需要检查的任务（有 fileid 但状态未标记，可能是文件已存在被跳过但未正确标记）
        tasks_to_check: List[TransferTask] = []

        for task in tasks:
            task_path = task.fileitem.path if task and task.fileitem else None
            if task_path and task_path in task_failures:
                failed_tasks.append((task, task_failures[task_path]))
            elif task_path and task_main_file_status.get(task_path, False):
                success_tasks.append(task)
            else:
                # 主文件未处理或处理失败
                # 如果文件有 fileid，可能是已存在被跳过但未正确标记状态
                if task.fileitem.fileid:
                    tasks_to_check.append(task)
                else:
                    failed_tasks.append((task, "主文件移动/复制未完成"))

        # 批量检查需要确认的任务（避免逐个调用 API）
        if tasks_to_check:
            # 按目标目录分组，批量检查
            tasks_by_dir: Dict[Path, List[TransferTask]] = defaultdict(list)
            for task in tasks_to_check:
                tasks_by_dir[task.target_dir].append(task)

            for target_dir, dir_tasks in tasks_by_dir.items():
                try:
                    # 批量列出目标目录的文件
                    folder_item = self._handler._get_folder(target_dir)
                    if folder_item:
                        existing_files = self._handler.cache_updater._p115_api.list(
                            folder_item
                        )
                        if existing_files:
                            # 创建文件名到 FileItem 的映射
                            existing_files_map = {
                                f.name: f for f in existing_files if f.type == "file"
                            }
                            # 检查每个任务的文件是否存在
                            for task in dir_tasks:
                                if task.target_name in existing_files_map:
                                    # 文件已在目标位置，视为成功
                                    success_tasks.append(task)
                                else:
                                    failed_tasks.append((task, "主文件移动/复制未完成"))
                        else:
                            # 目录为空，所有任务都失败
                            for task in dir_tasks:
                                failed_tasks.append((task, "主文件移动/复制未完成"))
                    else:
                        # 无法获取目录，所有任务都失败
                        for task in dir_tasks:
                            failed_tasks.append((task, "主文件移动/复制未完成"))
                except Exception as e:
                    logger.warn(
                        f"【整理接管】批量检查文件存在性失败 (目录: {target_dir}): {e}"
                    )
                    # 检查失败，所有任务都标记为失败
                    for task in dir_tasks:
                        failed_tasks.append((task, "主文件移动/复制未完成"))

        logger.info(
            f"【整理接管】批量移动/复制完成，成功: {len(success_tasks)} 个，失败: {len(failed_tasks)} 个"
        )

        return failed_tasks, success_tasks

    def update_file_ids_after_copy(
        self,
        target_dir: Path,
        file_mapping: Dict[int, Tuple[TransferTask, bool, str, Optional[RelatedFile]]],
    ) -> None:
        """
        批量更新复制后的 文件 ID

        :param target_dir: 目标目录
        :param file_mapping: 文件ID到任务信息的映射
        """
        try:
            # 获取目标目录的文件列表
            target_dir_fileitem = FileItem(
                storage=self._handler.storage_name,
                path=str(target_dir) + "/",
                type="dir",
            )
            files = self._handler.cache_updater._p115_api.list(target_dir_fileitem)

            if not files:
                logger.warn(f"【整理接管】目标目录 {target_dir} 为空，无法更新文件ID")
                return

            # 创建文件名到文件项的映射
            file_map: Dict[str, FileItem] = {
                f.name: f for f in files if f.type == "file"
            }

            # 更新每个文件的任务信息
            for file_id, (
                task,
                is_main,
                target_name,
                related_file,
            ) in file_mapping.items():
                # 复制后文件保留 115 源文件名，尚未重命名，用 fileitem.name 查找
                if is_main:
                    source_name = task.fileitem.name
                elif related_file:
                    source_name = related_file.fileitem.name
                else:
                    source_name = target_name
                if source_name in file_map:
                    new_fileitem = file_map[source_name]
                    if new_fileitem.fileid:
                        if is_main:
                            task.fileitem.fileid = new_fileitem.fileid
                            task.fileitem.pickcode = (
                                new_fileitem.pickcode or task.fileitem.pickcode
                            )
                            logger.debug(
                                f"【整理接管】更新主视频文件ID: {source_name} -> {new_fileitem.fileid}"
                            )
                        elif related_file:
                            related_file.fileitem.fileid = new_fileitem.fileid
                            related_file.fileitem.pickcode = (
                                new_fileitem.pickcode or related_file.fileitem.pickcode
                            )
                            logger.debug(
                                f"【整理接管】更新关联文件ID: {source_name} -> {new_fileitem.fileid}"
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

    def batch_rename_files(
        self, tasks: List[TransferTask]
    ) -> Tuple[List[Tuple[TransferTask, str]], List[TransferTask]]:
        """
        批量重命名文件

        :param tasks: 任务列表

        :return: (失败任务列表, 成功任务列表)
        """
        logger.info("【整理接管】开始批量重命名文件")

        # 收集需要重命名的文件（file_id, new_name, task, is_main）
        rename_items: List[Tuple[int, str, TransferTask, bool]] = []

        for task in tasks:
            # 检查主视频是否需要重命名
            source_name = Path(task.fileitem.path).name
            target_name = task.target_name
            if source_name != target_name and task.fileitem.fileid:
                rename_items.append(
                    (int(task.fileitem.fileid), target_name, task, True)
                )

            # 检查关联文件是否需要重命名
            for related_file in task.related_files:
                source_name = Path(related_file.fileitem.path).name
                target_name = related_file.target_path.name
                if source_name != target_name and related_file.fileitem.fileid:
                    rename_items.append(
                        (int(related_file.fileitem.fileid), target_name, task, False)
                    )

        if not rename_items:
            logger.info("【整理接管】没有需要重命名的文件")
            return [], tasks

        try:
            update_name(
                self._handler.client,
                [(file_id, new_name) for file_id, new_name, _, _ in rename_items],
                **configer.get_ios_ua_app(app=False),
            )
            for file_id, new_name, _, _ in rename_items:
                self._handler.cache_updater.update_rename_cache(file_id, new_name)
            logger.info(
                f"【整理接管】批量重命名完成，共重命名 {len(rename_items)} 个文件"
            )
        except Exception as e:
            logger.error(f"【整理接管】批量重命名失败: {e}", exc_info=True)
            # 批量重命名失败，所有任务都失败
            failed_tasks: List[Tuple[TransferTask, str]] = []
            for file_id, new_name, task, is_main in rename_items:
                if is_main:
                    task_path = task.fileitem.path if task and task.fileitem else None
                    if task_path:
                        failed_tasks.append((task, f"批量重命名失败: {new_name}"))

            return failed_tasks, []

        # 所有重命名都成功
        return [], tasks

    def record_history(self, tasks: List[TransferTask]) -> None:
        """
        记录转移历史

        :param tasks: 任务列表
        """
        logger.info("【整理接管】开始记录转移历史")

        # 跟踪成功处理的任务
        successfully_recorded_tasks: List[TransferTask] = []

        for task in tasks:
            try:
                # 构造目标文件项
                target_fileitem = FileItem(
                    storage=self._handler.storage_name,
                    path=str(task.target_path),
                    name=task.target_name,
                    fileid=task.fileitem.fileid,
                    type="file",
                    size=task.fileitem.size,
                    modify_time=task.fileitem.modify_time,
                    pickcode=task.fileitem.pickcode,
                )

                # 构造目标目录项
                target_diritem = FileItem(
                    storage=self._handler.storage_name,
                    path=str(task.target_dir) + "/",
                    name=task.target_dir.name,
                    type="dir",
                )

                # 构造 TransferInfo
                transferinfo = TransferInfo(
                    success=True,
                    fileitem=task.fileitem,
                    target_item=target_fileitem,
                    target_diritem=target_diritem,
                    transfer_type=task.transfer_type,
                    file_list=[task.fileitem.path],
                    file_list_new=[target_fileitem.path],
                    need_scrape=task.need_scrape,
                    need_notify=task.need_notify
                    if task.need_notify is not None
                    else True,
                )

                # 添加关联文件到文件列表
                for related_file in task.related_files:
                    transferinfo.file_list.append(related_file.fileitem.path)
                    transferinfo.file_list_new.append(str(related_file.target_path))

                # 记录成功历史
                history = self._handler.history_oper.add_success(
                    fileitem=task.fileitem,
                    mode=task.transfer_type,
                    meta=task.meta,
                    mediainfo=task.mediainfo,
                    transferinfo=transferinfo,
                    downloader=task.downloader,
                    download_hash=task.download_hash,
                )

                # 关联文件（字幕/音轨）写入历史（每个关联文件独立一条）
                related_file_histories = {}
                try:
                    related_count, related_file_histories = (
                        linked_subtitle_audio.record_related_files_success_history(
                            self._handler, task
                        )
                    )
                    if related_count:
                        logger.debug(
                            f"【整理接管】已写入 {related_count} 个关联文件历史记录: {task.fileitem.name}"
                        )
                except Exception as e:
                    logger.debug(
                        f"【整理接管】写入关联文件历史异常 (任务: {task.fileitem.name}): {e}",
                        exc_info=True,
                    )

                # 标记任务完成
                try:
                    chain = TransferChain()
                    mp_task = self._handler._create_mp_task(task)
                    chain.jobview.finish_task(mp_task)
                    logger.debug(f"【整理接管】标记任务完成: {task.fileitem.path}")
                except Exception as e:
                    logger.warn(f"【整理接管】标记任务完成失败: {e}", exc_info=True)

                # 发送整理完成事件
                eventmanager.send_event(
                    EventType.TransferComplete,
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

                # 关联文件（字幕/音轨）发送对应的事件
                for related_file in task.related_files:
                    related_history = (
                        related_file_histories.get(related_file.fileitem.path)
                        if related_file_histories
                        else None
                    )
                    if related_file.file_type == "subtitle":
                        eventmanager.send_event(
                            EventType.SubtitleTransferComplete,
                            {
                                "fileitem": related_file.fileitem,
                                "meta": task.meta,
                                "mediainfo": task.mediainfo,
                                "transferinfo": TransferInfo(
                                    success=True,
                                    fileitem=related_file.fileitem,
                                    target_item=FileItem(
                                        storage=self._handler.storage_name,
                                        path=str(related_file.target_path),
                                        name=related_file.target_path.name,
                                        fileid=related_file.fileitem.fileid,
                                        type="file",
                                        size=related_file.fileitem.size,
                                        modify_time=related_file.fileitem.modify_time,
                                        pickcode=related_file.fileitem.pickcode,
                                    ),
                                    target_diritem=transferinfo.target_diritem,
                                    transfer_type=task.transfer_type,
                                    file_list=[related_file.fileitem.path],
                                    file_list_new=[str(related_file.target_path)],
                                    need_scrape=False,
                                    need_notify=False,
                                ),
                                "downloader": task.downloader,
                                "download_hash": task.download_hash,
                                "transfer_history_id": related_history.id
                                if related_history
                                else None,
                            },
                        )
                    elif related_file.file_type == "audio_track":
                        eventmanager.send_event(
                            EventType.AudioTransferComplete,
                            {
                                "fileitem": related_file.fileitem,
                                "meta": task.meta,
                                "mediainfo": task.mediainfo,
                                "transferinfo": TransferInfo(
                                    success=True,
                                    fileitem=related_file.fileitem,
                                    target_item=FileItem(
                                        storage=self._handler.storage_name,
                                        path=str(related_file.target_path),
                                        name=related_file.target_path.name,
                                        fileid=related_file.fileitem.fileid,
                                        type="file",
                                        size=related_file.fileitem.size,
                                        modify_time=related_file.fileitem.modify_time,
                                        pickcode=related_file.fileitem.pickcode,
                                    ),
                                    target_diritem=transferinfo.target_diritem,
                                    transfer_type=task.transfer_type,
                                    file_list=[related_file.fileitem.path],
                                    file_list_new=[str(related_file.target_path)],
                                    need_scrape=False,
                                    need_notify=False,
                                ),
                                "downloader": task.downloader,
                                "download_hash": task.download_hash,
                                "transfer_history_id": related_history.id
                                if related_history
                                else None,
                            },
                        )

                # 登记转移成功文件清单到 _success_target_files
                try:
                    chain = TransferChain()
                    with task_lock:
                        # 登记转移成功文件清单
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

                # 整理完成且有成功的任务时，执行 __do_finished 逻辑
                try:
                    chain = TransferChain()
                    mp_task = self._handler._create_mp_task(task)
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

                            # 发送刮削事件
                            if (
                                transferinfo.need_scrape
                                and self._handler._is_media_file(task.fileitem)
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
                self._handler._record_fail(task, f"记录历史失败: {e}")

        # 所有任务处理完成后，统一批量删除空目录
        if successfully_recorded_tasks:
            self._handler._batch_delete_empty_dirs(successfully_recorded_tasks)

        try:
            # 按媒体分组，每个媒体组只需要移除一次
            tasks_by_media = self._handler._group_tasks_by_media(
                successfully_recorded_tasks
            )
            removed_count = self._handler._remove_completed_jobs(
                tasks_by_media, task_action="finish", check_method="is_finished"
            )

            if removed_count > 0:
                logger.info(f"【整理接管】已移除 {removed_count} 个已完成的任务组")
        except Exception as e:
            logger.debug(f"【整理接管】移除任务失败: {e}", exc_info=True)

        logger.info("【整理接管】历史记录完成")
