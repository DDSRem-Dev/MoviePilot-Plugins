from logging import ERROR
from time import time
from threading import Lock, Thread, Event as ThreadEvent
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from p115client import P115Client
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from aligo.core import set_config_folder

from ..core.i18n import i18n
from ..core.p115 import get_pid_by_path
from ..helper.mediainfo_download import MediaInfoDownloader
from ..helper.life import MonitorLife
from ..service.life import monitor_life_thread_worker
from ..service.fuse import FuseManager
from ..helper.strm import FullSyncStrmHelper, ShareStrmHelper, IncrementSyncStrmHelper
from ..helper.monitor import handle_file, FileMonitorHandler
from ..helper.offline import OfflineDownloadHelper
from ..helper.share import ShareTransferHelper
from ..helper.clean import Cleaner
from ..helper.r302 import Redirect
from ..helper.transfer import TransferTaskManager, TransferHandler
from ..helper.webdav import WebdavCore
from ..patch import TransferChainPatcher
from ..core.config import configer
from ..core.message import post_message
from ..core.aliyunpan import BAligo
from ..utils.sentry import sentry_manager

from app.log import logger
from app.core.config import settings
from app.schemas import NotificationType
from app.scheduler import Scheduler


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

        self.scheduler: Optional[BackgroundScheduler] = None

        self.service_observer: List = []

        self.fuse_manager: Optional[FuseManager] = None

        self.transfer_task_manager: Optional[TransferTaskManager] = None
        self.transfer_handler: Optional[TransferHandler] = None

        self.webdav_core: Optional[WebdavCore] = None

    def init_service(self):
        """
        初始化服务
        """
        try:
            # 115 网盘客户端初始化
            self.client = P115Client(configer.cookies)

            # 阿里云盘登入
            aligo_config = configer.get_config("PLUGIN_ALIGO_PATH")
            if configer.get_config("aliyundrive_token"):
                set_config_folder(aligo_config)
                if Path(aligo_config / "aligo.json").exists():
                    logger.debug("Config login aliyunpan")
                    self.aligo = BAligo(level=ERROR, re_login=False)
                else:
                    logger.debug("Refresh token login aliyunpan")
                    self.aligo = BAligo(
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

            # 媒体信息下载工具初始化
            self.mediainfodownloader = MediaInfoDownloader(
                cookie=configer.get_config("cookies")
            )

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
                self.fuse_manager._start_fuse_internal()

            # 初始化整理任务管理器和 TransferChain 补丁
            self._init_transfer_enhancement()

            # 初始化 Webdav 服务
            self.webdav_core = WebdavCore(client=self.client)
            return True
        except Exception as e:
            logger.error(f"服务项初始化失败: {e}")
            return False

    def _init_transfer_enhancement(self):
        """
        初始化或更新接管网盘整理功能
        """
        try:
            TransferChainPatcher.disable()
        except Exception:
            pass

        if self.transfer_task_manager:
            try:
                self.transfer_task_manager.shutdown()
            except Exception:
                pass
            self.transfer_task_manager = None
        self.transfer_handler = None

        if configer.pan_transfer_takeover:
            if configer.storage_module != "115网盘Plus":
                logger.warn(
                    "【整理接管】接管网盘整理功能需要存储模块为 '115网盘Plus'，当前存储模块为 "
                    f"'{configer.storage_module}'，接管功能已禁用"
                )
            else:
                try:
                    self.transfer_handler = TransferHandler(
                        client=self.client,
                        storage_name="115网盘Plus",
                    )
                    self.transfer_task_manager = TransferTaskManager(
                        batch_delay=10.0,
                        batch_max_size=500,
                        batch_callback=self.transfer_handler.process_batch,
                    )
                    TransferChainPatcher.enable(
                        task_manager=self.transfer_task_manager,
                        handler=self.transfer_handler,
                        storage_module="115网盘Plus",
                    )
                    logger.info("【整理接管】已启用")
                except Exception as e:
                    logger.error(f"【整理接管】初始化失败: {e}", exc_info=True)
                    self.transfer_task_manager = None
                    self.transfer_handler = None

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
                                    mtype=NotificationType.Plugin,
                                    title="【监控生活事件】自动重启",
                                    text="\n生活事件监控线程已停止超过5分钟\n"
                                    "守护线程正在自动重启监控服务\n",
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
            self._start_monitor_life_internal()

    def _stop_monitor_life_internal(self):
        """
        停止生活事件监控线程
        """
        if self.monitor_life_thread and self.monitor_life_thread.is_alive():
            logger.info("【监控生活事件】停止生活事件监控线程")
            if self.monitor_stop_event:
                self.monitor_stop_event.set()

            self.monitor_life_thread.join(timeout=25)
            if self.monitor_life_thread.is_alive():
                logger.warning("【监控生活事件】线程未在预期时间内结束")
            else:
                logger.info("【监控生活事件】线程已正常退出")

            self.monitor_life_thread = None
            if self.monitor_stop_event:
                self.monitor_stop_event = None

    def _start_monitor_life_internal(self):
        """
        启动生活事件监控线程
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

            try:
                self._update_monitor_life_guard_service()
            except Exception as e:
                logger.debug(f"【监控生活事件】重新注册守护服务失败: {e}")
        else:
            self._stop_monitor_life_internal()

    def _update_monitor_life_guard_service(self):
        """
        只重新注册115生活事件线程守护服务
        """
        pid = "P115StrmHelper"
        service_id = "P115StrmHelper_monitor_life_guard"
        job_id = f"{pid}_{service_id}"

        should_register = (
            configer.monitor_life_enabled
            and configer.monitor_life_paths
            and configer.monitor_life_event_modes
        ) or (configer.pan_transfer_enabled and configer.pan_transfer_paths)

        if not should_register:
            logger.debug("【监控生活事件】守护服务未启用，跳过注册")
            return

        guard_service = {
            "id": service_id,
            "name": "115生活事件线程守护",
            "trigger": CronTrigger.from_crontab("* * * * *"),
            "func": self.check_monitor_life_guard,
            "kwargs": {},
        }

        scheduler = Scheduler()
        scheduler.remove_plugin_job(pid, job_id)

        with scheduler._lock:
            try:
                sid = f"{pid}_{service_id}"
                scheduler._jobs[job_id] = {
                    "func": guard_service["func"],
                    "name": guard_service["name"],
                    "pid": pid,
                    "provider_name": "115网盘STRM助手",
                    "kwargs": guard_service.get("func_kwargs") or {},
                    "running": False,
                }
                scheduler._scheduler.add_job(
                    scheduler.start,
                    guard_service["trigger"],
                    id=sid,
                    name=guard_service["name"],
                    **(guard_service.get("kwargs") or {}),
                    kwargs={"job_id": job_id},
                    replace_existing=True,
                )
                logger.debug("【监控生活事件】已重新注册115生活事件线程守护服务")
            except Exception as e:
                logger.error(f"【监控生活事件】注册守护服务失败: {str(e)}")

    def full_sync_strm_files(self):
        """
        全量同步
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
        strm_helper.generate_strm_files(
            full_sync_strm_paths=configer.get_config("full_sync_strm_paths"),
        )
        (
            strm_count,
            mediainfo_count,
            strm_fail_count,
            mediainfo_fail_count,
            remove_unless_strm_count,
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
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("full_sync_done_title"),
                text=text,
            )

    def start_full_sync(self):
        """
        启动全量同步
        """
        self.scheduler = BackgroundScheduler(timezone=settings.TZ)
        self.scheduler.add_job(
            func=self.full_sync_strm_files,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name="115网盘助手全量生成STRM",
        )
        if self.scheduler.get_jobs():
            self.scheduler.print_jobs()
            self.scheduler.start()

    def full_sync_database(self):
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
        self.scheduler = BackgroundScheduler(timezone=settings.TZ)
        self.scheduler.add_job(
            func=self.full_sync_database,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name="115网盘助手全量同步数据库",
        )
        if self.scheduler.get_jobs():
            self.scheduler.print_jobs()
            self.scheduler.start()

    def share_strm_files(self):
        """
        分享生成STRM
        """
        if not configer.share_strm_config or not configer.moviepilot_address:
            return

        try:
            strm_helper = ShareStrmHelper(
                client=self.client, mediainfodownloader=self.mediainfodownloader
            )
            strm_helper.generate_strm_files()
            strm_count, mediainfo_count, strm_fail_count, mediainfo_fail_count = (
                strm_helper.get_generate_total()
            )
            if configer.get_config("notify"):
                post_message(
                    mtype=NotificationType.Plugin,
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
        self.scheduler = BackgroundScheduler(timezone=settings.TZ)
        self.scheduler.add_job(
            func=self.share_strm_files,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name="115网盘助手分享生成STRM",
        )
        if self.scheduler.get_jobs():
            self.scheduler.print_jobs()
            self.scheduler.start()

    def increment_sync_strm_files(self, send_msg: bool = False):
        """
        增量同步
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
        strm_helper.generate_strm_files(
            sync_strm_paths=configer.get_config("increment_sync_strm_paths"),
        )
        (
            strm_count,
            mediainfo_count,
            strm_fail_count,
            mediainfo_fail_count,
        ) = strm_helper.get_generate_total()
        if configer.get_config("notify") and (
            send_msg
            or (
                strm_count != 0
                or mediainfo_count != 0
                or strm_fail_count != 0
                or mediainfo_fail_count != 0
            )
        ):
            text = f"""
📄 生成STRM文件 {strm_count} 个
⬇️ 下载媒体文件 {mediainfo_count} 个
❌ 生成STRM失败 {strm_fail_count} 个
🚫 下载媒体失败 {mediainfo_fail_count} 个
"""
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("inc_sync_done_title"),
                text=text,
            )

    @staticmethod
    def event_handler(event, mon_path: str, text: str, event_path: str):
        """
        处理文件变化
        :param event: 事件
        :param mon_path: 监控目录
        :param text: 事件描述
        :param event_path: 事件文件路径
        """
        if not event.is_directory:
            # 文件发生变化
            logger.debug(f"【目录上传】文件 {text}: {event_path}")
            handle_file(event_path=event_path, mon_path=mon_path)

    def start_directory_upload(self):
        """
        启动目录上传监控
        """
        if configer.get_config("directory_upload_enabled"):
            for item in configer.get_config("directory_upload_path"):  # pylint: disable=E1133
                if not item:
                    continue
                mon_path = item.get("src", "")
                if not mon_path:
                    continue
                try:
                    if configer.get_config("directory_upload_mode") == "compatibility":
                        # 兼容模式，目录同步性能降低且NAS不能休眠，但可以兼容挂载的远程共享目录如SMB
                        observer = PollingObserver(timeout=10)
                    else:
                        # 内部处理系统操作类型选择最优解
                        observer = Observer(timeout=10)
                    self.service_observer.append(observer)
                    observer.schedule(
                        FileMonitorHandler(mon_path, self),
                        path=mon_path,
                        recursive=True,
                    )
                    observer.daemon = True
                    observer.start()
                    logger.info(f"【目录上传】{mon_path} 实时监控服务启动")
                except Exception as e:
                    err_msg = str(e)
                    if "inotify" in err_msg and "reached" in err_msg:
                        logger.warn(
                            f"【目录上传】监控服务启动出现异常：{err_msg}，请在宿主机上（不是docker容器内）执行以下命令并重启："
                            + """
                                echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
                                echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
                                sudo sysctl -p
                                """
                        )
                    else:
                        logger.error(
                            f"【目录上传】{mon_path} 启动实时监控失败：{err_msg}"
                        )

    def main_cleaner(self):
        """
        主清理模块
        """
        client = Cleaner(client=self.client)

        if configer.get_config("clear_receive_path_enabled"):
            client.clear_receive_path()

        if configer.get_config("clear_recyclebin_enabled"):
            client.clear_recyclebin()

    def offline_status(self):
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

    def stop_fuse(self):
        """
        停止 FUSE 文件系统
        """
        if self.fuse_manager:
            self.fuse_manager.stop_fuse()

    def stop(self):
        """
        停止所有服务
        """
        try:
            if self.service_observer:
                for observer in self.service_observer:
                    try:
                        observer.stop()
                        observer.join()
                        logger.debug(f"【目录上传】{observer} 关闭")
                    except Exception as e:
                        logger.error(f"【目录上传】关闭失败: {e}")
                logger.info("【目录上传】目录监控已关闭")
            self.service_observer = []
            if self.scheduler:
                self.scheduler.remove_all_jobs()
                if self.scheduler.running:
                    self.scheduler.shutdown()
                self.scheduler = None
            with self.monitor_life_lock:
                if self.monitor_life_thread:
                    self._stop_monitor_life_internal()
                elif self.monitor_stop_event:
                    self.monitor_stop_event.set()
                    self.monitor_stop_event = None
            if self.fuse_manager:
                self.fuse_manager.stop_fuse()
            if self.redirect:
                self.redirect.close_http_client_sync()
            try:
                TransferChainPatcher.disable()
            except Exception as e:
                logger.error(f"【整理接管】禁用补丁失败: {e}")
            if self.transfer_task_manager:
                try:
                    self.transfer_task_manager.shutdown()
                except Exception as e:
                    logger.error(f"【整理接管】关闭任务管理器失败: {e}")
                self.transfer_task_manager = None
            self.transfer_handler = None
        except Exception as e:
            logger.error(f"发生错误: {e}")


servicer = ServiceHelper()
