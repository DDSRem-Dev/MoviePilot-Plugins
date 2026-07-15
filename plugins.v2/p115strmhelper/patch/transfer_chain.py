from functools import wraps
from inspect import Parameter, signature
from pathlib import Path
from threading import Lock
from typing import Callable, Optional, Tuple, TYPE_CHECKING

from app.log import logger

if TYPE_CHECKING:
    from ..helper.transfer import TransferTaskManager, TransferHandler


class TransferChainPatcher:
    """
    TransferChain 补丁管理器
    """

    _original_handle_transfer = None
    _enabled = False
    _task_manager: Optional["TransferTaskManager"] = None
    _handler: Optional["TransferHandler"] = None
    _storage_module: str = ""
    _lock = Lock()

    @classmethod
    def enable(
        cls,
        task_manager: "TransferTaskManager",
        handler: "TransferHandler",
        storage_module: str,
    ):
        """
        启用补丁

        :param task_manager: TransferTaskManager 实例
        :param handler: TransferHandler 实例
        :param storage_module: 存储模块名称
        """
        with cls._lock:
            if cls._enabled:
                logger.debug("【整理接管】补丁已启用，跳过")
                return

            try:
                from app.chain.transfer import TransferChain

                cls._task_manager = task_manager
                cls._handler = handler
                cls._storage_module = storage_module

                # 保存原方法
                cls._original_handle_transfer = (
                    TransferChain._TransferChain__handle_transfer
                )

                # 创建 patched 方法
                @wraps(cls._original_handle_transfer)
                def patched_handle_transfer(
                    self, task, callback: Optional[Callable] = None
                ) -> Optional[Tuple[bool, str]]:
                    """
                    补丁版 TransferChain 整理方法，拦截 115 → 115 的整理任务并委托给插件处理

                    :param self: TransferChain 实例
                    :param task: MoviePilot TransferTask
                    :param callback: 可选的完成回调
                    :return: (成功状态, 消息) 或 None
                    """
                    return cls._patched_handle_transfer(self, task, callback)

                # 应用补丁
                TransferChain._TransferChain__handle_transfer = patched_handle_transfer
                cls._enabled = True
                logger.info("【整理接管】TransferChain 补丁已启用")

            except Exception as e:
                logger.error(f"【整理接管】启用补丁失败: {e}", exc_info=True)

    @classmethod
    def disable(cls):
        """
        禁用补丁
        """
        with cls._lock:
            if not cls._enabled:
                return

            try:
                from app.chain.transfer import TransferChain

                # 恢复原方法
                if cls._original_handle_transfer:
                    TransferChain._TransferChain__handle_transfer = (
                        cls._original_handle_transfer
                    )
                    cls._original_handle_transfer = None

                cls._task_manager = None
                cls._handler = None
                cls._storage_module = ""
                cls._enabled = False
                logger.info("【整理接管】TransferChain 补丁已禁用")

            except Exception as e:
                logger.error(f"【整理接管】禁用补丁失败: {e}", exc_info=True)

    @classmethod
    def _patched_handle_transfer(
        cls, chain_self, task, callback: Optional[Callable] = None
    ) -> Optional[Tuple[bool, str]]:
        """
        Patched 版本的 __handle_transfer
        """
        from app.chain.media import MediaChain
        from app.chain.tmdb import TmdbChain
        from app.core.config import settings
        from app.core.context import MediaInfo
        from app.db.transferhistory_oper import TransferHistoryOper
        from app.helper.directory import DirectoryHelper
        from app.schemas import Notification, TransferInfo
        from app.schemas.types import MediaType, NotificationType

        from ..schemas.transfer import TransferTask as PluginTransferTask

        try:
            ########## 原始方法执行部分 ##########

            transferhis = TransferHistoryOper()
            mediainfo = task.mediainfo
            mediainfo_changed = False
            need_obtain_images = False
            if not mediainfo:
                download_history = task.download_history
                # 下载用户
                if download_history:
                    task.username = download_history.username
                    # 识别媒体信息
                    history_year_conflict = cls._is_movie_year_conflict(
                        task.meta, download_history
                    )
                    if (
                        download_history.tmdbid or download_history.doubanid
                    ) and not history_year_conflict:
                        # 下载记录中已存在识别信息
                        mediainfo: Optional[MediaInfo] = chain_self.recognize_media(
                            mtype=MediaType(download_history.type),
                            tmdbid=download_history.tmdbid,
                            doubanid=download_history.doubanid,
                            episode_group=download_history.episode_group,
                        )
                        need_obtain_images = True
                        if mediainfo:
                            # 更新自定义媒体类别
                            if download_history.media_category:
                                mediainfo.category = download_history.media_category
                    else:
                        if history_year_conflict:
                            logger.info(
                                f"【整理接管】{task.fileitem.name} 文件年份 "
                                f"{task.meta.year} 与下载记录年份 "
                                f"{download_history.year} 不一致，按文件名重新识别"
                            )
                        mediainfo = MediaChain().recognize_by_meta(
                            task.meta, obtain_images=True
                        )
                        if mediainfo and download_history.media_category:
                            mediainfo.category = download_history.media_category
                else:
                    # 识别媒体信息（obtain_images=True 内部已完成图片获取）
                    mediainfo = MediaChain().recognize_by_meta(
                        task.meta, obtain_images=True
                    )

                # 按名称识别时已在识别链路补图，这里只补齐显式ID识别的场景
                if mediainfo and need_obtain_images:
                    chain_self.obtain_images(mediainfo=mediainfo)

                if not mediainfo:
                    # preview 模式下不创建历史记录
                    if task.preview:
                        return False, "未识别到媒体信息"
                    # 新增整理失败历史记录
                    his = transferhis.add_fail(
                        fileitem=task.fileitem,
                        mode=task.transfer_type,
                        meta=task.meta,
                        downloader=task.downloader,
                        download_hash=task.download_hash,
                    )
                    chain_self.post_message(
                        Notification(
                            mtype=NotificationType.Manual,
                            title=f"{task.fileitem.name} 未识别到媒体信息，无法入库！",
                            text=(
                                "原因：未识别到媒体信息\n"
                                "如果按钮不可用，可回复：\n"
                                f"```\n/redo {his.id}\n/redo {his.id} [tmdbid]|[类型]\n```\n"
                                "自动重试或手动识别整理。"
                            ),
                            username=task.username,
                            link=settings.MP_DOMAIN("#/history"),
                            buttons=chain_self.build_failed_transfer_buttons(
                                his.id if his else None
                            ),
                            save_history=False,
                        )
                    )
                    # 任务失败，直接移除task
                    chain_self.jobview.remove_task(task.fileitem)

                    # AI智能体自动重试整理
                    if (
                        his
                        and settings.AI_AGENT_ENABLE
                        and settings.AI_AGENT_RETRY_TRANSFER
                    ):
                        try:
                            import asyncio
                            from app.core import global_vars

                            group_key = (
                                task.download_hash
                                or str(task.fileitem.path).rsplit("/", 1)[0]
                                if task.fileitem
                                else ""
                            )
                            asyncio.run_coroutine_threadsafe(
                                chain_self.retry_scheduler.schedule_retry(
                                    his.id, group_key=group_key
                                ),
                                global_vars.loop,
                            )
                            logger.info(
                                f"【整理接管】已触发AI智能体重试整理历史记录 #{his.id}"
                            )
                        except Exception as e:
                            logger.error(f"【整理接管】触发AI智能体重试整理失败: {e}")

                    return False, "未识别到媒体信息"

                mediainfo_changed = True

            # 如果未开启新增已入库媒体是否跟随TMDB信息变化则根据tmdbid查询之前的title
            if not settings.SCRAP_FOLLOW_TMDB:
                transfer_history = transferhis.get_by_type_tmdbid(
                    tmdbid=mediainfo.tmdb_id, mtype=mediainfo.type.value
                )
                if transfer_history and mediainfo.title != transfer_history.title:
                    mediainfo.title = transfer_history.title
                    mediainfo_changed = True

            if mediainfo_changed:
                # 更新任务信息
                task.mediainfo = mediainfo
                # 更新队列任务
                curr_task = chain_self.jobview.remove_task(task.fileitem)
                chain_self.jobview.add_task(
                    task, state=curr_task.state if curr_task else "waiting"
                )

            # 获取集数据
            if task.mediainfo.type == MediaType.TV and not task.episodes_info:
                # 判断注意season为0的情况
                season_num = task.mediainfo.season
                if season_num is None and task.meta.season_seq:
                    if task.meta.season_seq.isdigit():
                        season_num = int(task.meta.season_seq)
                # 默认值1
                if season_num is None:
                    season_num = 1
                task.episodes_info = TmdbChain().tmdb_episodes(
                    tmdbid=task.mediainfo.tmdb_id,
                    season=season_num,
                    episode_group=task.mediainfo.episode_group,
                )

            # 查询整理目标目录
            if not task.target_directory:
                if task.target_path:
                    # 指定目标路径，`手动整理`场景下使用，忽略源目录匹配，使用指定目录匹配
                    task.target_directory = DirectoryHelper().get_dir(
                        media=task.mediainfo,
                        dest_path=task.target_path,
                        target_storage=task.target_storage,
                    )
                else:
                    # 启用源目录匹配时，根据源目录匹配下载目录，否则按源目录同盘优先原则，如无源目录，则根据媒体信息获取目标目录
                    task.target_directory = DirectoryHelper().get_dir(
                        media=task.mediainfo,
                        storage=task.fileitem.storage,
                        src_path=Path(task.fileitem.path),
                        target_storage=task.target_storage,
                    )
            if not task.target_storage and task.target_directory:
                task.target_storage = task.target_directory.library_storage

            source_storage = task.fileitem.storage
            target_storage = task.target_storage

            ########## 原始方法执行结束 ##########

            # 如果是目录（蓝光原盘），回退到原方法处理
            if task.fileitem.type == "dir":
                logger.debug(
                    f"【整理接管】检测到目录类型任务（可能是蓝光原盘），回退到原方法: {task.fileitem.path}"
                )
                return cls._call_original_transfer_part(chain_self, task, callback)

            if (
                cls._should_intercept(source_storage, target_storage)
                and cls._task_manager is not None
            ):
                logger.debug(
                    f"【整理接管】检测到 115 → 115 整理任务: {task.fileitem.name}"
                )

                from ..core.config import configer
                from ..helper.transfer.linked_subtitle_audio import (
                    is_subtitle_or_audio_file,
                )

                if (
                    configer.pan_transfer_linked_subtitle_audio
                    and is_subtitle_or_audio_file(task.fileitem)
                ):
                    logger.debug(
                        f"【整理接管】忽略字幕/音频文件（将跟随主文件一起处理）: {task.fileitem.name}"
                    )
                    chain_self.jobview.running_task(task)
                    chain_self.jobview.finish_task(task)
                    if chain_self.jobview.is_done(task):
                        chain_self.jobview.remove_job(task)
                    return True, "已由插件接管（字幕/音频文件，跟随主文件处理）"

                need_rename, need_notify, need_scrape = cls._derive_transfer_flags(task)

                # preview 模式：只计算目标路径并返回预览结果，不执行实际整理
                if task.preview:
                    return cls._handle_preview(
                        chain_self,
                        task,
                        callback,
                        need_rename,
                        need_notify,
                        need_scrape,
                    )

                # 注意：这个验证在 transfer_media 中进行，但由于我们拦截了，需要在这里进行
                if task.mediainfo.type == MediaType.TV and task.fileitem.type == "file":
                    if task.meta.begin_episode is None:
                        logger.warn(
                            f"【整理接管】文件 {task.fileitem.path} 整理失败：未识别到文件集数"
                        )
                        fail_msg = "未识别到文件集数"
                        src_path = task.fileitem.path
                        transferhis.add_fail(
                            fileitem=task.fileitem,
                            mode=task.transfer_type or "",
                            meta=task.meta,
                            mediainfo=task.mediainfo,
                            transferinfo=TransferInfo(
                                success=False,
                                fileitem=task.fileitem,
                                message=fail_msg,
                                transfer_type=task.transfer_type,
                                file_list=[src_path],
                                fail_list=[src_path],
                                need_notify=need_notify,
                                need_scrape=need_scrape,
                            ),
                            downloader=task.downloader,
                            download_hash=task.download_hash,
                        )
                        chain_self.jobview.remove_task(task.fileitem)
                        return False, "未识别到文件集数"

                    # 文件结束季为空
                    task.meta.end_season = None
                    # 文件总季数为1
                    if task.meta.total_season:
                        task.meta.total_season = 1
                    # 文件不可能超过2集
                    if task.meta.total_episode and task.meta.total_episode > 2:
                        task.meta.total_episode = 1
                        task.meta.end_episode = None

                # 计算目标路径
                target_path = cls._compute_target_path(task, need_rename=need_rename)
                if not target_path:
                    logger.error(f"【整理接管】计算目标路径失败: {task.fileitem.path}")
                    # 回退到原方法
                    return cls._call_original_transfer_part(chain_self, task, callback)

                # 确定整理方式
                transfer_type = task.transfer_type
                if not transfer_type and task.target_directory:
                    transfer_type = task.target_directory.transfer_type

                # 获取覆盖模式
                overwrite_mode = None
                if task.target_directory:
                    overwrite_mode = task.target_directory.overwrite_mode

                # 正在处理
                chain_self.jobview.running_task(task)

                # 创建插件的 TransferTask
                plugin_task = PluginTransferTask(
                    fileitem=task.fileitem,
                    target_path=target_path,
                    mediainfo=task.mediainfo,
                    meta=task.meta,
                    transfer_type=transfer_type or "move",
                    overwrite_mode=overwrite_mode,
                    need_rename=need_rename,
                    need_notify=need_notify,
                    need_scrape=need_scrape,
                    scrape=task.scrape,
                    manual=task.manual,
                    background=task.background,
                    username=task.username,
                    downloader=task.downloader,
                    download_hash=task.download_hash,
                )

                # 加入批量队列
                cls._task_manager.add_task(plugin_task)

                logger.info(
                    f"【整理接管】任务已加入批量队列: {task.fileitem.name} -> {target_path}"
                )

                return True, "已由插件接管"

            # 非 115 -> 115 原方法整理
            return cls._call_original_transfer_part(chain_self, task, callback)

        except Exception as e:
            logger.error(
                f"【整理接管】Patched handle_transfer 异常: {e}", exc_info=True
            )
            try:
                return cls._call_original(chain_self, task, callback)
            except Exception as fallback_error:
                logger.error(f"【整理接管】回退到原方法也失败: {fallback_error}")
                return False, f"整理异常: {e}"
        finally:
            # 与原生 __handle_transfer 一致：每次处理完尝试移除已完成作业，并清理批次 pending 集合
            chain_self.jobview.try_remove_job(task)
            chain_self._TransferChain__finish_scrape_batch_task(task)

    @classmethod
    def _derive_transfer_flags(cls, task) -> Tuple[bool, bool, bool]:
        """
        与 app.modules.filemanager 中 transfer() 一致，推导 need_rename / need_notify / need_scrape

        :param task: MoviePilot TransferTask
        :return: (need_rename, need_notify, need_scrape)
        """
        if task.target_directory:
            need_rename = bool(task.target_directory.renaming)
            need_notify = bool(task.target_directory.notify)
            if task.scrape is None:
                need_scrape = bool(task.target_directory.scraping)
            else:
                need_scrape = bool(task.scrape)
            return need_rename, need_notify, need_scrape
        if task.target_path:
            need_rename = True
            need_notify = False
            need_scrape = bool(task.scrape) if task.scrape is not None else False
            return need_rename, need_notify, need_scrape
        need_rename = True
        need_notify = True
        need_scrape = bool(task.scrape) if task.scrape is not None else False
        return need_rename, need_notify, need_scrape

    @classmethod
    def _should_intercept(cls, source_storage: str, target_storage: str) -> bool:
        """
        判断是否应该拦截

        :param source_storage: 源存储
        :param target_storage: 目标存储
        :return: 是否应该拦截
        """
        return (
            cls._enabled
            and cls._storage_module
            and source_storage == cls._storage_module
            and target_storage == cls._storage_module
        )

    @staticmethod
    def _is_movie_year_conflict(file_meta, media) -> bool:
        """
        判断文件名年份是否与已识别电影年份冲突
        """
        from app.schemas.types import MediaType

        file_year = getattr(file_meta, "year", None)
        media_year = getattr(media, "year", None)
        if not file_meta or not media or not file_year or not media_year:
            return False
        media_type = getattr(media, "type", None)
        if not isinstance(media_type, MediaType):
            try:
                media_type = MediaType(media_type)
            except (TypeError, ValueError):
                return False
        return media_type == MediaType.MOVIE and str(file_year) != str(media_year)

    @classmethod
    def _compute_target_path(cls, task, need_rename: bool = True) -> Optional[Path]:
        """
        与 TransHandler.transfer_media 单文件分支一致的目标路径

        :param task: MoviePilot 的 TransferTask
        :param need_rename: 是否与 MP 目录 renaming 一致
        :return: 目标路径，失败返回 None
        """
        from app.core.config import settings
        from app.modules.filemanager.transhandler import TransHandler
        from app.schemas.types import MediaType

        try:
            handler = TransHandler()

            target_dir = handler.get_dest_dir(
                mediainfo=task.mediainfo,
                target_dir=task.target_directory,
                need_type_folder=task.library_type_folder,
                need_category_folder=task.library_category_folder,
            )

            if not target_dir:
                logger.error("【整理接管】计算目标目录失败")
                return None

            if not need_rename:
                return target_dir / task.fileitem.name

            if task.mediainfo.type == MediaType.TV:
                rename_format = settings.TV_RENAME_FORMAT
            else:
                rename_format = settings.MOVIE_RENAME_FORMAT

            file_ext = Path(task.fileitem.name).suffix

            naming_dict = handler.get_naming_dict(
                meta=task.meta,
                mediainfo=task.mediainfo,
                file_ext=file_ext,
                episodes_info=task.episodes_info,
            )

            # 触发 TransferRenameBuild 事件，允许插件注入命名字段
            try:
                from app.core.event import eventmanager
                from app.schemas import TransferRenameBuildEventData
                from app.schemas.types import ChainEventType

                build_event_data = TransferRenameBuildEventData(
                    rename_dict=naming_dict,
                    meta=task.meta,
                    mediainfo=task.mediainfo,
                    file_ext=file_ext,
                    episodes_info=task.episodes_info,
                )
                build_event = eventmanager.send_event(
                    ChainEventType.TransferRenameBuild, build_event_data
                )
                if build_event and build_event.event_data:
                    naming_dict = build_event.event_data.rename_dict
            except Exception:
                pass

            rename_kwargs = {
                "template_string": rename_format,
                "rename_dict": naming_dict,
                "path": target_dir,
            }
            try:
                sig = signature(handler.get_rename_path)
                has_varkw = any(
                    p.kind == Parameter.VAR_KEYWORD for p in sig.parameters.values()
                )
                if "source_path" in sig.parameters or has_varkw:
                    rename_kwargs["source_path"] = task.fileitem.path
                if "source_item" in sig.parameters or has_varkw:
                    rename_kwargs["source_item"] = task.fileitem
            except (TypeError, ValueError):
                pass
            rename_path = handler.get_rename_path(**rename_kwargs)

            if not rename_path:
                return None

            new_file = (
                Path(rename_path) if not isinstance(rename_path, Path) else rename_path
            )

            if task.fileitem.extension:
                ext = f".{task.fileitem.extension.lower()}"
                if ext in settings.RMT_SUBEXT:
                    new_file = TransHandler._TransHandler__rename_subtitles(
                        task.fileitem, new_file
                    )

            return new_file

        except Exception as e:
            logger.error(f"【整理接管】计算目标路径失败: {e}", exc_info=True)
            return None

    @classmethod
    def _handle_preview(
        cls,
        chain_self,
        task,
        callback: Optional[Callable],
        need_rename: bool,
        need_notify: bool,
        need_scrape: bool,
    ) -> Optional[Tuple[bool, str]]:
        """
        Preview 模式：只计算目标路径，不执行实际文件操作

        :param chain_self: TransferChain 实例
        :param task: MoviePilot TransferTask
        :param callback: 回调函数（preview 模式下为 _preview_callback）
        :param need_rename: 是否需要重命名
        :param need_notify: 是否需要通知
        :param need_scrape: 是否需要刮削
        :return: 回调结果或 (True, target_path)
        """
        try:
            target_path = cls._compute_target_path(task, need_rename=need_rename)
            if not target_path:
                logger.error(
                    f"【整理接管】Preview 模式计算目标路径失败: {task.fileitem.path}"
                )
                return False, "计算目标路径失败"

            transfer_type = task.transfer_type
            if not transfer_type and task.target_directory:
                transfer_type = task.target_directory.transfer_type

            target_storage = task.target_storage or ""
            from app.schemas import FileItem, TransferInfo

            transferinfo = TransferInfo(
                success=True,
                fileitem=task.fileitem,
                target_item=FileItem(
                    storage=target_storage,
                    path=str(target_path),
                    name=target_path.name,
                    type="file",
                ),
                target_diritem=FileItem(
                    storage=target_storage,
                    path=str(target_path.parent) + "/",
                    name=target_path.parent.name,
                    type="dir",
                ),
                transfer_type=transfer_type or "move",
                file_list=[task.fileitem.path],
                file_list_new=[str(target_path)],
                need_scrape=need_scrape,
                need_notify=need_notify,
            )

            if callback:
                return callback(task, transferinfo)
            return True, str(target_path)
        except Exception as e:
            logger.error(f"【整理接管】Preview 模式异常: {e}", exc_info=True)
            return False, f"Preview 异常: {e}"

    @classmethod
    def _call_original(
        cls, chain_self, task, callback: Optional[Callable]
    ) -> Optional[Tuple[bool, str]]:
        """
        调用原方法

        :param chain_self: TransferChain 实例
        :param task: 任务
        :param callback: 回调
        :return: 原方法的返回值
        """
        if cls._original_handle_transfer:
            return cls._original_handle_transfer(chain_self, task, callback)
        return None

    @classmethod
    def _call_original_transfer_part(
        cls, chain_self, task, callback: Optional[Callable]
    ) -> Optional[Tuple[bool, str]]:
        """
        调用原方法的 transfer 部分

        :param chain_self: TransferChain 实例
        :param task: 任务
        :param callback: 回调
        :return: 返回值
        """
        from app.core.event import eventmanager
        from app.schemas import StorageOperSelectionEventData, TransferInfo
        from app.schemas.types import ChainEventType

        try:
            # 正在处理
            chain_self.jobview.running_task(task)

            # 获取源存储操作对象
            source_oper = None
            source_event_data = StorageOperSelectionEventData(
                storage=task.fileitem.storage
            )
            source_event = eventmanager.send_event(
                ChainEventType.StorageOperSelection, source_event_data
            )
            if source_event and source_event.event_data:
                source_event_data = source_event.event_data
                if source_event_data.storage_oper:
                    source_oper = source_event_data.storage_oper

            # 获取目标存储操作对象
            target_oper = None
            target_event_data = StorageOperSelectionEventData(
                storage=task.target_storage
            )
            target_event = eventmanager.send_event(
                ChainEventType.StorageOperSelection, target_event_data
            )
            if target_event and target_event.event_data:
                target_event_data = target_event.event_data
                if target_event_data.storage_oper:
                    target_oper = target_event_data.storage_oper

            # 执行整理
            transferinfo: TransferInfo = chain_self.transfer(
                fileitem=task.fileitem,
                meta=task.meta,
                mediainfo=task.mediainfo,
                target_directory=task.target_directory,
                target_storage=task.target_storage,
                target_path=task.target_path,
                transfer_type=task.transfer_type,
                episodes_info=task.episodes_info,
                scrape=task.scrape,
                library_type_folder=task.library_type_folder,
                library_category_folder=task.library_category_folder,
                source_oper=source_oper,
                target_oper=target_oper,
                preview=task.preview,
            )

            if not transferinfo:
                logger.error("文件整理模块运行失败")
                return False, "文件整理模块运行失败"

            if callback:
                return callback(task, transferinfo)

            return transferinfo.success, transferinfo.message

        except Exception as e:
            logger.error(f"【整理接管】执行 transfer 失败: {e}", exc_info=True)
            return False, f"整理失败: {e}"
