from contextlib import contextmanager
from functools import wraps
from logging import ERROR
from time import monotonic, time
from threading import Condition, Lock, Thread, Event as ThreadEvent, current_thread
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from watchfiles import watch, Change

from ..core.aliyunpan import BAligo
from ..core.config import configer
from ..core.p115_client import create_client
from ..core.i18n import i18n
from ..core.message import post_message
from ..core.p115 import get_pid_by_path
from ..helper.clean import Cleaner
from ..helper.life import MonitorLife
from ..helper.mediainfo_download import MediaInfoDownloader
from ..helper.monitor import (
    directory_upload_rescan,
    directory_upload_stability_tracker,
)
from ..helper.monitor.directory_upload_queue import (
    DirectoryUploadTask,
    directory_upload_queue,
)
from ..helper.offline import OfflineDownloadHelper
from ..helper.r302 import Redirect
from ..helper.share import ShareTransferHelper
from ..helper.strm import (
    FullSyncStrmHelper,
    IncrementSyncStrmHelper,
    ShareInteractiveGenStrmQueue,
    ShareStrmHelper,
)
from ..helper.strm.share import share_audit_download_queue, share_strm_cleaner
from ..helper.transfer.durable import DurableBatchTransfer
from ..helper.webdav import WebdavCore
from ..helper.mediaserver import emby_mediainfo_queue
from ..helper.mediasyncdel.webhook_queue import sync_del_webhook_queue
from ..patch import TransferChainPatcher
from ..schemas.monitor import ObserverInfo
from ..service.backup import BackupService
from ..service.fuse import FuseManager
from ..service.one_shot import schedule_plugin_one_shot
from ..service.life import monitor_life_thread_worker
from ..service.hdhive_checkin.scheduler import hdhive_checkin_scheduler_tick
from ..service.p115_checkin.scheduler import (
    p115_checkin_scheduler_tick as p115_scheduler_tick,
)
from ..utils.sentry import sentry_manager

from app.sdk.logging import logger
from app.schemas import MessageType
from app.sdk.scheduler import list_scheduler_jobs, update_plugin_job


def _track_sync_operation(func: Callable) -> Callable:
    """
    跟踪同步调用及同线程嵌套，让已登记全量任务留在增量关停屏障内
    """

    @wraps(func)
    def wrapper(self: "ServiceHelper", *args: Any, **kwargs: Any) -> Any:
        with self.sync_operation():
            return func(self, *args, **kwargs)

    return wrapper


@sentry_manager.capture_all_class_exceptions
class ServiceHelper:
    """
    服务项
    """

    def __init__(self):
        self.client = None
        self.mediainfodownloader: Optional[MediaInfoDownloader] = None
        self.monitorlife: Optional[MonitorLife] = None
        self.aligo: Optional[BAligo] = None

        self.sharetransferhelper: Optional[ShareTransferHelper] = None

        self.monitor_stop_event: Optional[ThreadEvent] = None
        self.monitor_life_thread: Optional[Thread] = None
        self.monitor_life_lock = Lock()
        self.monitor_life_fail_time: Optional[float] = None

        self.offlinehelper: Optional[OfflineDownloadHelper] = None

        self.redirect: Optional[Redirect] = None

        self.service_observer: List[ObserverInfo] = []

        self.fuse_manager: Optional[FuseManager] = None
        self.backup_service = BackupService()

        self.transfer_task_manager: Optional[DurableBatchTransfer] = None
        self.transfer_handler: Optional[DurableBatchTransfer] = None

        self.webdav_core: Optional[WebdavCore] = None

        self.share_interactive_gen_strm_queue = ShareInteractiveGenStrmQueue()

        self._sync_state_lock = Lock()
        self._full_sync_running = False
        self._increment_sync_running = False
        self._full_sync_pending = False
        self._sync_condition = Condition()
        self._sync_operations: Dict[Thread, int] = {}
        self._sync_stopping = False

    def init_service(self) -> bool:
        """
        初始化服务
        """
        if not self._stop_sync_operations(timeout=0):
            logger.warning("【同步服务】旧任务尚未退出，拒绝重新初始化")
            return False
        if self.backup_service.stop() is False:
            logger.warning("【STRM备份】旧任务尚未退出，拒绝重新初始化")
            return False
        try:
            # 115 网盘客户端初始化
            self.client = create_client(
                configer.cookies,
                default_timeout=configer.get_default_timeout(),
                slow_timeout=configer.get_slow_timeout(),
            )

            # 阿里云盘登入
            aligo_config = Path(configer.get_config("plugin_aligo_path")).resolve()
            try:
                if configer.get_config("aliyundrive_token"):
                    aligo_config.mkdir(parents=True, exist_ok=True)
                    aligo_name = str(aligo_config / "aligo")
                    if Path(aligo_config / "aligo.json").exists():
                        logger.debug("Config login aliyunpan")
                        self.aligo = BAligo(
                            name=aligo_name, level=ERROR, re_login=False
                        )
                    else:
                        logger.debug("Refresh token login aliyunpan")
                        self.aligo = BAligo(
                            name=aligo_name,
                            refresh_token=configer.get_config("aliyundrive_token"),
                            level=ERROR,
                            re_login=False,
                        )
                    # 默认操作资源盘
                    v2_user = self.aligo.v2_user_get()
                    logger.debug(f"AliyunPan user info: {v2_user}")
                    resource_drive_id = v2_user.resource_drive_id
                    self.aligo.default_drive_id = resource_drive_id
                elif (
                    not configer.get_config("aliyundrive_token")
                    and not Path(aligo_config / "aligo.json").exists()
                ):
                    logger.debug("Login out aliyunpan")
                    self.aligo = None
            except Exception as e:
                logger.warning(f"阿里云盘登入失败，跳过初始化: {e}")
                self.aligo = None

            # 媒体信息下载工具初始化
            self.mediainfodownloader = MediaInfoDownloader(
                cookie=configer.get_config("cookies")
            )
            self.share_interactive_gen_strm_queue.bind_mediainfodownloader(
                self.mediainfodownloader
            )
            share_audit_download_queue.bind_downloader(self.mediainfodownloader)

            # 生活事件监控初始化
            self.monitorlife = MonitorLife(
                client=self.client,
                mediainfodownloader=self.mediainfodownloader,
                stop_event=None,
            )

            # 分享转存初始化
            self.sharetransferhelper = ShareTransferHelper(self.client, self.aligo)

            # 离线下载初始化
            self.offlinehelper = OfflineDownloadHelper(
                client=self.client, monitorlife=self.monitorlife
            )

            # 多端播放初始化
            pid = None
            if configer.get_config("same_playback"):
                pid = get_pid_by_path(self.client, "/多端播放", True, False, False)

            # 302跳转初始化
            self.redirect = Redirect(client=self.client, pid=pid)

            # FUSE 初始化
            self.fuse_manager = FuseManager(client=self.client)
            if configer.fuse_enabled and configer.fuse_mountpoint:
                self.fuse_manager.start_fuse()

            # STRM 备份服务绑定客户端
            self.backup_service = BackupService(client=self.client)

            # 初始化整理任务管理器和 TransferChain 补丁
            self._init_transfer_enhancement()

            # 初始化 Webdav 服务
            self.webdav_core = WebdavCore(client=self.client)

            # 启动 Emby 媒体信息提取全局队列 worker
            emby_mediainfo_queue.start()
            sync_del_webhook_queue.start()

            if configer.share_audit_queue_enabled:
                share_audit_download_queue.start()

            with self._sync_condition:
                self._sync_stopping = False
            return True
        except Exception as e:
            logger.error(f"服务项初始化失败: {e}")
            return False

    def _init_transfer_enhancement(self) -> None:
        """
        初始化或更新接管网盘整理功能
        """
        if self.transfer_task_manager:
            if self.transfer_task_manager.shutdown() is False:
                raise RuntimeError("批量整理仍在运行，待原任务结束后再更新配置")
            self.transfer_task_manager = None
        TransferChainPatcher.disable()
        self.transfer_handler = None

        if configer.pan_transfer_takeover:
            if configer.storage_module != "115网盘Plus":
                logger.warn(
                    "【整理接管】接管网盘整理功能需要存储模块为 '115网盘Plus'，当前存储模块为 "
                    f"'{configer.storage_module}'，接管功能已禁用"
                )
            else:
                try:
                    self.transfer_handler = DurableBatchTransfer()
                    self.transfer_task_manager = self.transfer_handler
                    TransferChainPatcher.enable(
                        task_manager=self.transfer_task_manager,
                        handler=self.transfer_handler,
                        storage_module="115网盘Plus",
                    )
                    logger.info("【整理接管】已启用")
                except Exception as e:
                    logger.error(f"【整理接管】初始化失败: {e}", exc_info=True)
                    TransferChainPatcher.disable()
                    if self.transfer_task_manager:
                        self.transfer_task_manager.shutdown()
                    self.transfer_task_manager = None
                    self.transfer_handler = None

    def is_background_active(self) -> bool:
        """
        判断插件后台是否有活跃任务

        :return bool: 存在运行中的后台线程、目录监控或同步任务时返回 True
        """
        if self.monitor_life_thread and self.monitor_life_thread.is_alive():
            return True
        if any(ob.thread.is_alive() for ob in self.service_observer):
            return True
        with self._sync_state_lock:
            if self._full_sync_running or self._increment_sync_running:
                return True
        prefixes = (
            f"{configer.plugin_id}_P115StrmHelper_",
            f"{configer.plugin_id}_once_",
        )
        return any(
            job.status == "正在运行" and (job.id or "").startswith(prefixes)
            for job in list_scheduler_jobs()
        )

    def check_monitor_life_guard(self):
        """
        检查并守护生活事件监控线程
        """
        should_run = (
            configer.monitor_life_enabled
            and configer.monitor_life_paths
            and configer.monitor_life_event_modes
        ) or (configer.pan_transfer_enabled and configer.pan_transfer_paths)

        with self.monitor_life_lock:
            if should_run:
                is_alive = (
                    self.monitor_life_thread and self.monitor_life_thread.is_alive()
                )

                if is_alive:
                    if self.monitor_life_fail_time is not None:
                        logger.debug("【监控生活事件】线程运行正常，清除失败时间记录")
                        self.monitor_life_fail_time = None
                else:
                    current_time = time()
                    if self.monitor_life_fail_time is None:
                        self.monitor_life_fail_time = current_time
                        logger.debug(
                            "【监控生活事件】检测到线程已停止，开始记录失败时间"
                        )
                    else:
                        fail_duration = current_time - self.monitor_life_fail_time
                        fail_duration_minutes = int(fail_duration / 60)
                        fail_duration_seconds = int(fail_duration % 60)
                        logger.debug(
                            f"【监控生活事件】线程已停止，持续失败时间: {fail_duration_minutes}分{fail_duration_seconds}秒"
                        )

                        if fail_duration >= 300:
                            logger.warning(
                                "【监控生活事件】连续5分钟检测到线程已停止，正在重新启动..."
                            )
                            if configer.notify:
                                post_message(
                                    mtype=MessageType.Plugin,
                                    title=i18n.translate(
                                        "monitor_life_auto_restart_title"
                                    ),
                                    text=f"\n{i18n.translate('monitor_life_auto_restart_text')}\n",
                                )
                            self._start_monitor_life_internal()
                            self.monitor_life_fail_time = None
            else:
                if self.monitor_life_thread and self.monitor_life_thread.is_alive():
                    logger.info("【监控生活事件】配置已关闭，守护线程正在停止线程")
                    self._stop_monitor_life_internal()
                self.monitor_life_fail_time = None

    def start_monitor_life(self):
        """
        启动生活事件监控
        """
        with self.monitor_life_lock:
            self._start_monitor_life_internal(register_guard_service=False)

    def _stop_monitor_life_internal(self) -> bool:
        """
        请求停止生活事件监控并保留尚未退出的线程句柄
        """
        if self.monitor_stop_event:
            self.monitor_stop_event.set()
        if self.monitor_life_thread and self.monitor_life_thread.is_alive():
            logger.info("【监控生活事件】停止生活事件监控线程")
            self.monitor_life_thread.join(timeout=25)
            if self.monitor_life_thread.is_alive():
                logger.warning("【监控生活事件】线程未在预期时间内结束")
                return False
            logger.info("【监控生活事件】线程已正常退出")
        self.monitor_life_thread = None
        self.monitor_stop_event = None
        return True

    def _start_monitor_life_internal(self, register_guard_service: bool = True):
        """
        启动生活事件监控线程

        :param register_guard_service: 是否在启动后调用 _update_monitor_life_guard_service
            初始化时（start_monitor_life）设为 False，让 get_service() 统一注册
            运行时恢复时（check_monitor_life_guard）保留 True，确保守护服务存在
        """
        if (
            configer.get_config("monitor_life_enabled")
            and configer.get_config("monitor_life_paths")
            and configer.get_config("monitor_life_event_modes")
        ) or (
            configer.get_config("pan_transfer_enabled")
            and configer.get_config("pan_transfer_paths")
        ):
            if self.monitor_life_thread and self.monitor_life_thread.is_alive():
                logger.info("【监控生活事件】检测到已有线程在运行，停止旧线程中...")
                self._stop_monitor_life_internal()

            if self.monitor_life_thread and self.monitor_life_thread.is_alive():
                logger.debug("【监控生活事件】线程仍在运行，跳过启动")
                return

            self.monitor_stop_event = ThreadEvent()

            if not self.monitorlife:
                logger.error("【监控生活事件】monitorlife 未初始化，无法启动监控线程")
                return

            self.monitor_life_thread = Thread(
                target=monitor_life_thread_worker,
                args=(
                    self.monitorlife,
                    self.monitor_stop_event,
                ),
                name="P115StrmHelper-MonitorLife",
                daemon=False,
            )
            self.monitor_life_thread.start()
            logger.info("【监控生活事件】生活事件监控线程已启动")
            self.monitor_life_fail_time = None

            if register_guard_service:
                try:
                    self._update_monitor_life_guard_service()
                except Exception as e:
                    logger.debug(f"【监控生活事件】重新注册守护服务失败: {e}")
        else:
            self._stop_monitor_life_internal()

    def _update_monitor_life_guard_service(self) -> None:
        """
        由宿主重新同步声明的周期服务，保留当前实例的有效一次性任务
        """
        try:
            update_plugin_job(configer.plugin_id)
        except Exception as e:
            logger.error(f"【监控生活事件】注册守护服务失败: {e}", exc_info=True)

    @_track_sync_operation
    def full_sync_strm_files(self) -> None:
        """
        全量同步（带并发互斥与优先级控制）
        """
        with self._sync_state_lock:
            if self._full_sync_running:
                logger.info("【全量同步】全量同步已在运行，跳过本次触发")
                return
            if self._increment_sync_running:
                logger.info("【全量同步】增量同步正在运行，已登记待执行全量同步")
                self._full_sync_pending = True
                return
            self._full_sync_running = True
        try:
            self._run_full_sync()
        finally:
            with self._sync_state_lock:
                self._full_sync_running = False

    def _run_full_sync(self):
        """
        全量同步实际执行逻辑
        """
        if (
            not configer.get_config("full_sync_strm_paths")
            or not configer.get_config("moviepilot_address")
            or not configer.get_config("user_download_mediaext")
        ):
            return

        strm_helper = FullSyncStrmHelper(
            client=self.client,
            mediainfodownloader=self.mediainfodownloader,
        )
        strm_helper.strm_exec_history_kind = "full"
        strm_helper.generate_strm_files(
            full_sync_strm_paths=configer.get_config("full_sync_strm_paths"),
        )
        (
            strm_count,
            mediainfo_count,
            strm_fail_count,
            mediainfo_fail_count,
            remove_unless_strm_count,
            strm_cleanup_deferred_count,
        ) = strm_helper.get_generate_total()
        if configer.get_config("notify"):
            text = f"""
📄 生成STRM文件 {strm_count} 个
⬇️ 下载媒体文件 {mediainfo_count} 个
❌ 生成STRM失败 {strm_fail_count} 个
🚫 下载媒体失败 {mediainfo_fail_count} 个
"""
            if remove_unless_strm_count != 0:
                text += f"🗑️ 清理无效STRM文件 {remove_unless_strm_count} 个"
            if strm_cleanup_deferred_count != 0:
                text += f"\n⏳ 待二次确认清理无效 STRM {strm_cleanup_deferred_count} 个"
            post_message(
                mtype=MessageType.Plugin,
                title=i18n.translate("full_sync_done_title"),
                text=text,
            )

    def start_full_sync(self):
        """
        启动全量同步
        """
        schedule_plugin_one_shot(
            service_id="full_sync_strm",
            name="115网盘助手全量生成STRM",
            func=self.full_sync_strm_files,
        )

    @_track_sync_operation
    def full_sync_database(self) -> None:
        """
        全量同步数据库
        """
        if (
            not configer.get_config("full_sync_strm_paths")
            or not configer.get_config("moviepilot_address")
            or not configer.get_config("user_download_mediaext")
        ):
            return

        strm_helper = FullSyncStrmHelper(
            client=self.client,
            mediainfodownloader=self.mediainfodownloader,
        )
        strm_helper.generate_database(
            full_sync_strm_paths=configer.get_config("full_sync_strm_paths"),
        )

    def start_full_sync_db(self):
        """
        启动全量同步数据库
        """
        schedule_plugin_one_shot(
            service_id="full_sync_database",
            name="115网盘助手全量同步数据库",
            func=self.full_sync_database,
        )

    @_track_sync_operation
    def share_strm_cleanup_run(self) -> None:
        """
        定时任务：分享 STRM 失效清理扫描
        """
        try:
            share_strm_cleaner.run_full_cleanup()
        except Exception as e:
            logger.error(f"【分享STRM清理】定时任务失败: {e}", exc_info=True)

    @_track_sync_operation
    def share_strm_files(self) -> None:
        """
        分享生成STRM
        """
        if not configer.share_strm_config or not configer.moviepilot_address:
            return

        try:
            strm_helper = ShareStrmHelper(mediainfodownloader=self.mediainfodownloader)
            strm_helper.strm_exec_history_kind = "share"
            strm_helper.generate_strm_files()
            strm_count, mediainfo_count, strm_fail_count, mediainfo_fail_count = (
                strm_helper.get_generate_total()
            )
            if configer.get_config("notify"):
                post_message(
                    mtype=MessageType.Plugin,
                    title=i18n.translate("share_sync_done_title"),
                    text=f"\n📄 生成STRM文件 {strm_count} 个\n"
                    + f"⬇️ 下载媒体文件 {mediainfo_count} 个\n"
                    + f"❌ 生成STRM失败 {strm_fail_count} 个\n"
                    + f"🚫 下载媒体失败 {mediainfo_fail_count} 个",
                )
        except Exception as e:
            logger.error(f"【分享STRM生成】运行失败: {e}")
            return

    def start_share_sync(self):
        """
        启动分享同步
        """
        schedule_plugin_one_shot(
            service_id="share_strm",
            name="115网盘助手分享生成STRM",
            func=self.share_strm_files,
        )

    @_track_sync_operation
    def increment_sync_strm_files(self, send_msg: bool = False) -> None:
        """
        增量同步（带并发互斥与优先级控制）
        """
        with self._sync_state_lock:
            if self._full_sync_running:
                logger.info("【增量同步】全量同步正在运行，跳过本次增量同步")
                return
            if self._increment_sync_running:
                logger.info("【增量同步】增量同步已在运行，跳过本次触发")
                return
            self._increment_sync_running = True
        try:
            self._run_increment_sync(send_msg)
        finally:
            run_full = False
            with self._sync_state_lock:
                self._increment_sync_running = False
                if self._full_sync_pending:
                    self._full_sync_pending = False
                    run_full = True
            if run_full:
                logger.info("【增量同步】增量同步完成，执行待运行的全量同步")
                self.full_sync_strm_files()

    def _run_increment_sync(self, send_msg: bool = False):
        """
        增量同步实际执行逻辑
        """
        if (
            not configer.get_config("increment_sync_strm_paths")
            or not configer.get_config("moviepilot_address")
            or not configer.get_config("user_download_mediaext")
        ):
            return

        strm_helper = IncrementSyncStrmHelper(
            client=self.client, mediainfodownloader=self.mediainfodownloader
        )
        strm_helper.strm_exec_history_kind = "increment"
        strm_helper.generate_strm_files(
            sync_strm_paths=configer.get_config("increment_sync_strm_paths"),
        )
        (
            strm_count,
            mediainfo_count,
            strm_fail_count,
            mediainfo_fail_count,
            remove_unless_strm_count,
        ) = strm_helper.get_generate_total()
        if configer.get_config("notify") and (
            send_msg
            or (
                strm_count != 0
                or mediainfo_count != 0
                or strm_fail_count != 0
                or mediainfo_fail_count != 0
                or remove_unless_strm_count != 0
            )
        ):
            text = f"""
📄 生成STRM文件 {strm_count} 个
⬇️ 下载媒体文件 {mediainfo_count} 个
❌ 生成STRM失败 {strm_fail_count} 个
🚫 下载媒体失败 {mediainfo_fail_count} 个
"""
            if remove_unless_strm_count != 0:
                text += f"🗑️ 清理无效STRM文件 {remove_unless_strm_count} 个"
            post_message(
                mtype=MessageType.Plugin,
                title=i18n.translate("inc_sync_done_title"),
                text=text,
            )

    @_track_sync_operation
    def hdhive_checkin_scheduler_tick(self) -> None:
        """
        HDHive 签到调度
        """
        hdhive_checkin_scheduler_tick()

    @_track_sync_operation
    def p115_checkin_scheduler_tick(self) -> None:
        """
        115 签到调度
        """
        p115_scheduler_tick(client=self.client)

    def start_directory_upload(self):
        """
        启动目录上传监控
        """
        if configer.directory_upload_enabled:
            active_mon_paths = [
                item.get("src", "")
                for item in (configer.directory_upload_path or [])
                if item and item.get("src", "")
            ]
            directory_upload_queue.start()
            directory_upload_stability_tracker.start(self.client, active_mon_paths)
            directory_upload_rescan.start(self.client, active_mon_paths)
            for item in configer.directory_upload_path or []:
                if not item:
                    continue
                mon_path = item.get("src", "")
                if not mon_path:
                    continue
                try:
                    stop_event = ThreadEvent()
                    force_polling = configer.directory_upload_mode == "compatibility"

                    def watch_worker(path: str, stop_evt: ThreadEvent, polling: bool):
                        """
                        目录监控工作线程，监听文件新增事件并加入上传队列

                        :param path: 要监控的目录路径
                        :param stop_evt: 停止事件
                        :param polling: 是否使用轮询模式（兼容模式）
                        """
                        try:
                            for changes in watch(
                                path,
                                recursive=True,
                                force_polling=polling,
                                stop_event=stop_evt,
                                debounce=1600,
                                step=50,
                            ):
                                for change in changes:
                                    change_type, path_str = change
                                    if change_type == Change.added:
                                        directory_upload_queue.enqueue(
                                            DirectoryUploadTask(
                                                servicer.client,
                                                path_str,
                                                path,
                                            )
                                        )
                        except Exception as e:
                            logger.error(
                                f"【目录上传】{path} 监控线程异常: {e}",
                                exc_info=True,
                            )

                    watch_thread = Thread(
                        target=watch_worker,
                        args=(mon_path, stop_event, force_polling),
                        name=f"P115StrmHelper-DirectoryUpload-{mon_path}",
                        daemon=True,
                    )
                    watch_thread.start()

                    self.service_observer.append(
                        ObserverInfo(
                            thread=watch_thread,
                            stop_event=stop_event,
                            mon_path=mon_path,
                        )
                    )
                    logger.info(f"【目录上传】{mon_path} 实时监控服务启动")
                except Exception as e:
                    logger.error(f"【目录上传】{mon_path} 启动实时监控失败：{e}")

    @_track_sync_operation
    def main_cleaner(self) -> None:
        """
        主清理模块
        """
        client = Cleaner(client=self.client)

        if configer.get_config("clear_receive_path_enabled"):
            client.clear_receive_path()

        if configer.get_config("clear_recyclebin_enabled"):
            client.clear_recyclebin()

    @_track_sync_operation
    def offline_status(self) -> None:
        """
        监控 115 网盘离线下载进度
        """
        if self.offlinehelper:
            self.offlinehelper.pull_status_to_task()

    def start_fuse(self, mountpoint: Optional[str] = None, readdir_ttl: float = 60):
        """
        启动 FUSE 文件系统

        :param mountpoint: 挂载点路径，如果为 None 则使用配置中的路径
        :param readdir_ttl: 目录读取缓存 TTL（秒）
        :return: 是否启动成功
        """
        if not self.fuse_manager:
            logger.error("【FUSE】FuseManager 未初始化")
            return False
        return self.fuse_manager.start_fuse(mountpoint, readdir_ttl)

    def stop_fuse(self) -> bool:
        """
        停止 FUSE 文件系统

        :return bool: FUSE 工作线程已退出或尚未初始化时返回 True
        """
        if self.fuse_manager:
            return self.fuse_manager.stop_fuse()
        return True

    @contextmanager
    def sync_operation(self) -> Iterator[None]:
        """
        在同步调用访问实例配置和资源前登记关停归属

        :yields None: 当前调用持有的在途执行范围
        """
        worker = current_thread()
        with self._sync_condition:
            if self._sync_stopping and worker not in self._sync_operations:
                raise RuntimeError("同步服务已停止，暂不接收新任务")
            self._sync_operations[worker] = self._sync_operations.get(worker, 0) + 1
        try:
            yield
        finally:
            with self._sync_condition:
                self._sync_operations[worker] -= 1
                if not self._sync_operations[worker]:
                    del self._sync_operations[worker]
                self._sync_condition.notify_all()

    def start_background_sync(self, func: Callable[[], None], name: str) -> None:
        """
        在线程启动前登记后台工作，使已受理请求能够在关停期间交接任务

        :param func (Callable): 原后台任务
        :param name (str): 原线程名称
        """

        def run() -> None:
            try:
                func()
            finally:
                with self._sync_condition:
                    del self._sync_operations[current_thread()]
                    self._sync_condition.notify_all()

        worker = Thread(target=run, daemon=True, name=name)
        with self._sync_condition:
            if self._sync_stopping and current_thread() not in self._sync_operations:
                raise RuntimeError("同步服务已停止，暂不接收新任务")
            self._sync_operations[worker] = 1
            try:
                worker.start()
            except Exception:
                del self._sync_operations[worker]
                self._sync_condition.notify_all()
                raise

    def _stop_sync_operations(self, timeout: float = 25.0) -> bool:
        """
        关闭同步准入并等待已开始的调用，超时保留实例资源供宿主重试
        """
        deadline = monotonic() + max(timeout, 0)
        with self._sync_condition:
            self._sync_stopping = True
            if current_thread() in self._sync_operations:
                return False
            while self._sync_operations:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._sync_condition.wait(remaining)
            return True

    def stop(self) -> bool:
        """
        停止服务并报告已知的关停失败

        :return bool: 已检查的停止步骤成功返回 True，显式失败或异常时返回 False
        """
        all_stopped = True
        try:
            if not self._stop_sync_operations():
                logger.warning("【同步服务】全量、增量、数据库或分享任务尚未退出")
                return False
            if self.backup_service.stop() is False:
                logger.warning("【STRM备份】备份或恢复任务尚未结束")
                return False
            remaining_observers = []
            for observer in self.service_observer:
                try:
                    observer.stop_event.set()
                    if observer.thread.is_alive():
                        observer.thread.join(timeout=5)
                    if observer.thread.is_alive():
                        remaining_observers.append(observer)
                        logger.warning(
                            f"【目录上传】{observer.mon_path} 监控线程尚未退出"
                        )
                    else:
                        logger.debug(f"【目录上传】{observer.mon_path} 监控线程已关闭")
                except Exception as e:
                    remaining_observers.append(observer)
                    logger.error(f"【目录上传】关闭失败: {e}", exc_info=True)
            self.service_observer = remaining_observers
            if remaining_observers:
                all_stopped = False
            for name, component in (
                ("目录上传稳定性跟踪", directory_upload_stability_tracker),
                ("目录上传", directory_upload_queue),
                ("目录上传漏传巡检", directory_upload_rescan),
            ):
                try:
                    if component.stop() is False:
                        all_stopped = False
                except Exception as e:
                    all_stopped = False
                    logger.error(f"【{name}】停止失败: {e}", exc_info=True)
            with self.monitor_life_lock:
                if self.monitor_life_thread:
                    if self._stop_monitor_life_internal() is False:
                        return False
                elif self.monitor_stop_event:
                    self.monitor_stop_event.set()
                    self.monitor_stop_event = None
            if self.monitorlife and self.monitorlife.stop() is False:
                logger.warning("【监控生活事件】手动整理或延迟通知尚未退出")
                return False
            if self.share_interactive_gen_strm_queue.stop() is False:
                logger.warning("【分享交互生成STRM】任务尚未退出")
                return False
            if self.sharetransferhelper and self.sharetransferhelper.stop() is False:
                logger.warning("【分享转存】后台队列或直接转存调用尚未退出")
                return False
            if self.fuse_manager and self.fuse_manager.stop_fuse() is False:
                all_stopped = False
            if self.redirect and self.redirect.close_http_client_sync() is False:
                all_stopped = False
            for name, component in (
                ("Emby 媒体信息队列", emby_mediainfo_queue),
                ("同步删除 Webhook 队列", sync_del_webhook_queue),
                ("分享审核下载", share_audit_download_queue),
            ):
                try:
                    if component.stop() is False:
                        all_stopped = False
                except Exception as e:
                    all_stopped = False
                    logger.error(f"【{name}】停止失败: {e}", exc_info=True)
            if not all_stopped:
                return False
            if self.transfer_task_manager:
                if self.transfer_task_manager.shutdown() is False:
                    return False
                self.transfer_task_manager = None
            TransferChainPatcher.disable()
            self.transfer_handler = None
            return True
        except Exception as e:
            logger.error(f"停止服务失败: {e}", exc_info=True)
            return False


servicer = ServiceHelper()
