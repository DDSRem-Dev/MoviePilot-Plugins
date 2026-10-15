from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Event
from time import monotonic, sleep
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import quote

from app.schemas import ServiceInfo
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.services import MediaServerHelper
from httpx import RequestError
from httpx import post as httpx_post
from p115center import P115Center

from ...core.config import configer
from ...core.worker_queue import WorkerQueue
from ...schemas.emby_mediainfo import EmbyMediainfoTask
from ...utils.path import PathUtils
from ...utils.sentry import sentry_manager
from .scan import library_scan


@sentry_manager.capture_all_class_exceptions
class EmbyOperate:
    """
    Emby 媒体服务器操作类
    """

    def __init__(self, func_name: str) -> None:
        """
        初始化 Emby 服务访问器

        :param func_name (str): 调用方日志标识
        """
        self.func_name = func_name
        self.mediaserver_helper = MediaServerHelper()

    def get_emby_info(self, name: str) -> Tuple[str, str, str]:
        """
        获取 Emby 服务器信息

        :param name (str): Emby Server Name

        :return Tuple: Emby 服务器信息
        """
        emby_server = self.mediaserver_helper.get_service(name=name, type_filter="emby")
        if not emby_server:
            logger.warning(f"{self.func_name}未找到 Emby 服务: {name}")
            return "", "", ""
        emby_user = emby_server.instance.get_user()
        emby_apikey = emby_server.config.config.get("apikey")
        emby_host = emby_server.config.config.get("host")
        if not emby_host or not emby_apikey:
            return "", "", ""
        if not emby_host.endswith("/"):
            emby_host += "/"
        if not emby_host.startswith("http"):
            emby_host = "http://" + emby_host  # noqa
        return emby_host, emby_user, emby_apikey

    def get_series_tmdb_id(self, name: str, series_id: str) -> Optional[str]:
        """
        获取剧集 TMDB ID

        :param name (str): Emby Server Name
        :param series_id (str): 剧集ID

        :return str: TMDB ID
        """
        emby_host, emby_user, emby_apikey = self.get_emby_info(name)
        if not emby_host:
            return None

        req_url = (
            f"{emby_host}emby/Users/{emby_user}/Items/{series_id}?api_key={emby_apikey}"
        )
        try:
            with RequestUtils().get_res(req_url) as res:
                if res:
                    return res.json().get("ProviderIds", {}).get("Tmdb")
                else:
                    logger.warning(
                        f"{self.func_name}获取剧集 TMDB ID 失败，Emby 未返回有效响应 name={name!r} series_id={series_id!r}"
                    )
                    return None
        except Exception as e:
            logger.error(
                f"{self.func_name}获取剧集 TMDB ID 异常 name={name!r} series_id={series_id!r}: {e}",
            )
            return None

    def get_item_id_by_path(
        self, name: str, path: str, log_warning: bool = True
    ) -> Optional[str]:
        """
        依据路径获取 Emby 项目 ID

        :param name (str): Emby Server Name
        :param path (str): 项目路径
        :param log_warning (bool): 是否输出 warn 日志，当在遍历父目录等场景下可设为 False

        :return str: 项目 ID
        """
        emby_host, _, emby_apikey = self.get_emby_info(name)
        if not emby_host:
            return None

        req_url = f"{emby_host}emby/Items"
        params = {
            "Path": path,
            "Recursive": "true",
            "Fields": "Path",
            "IncludeItemTypes": "Movie,Episode,Folder,Series",
            "api_key": emby_apikey,
        }
        try:
            with RequestUtils().get_res(url=req_url, params=params) as res:
                if res:
                    items = res.json().get("Items", [])
                    for item in items:
                        if item.get("Path") == path:
                            return item.get("Id")
                    if log_warning:
                        logger.warning(
                            f"{self.func_name}无法获取项目 Id，未匹配到路径 name={name!r} path={path!r}"
                        )
                    else:
                        logger.debug(
                            f"{self.func_name}未匹配到路径 name={name!r} path={path!r}"
                        )
                else:
                    logger.warning(
                        f"{self.func_name}获取项目 Id 失败，Emby 未返回有效响应 name={name!r} path={path!r}"
                    )
            return None
        except Exception as e:
            logger.error(
                f"{self.func_name}获取项目 Id 异常 name={name!r} path={path!r}: {e}",
            )
            return None

    def notify_media_updated(self, name: str, path: str) -> bool:
        """
        通知 Emby 发现新增文件，不刷新父目录元数据

        不支持文件变更通知接口时回退普通媒体库扫描
        返回成功仅表示请求已提交，不代表文件已经入库

        :param name (str): Emby 服务器名称
        :param path (str): Emby 可见的文件绝对路径

        :return bool: 是否成功提交发现请求
        """
        if not path or not (
            PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
        ):
            logger.warning(
                f"{self.func_name}无法提交文件发现请求，路径不是绝对路径: {path!r}"
            )
            return False
        try:
            emby_host, _, emby_apikey = self.get_emby_info(name)
            if not emby_host:
                return False
            response = RequestUtils().post_res(
                url=f"{emby_host}emby/Library/Media/Updated",
                params={"api_key": emby_apikey},
                json={"Updates": [{"Path": path, "UpdateType": "Created"}]},
            )
            if response is None:
                logger.warning(f"{self.func_name}{name} 文件发现请求未获得响应: {path}")
                return False
            with response as res:
                status_code = res.status_code
            if status_code in {200, 202, 204}:
                logger.info(f"{self.func_name}{name} 文件发现请求已提交: {path}")
                return True
            if status_code not in {404, 405, 501}:
                logger.warning(
                    f"{self.func_name}{name} 文件发现请求失败: [{status_code}] {path}"
                )
                return False
            service = self.mediaserver_helper.get_service(name=name, type_filter="emby")
            if not service or not hasattr(service.instance, "refresh_root_library"):
                logger.warning(f"{self.func_name}{name} 不支持普通媒体库扫描")
                return False
            success = library_scan.submit(
                (name, emby_host, emby_apikey), service.instance.refresh_root_library
            )
            if success:
                logger.info(f"{self.func_name}{name} 普通媒体库扫描请求已提交: {path}")
            else:
                logger.warning(f"{self.func_name}{name} 普通媒体库扫描请求失败: {path}")
            return success
        except Exception:
            logger.error(
                f"{self.func_name}{name} 提交文件发现请求异常: {path}", exc_info=True
            )
            return False

    def trigger_mediainfo_refresh(self, name: str, item_id: str) -> bool:
        """
        触发 Emby 提取媒体信息

        :param name (str): Emby Server Name
        :param item_id (str): ID

        :return bool: 是否触发成功
        """
        emby_host, emby_user, emby_apikey = self.get_emby_info(name)
        if not emby_host:
            return False

        req_url = f"{emby_host}emby/Items/{item_id}/PlaybackInfo"
        params = {
            "AutoOpenLiveStream": "true",
            "IsPlayback": "true",
            "api_key": emby_apikey,
            "UserId": emby_user,
        }
        try:
            response = RequestUtils(timeout=120).post_res(url=req_url, params=params)
            if response is None:
                logger.warning(
                    f"{self.func_name}触发提取媒体信息失败，请求超时或连接失败 "
                    f"name={name!r} item_id={item_id!r}"
                )
                return False
            with response as res:
                if res.status_code == 200:
                    return True
                else:
                    logger.warning(
                        f"{self.func_name}触发提取媒体信息失败，"
                        f"Emby 未返回有效响应 code={res.status_code!r} "
                        f"name={name!r} item_id={item_id!r}"
                    )
                    return False
        except Exception as e:
            logger.error(
                f"{self.func_name}触发提取媒体信息异常 name={name!r} item_id={item_id!r}: {e}",
            )
            return False


@sentry_manager.capture_all_class_exceptions
class EmbyMediaInfoOperate:
    """
    Emby 媒体信息操作类
    """

    def __init__(
        self,
        func_name: str,
        mediaservers: Optional[List[str]] = None,
        mp_mediaserver: Optional[str] = None,
        stop_event: Optional[Event] = None,
    ) -> None:
        """
        初始化媒体信息提取及可中断的入库等待

        :param func_name (str): 调用方日志标识
        :param mediaservers (List): 媒体服务器名称
        :param mp_mediaserver (str): 媒体服务器路径映射
        :param stop_event (Event): 停止入库等待的信号
        """
        self._stop_event = stop_event if stop_event is not None else Event()
        self.func_name = func_name
        self.media_servers = mediaservers
        self.mp_mediaserver = mp_mediaserver
        self.center = P115Center(
            license=configer.p115center_license,
            file_path=str(Path(__file__).resolve().parent.parent.parent / "api.py"),
        )
        self.emby_operate = EmbyOperate(func_name)

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        媒体服务器服务信息

        :return Dict: 媒体服务器服务信息
        """
        if not self.media_servers:
            logger.warning(f"{self.func_name}尚未配置媒体服务器，请检查配置")
            return None

        mediaserver_helper = MediaServerHelper()

        services = mediaserver_helper.get_services(name_filters=self.media_servers)
        if not services:
            logger.warning(f"{self.func_name}获取媒体服务器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(
                    f"{self.func_name}媒体服务器 {service_name} 未连接，请检查配置"
                )
            else:
                if service_info.type == "emby":
                    active_services[service_name] = service_info

        if not active_services:
            logger.warning(f"{self.func_name}没有已连接的 Emby 媒体服务器，请检查配置")
            return None

        return active_services

    def _sync_media_info(
        self,
        host: str,
        api_key: str,
        media_data: Optional[Dict],
        service_name: str,
        need_upload: bool,
        file_path: Optional[str] = None,
        item_id: Optional[str] = None,
    ) -> Tuple[bool, bool, Optional[Dict]]:
        if file_path:
            path_encoded = quote(file_path, safe="")
            url = (
                f"{host}emby/Items/SyncMediaInfo?Path={path_encoded}&api_key={api_key}"
            )
        elif item_id:
            url = f"{host}emby/Items/SyncMediaInfo?Id={item_id}&api_key={api_key}"
        else:
            return False, need_upload, media_data
        try:
            res = httpx_post(
                url,
                json=media_data,
                headers={"Content-Type": "application/json"},
                timeout=60.0,
            )
            try:
                res_data = res.json()
            except Exception:
                res_data = []
            if res.status_code == 200 and res_data:
                logger.info(
                    f"{self.func_name}{service_name} 更新媒体信息成功: {file_path if file_path else item_id}"
                )
                if need_upload:
                    media_data = res_data
                elif media_data != res_data:
                    logger.warning(
                        f"{self.func_name}{service_name} 媒体信息不一致，重新上传服务器: {file_path if file_path else item_id}"
                    )
                    need_upload = True
                    media_data = res_data
                return True, need_upload, media_data
            else:
                logger.warning(
                    f"{self.func_name}{service_name} 更新媒体信息失败: [{res.status_code}] {res_data}"
                )
        except RequestError as e:
            logger.error(f"{self.func_name}{service_name} 更新媒体信息失败: {e}")
        return False, need_upload, media_data

    def _get_or_discover_item_id(
        self, service_name: str, file_path: str
    ) -> Optional[str]:
        if self._stop_event.is_set():
            return None
        item_id = self.emby_operate.get_item_id_by_path(
            service_name, file_path, log_warning=False
        )
        if item_id or self._stop_event.is_set():
            return item_id
        if not self.emby_operate.notify_media_updated(service_name, file_path):
            return None
        deadline = monotonic() + 60
        while not self._stop_event.wait(min(5, max(0, deadline - monotonic()))):
            item_id = self.emby_operate.get_item_id_by_path(
                service_name, file_path, log_warning=False
            )
            if item_id:
                return item_id
            if monotonic() >= deadline:
                logger.warning(
                    f"{self.func_name}{service_name} 文件发现请求已提交，但等待入库超时: {file_path}"
                )
                return None
        return None

    def get_mediainfo_native(self, path: Path) -> None:
        """
        执行原生 Emby 提取媒体信息

        :param path (Path): 媒体路径
        """
        media_server = self.service_infos
        if not media_server:
            return

        file_path = path.as_posix()
        if self.mp_mediaserver:
            status, mediaserver_path, moviepilot_path = PathUtils.get_media_path(
                self.mp_mediaserver,
                path.as_posix(),
            )
            if not status:
                logger.error(
                    f"{self.func_name}{path} 无法确定媒体库路径，无法媒体信息提取"
                )
                return
            logger.info(f"{self.func_name}{path.name} 提取媒体信息目录替换中...")
            file_path = path.as_posix().replace(moviepilot_path, mediaserver_path, 1)
            logger.info(
                f"{self.func_name}提取媒体信息目录替换: {moviepilot_path} --> {mediaserver_path}"
            )
            logger.info(f"{self.func_name}提取媒体信息目录: {file_path}")

        for service_name, _ in media_server.items():
            item_id = self._get_or_discover_item_id(service_name, file_path)
            if self._stop_event.is_set():
                return
            if not item_id:
                logger.error(
                    f"{self.func_name}无法获取媒体 Id 提取媒体信息: {file_path}"
                )
            else:
                status = self.emby_operate.trigger_mediainfo_refresh(
                    service_name, item_id
                )
                if not status:
                    logger.error(
                        f"{self.func_name}使用媒体 Id 原生提取媒体信息失败: [{item_id}] {file_path}"
                    )

    def get_mediainfo(self, sha1: str, path: Path, size: Optional[int] = None):
        """
        执行提取媒体信息，并上传服务器

        :param sha1 (str): 媒体文件的 sha1 值
        :param path (Path): 媒体路径
        :param size (int): 可选，当前文件大小（字节）
        """
        media_server = self.service_infos
        if not media_server:
            return

        media_data = None
        try:
            resp = self.center.download_emby_mediainfo_data([(sha1, size)])
            media_data = resp.get(sha1.upper(), None)
        except Exception as e:
            logger.error(f"{self.func_name}{path} 获取媒体信息失败: {e}")

        need_upload = True
        if media_data:
            need_upload = False

        file_path = path.as_posix()
        if self.mp_mediaserver:
            status, mediaserver_path, moviepilot_path = PathUtils.get_media_path(
                self.mp_mediaserver,
                path.as_posix(),
            )
            if not status:
                logger.error(
                    f"{self.func_name}{path} 无法确定媒体库路径，无法媒体信息提取"
                )
                return
            logger.info(f"{self.func_name}{path.name} 提取媒体信息目录替换中...")
            file_path = path.as_posix().replace(moviepilot_path, mediaserver_path, 1)
            logger.info(
                f"{self.func_name}提取媒体信息目录替换: {moviepilot_path} --> {mediaserver_path}"
            )
            logger.info(f"{self.func_name}提取媒体信息目录: {file_path}")

        for service_name, service_info in media_server.items():
            host = service_info.config.config.get("host")
            api_key = service_info.config.config.get("apikey")
            if not host:
                continue
            if not host.endswith("/"):
                host += "/"
            if not host.startswith("http"):
                host = "http://" + host  # noqa
            status, need_upload, media_data = self._sync_media_info(
                host=host,
                api_key=api_key,
                media_data=media_data,
                service_name=service_name,
                need_upload=need_upload,
                file_path=file_path,
            )
            if not status:
                logger.info(
                    f"{self.func_name}尝试获取媒体 Id 提取媒体信息: {file_path}"
                )
                item_id = self._get_or_discover_item_id(service_name, file_path)
                if self._stop_event.is_set():
                    return
                if not item_id:
                    logger.error(
                        f"{self.func_name}无法获取媒体 Id 提取媒体信息: {file_path}"
                    )
                else:
                    status, need_upload, media_data = self._sync_media_info(
                        host=host,
                        api_key=api_key,
                        media_data=media_data,
                        service_name=service_name,
                        need_upload=need_upload,
                        item_id=item_id,
                    )
                    if not status:
                        logger.error(
                            f"{self.func_name}使用媒体 Id 提取媒体信息失败: [{item_id}] {file_path}"
                        )
        if need_upload and media_data:
            try:
                if self.center.upload_emby_mediainfo_data(sha1, media_data, size=size):
                    logger.info(
                        f"{self.func_name}上传媒体信息成功: [{sha1}]{file_path}"
                    )
                else:
                    logger.error(
                        f"{self.func_name}Emby 返回媒体信息异常，不进行上传: [{sha1}]{file_path}"
                    )
            except Exception as e:
                logger.warning(
                    f"{self.func_name}上传媒体信息失败: {sha1} {file_path} {e}"
                )


@sentry_manager.capture_all_class_exceptions
class EmbyMediainfoQueue(WorkerQueue):
    """
    Emby 媒体信息提取全局队列
    """

    _TASK_SLEEP_AFTER_SEC: float = 4.0

    def __init__(self) -> None:
        super().__init__("P115StrmHelper-EmbyMediainfoQueue", "Emby 媒体信息队列")
        self._discovery_stop = Event()

    def _start_locked(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._discovery_stop.clear()
        super()._start_locked()

    def _request_stop_locked(self) -> None:
        self._discovery_stop.set()
        super()._request_stop_locked()

    def _worker(self) -> None:
        """
        队列 worker
        """
        q = self._queue
        if q is None:
            return
        while True:
            try:
                task = q.get()
            except Exception as e:
                logger.error(
                    f"【Emby 媒体信息队列】worker 取任务异常: {e}", exc_info=True
                )
                continue
            if task is self._SENTINEL:
                q.task_done()
                break
            try:
                path = task.path if isinstance(task.path, Path) else Path(task.path)
                helper = EmbyMediaInfoOperate(
                    func_name=task.func_name,
                    mp_mediaserver=task.mp_mediaserver,
                    mediaservers=task.mediaservers,
                    stop_event=self._discovery_stop,
                )
                if configer.native_emby_mediainfo_enabled:
                    helper.get_mediainfo_native(path)
                elif not task.sha1:
                    logger.warning(
                        f"{task.func_name} Emby 媒体信息提取跳过：未配置原生模式且缺少 sha1，path={path}"
                    )
                else:
                    helper.get_mediainfo(task.sha1, path, size=task.size)
            except Exception as e:
                logger.error(
                    f"{task.func_name} Emby 媒体信息提取失败: {e}",
                    exc_info=True,
                )
            finally:
                q.task_done()
                sleep(self._TASK_SLEEP_AFTER_SEC)

    def enqueue(
        self,
        func_name: str,
        path: Union[str, Path],
        sha1: Optional[str] = None,
        mp_mediaserver: Optional[str] = None,
        mediaservers: Optional[List[str]] = None,
        size: Optional[int] = None,
    ) -> bool:
        """
        将一条 Emby 媒体信息提取任务加入全局队列

        :param func_name (str): 调用方标识，用于日志
        :param path (str): 媒体路径
        :param sha1 (str): 媒体文件 sha1
        :param mp_mediaserver (str): MoviePilot 媒体服务器路径配置，可选
        :param mediaservers (List): 媒体服务器名称列表，可选
        :param size (int): 文件大小（字节），可选

        :return bool: 入队成功返回 True，队列未启动或已停止返回 False
        """
        try:
            task = EmbyMediainfoTask(
                func_name=func_name,
                mp_mediaserver=mp_mediaserver,
                mediaservers=mediaservers,
                sha1=sha1,
                path=path,
                size=size,
            )
        except Exception as e:
            logger.error(f"【Emby 媒体信息队列】任务参数无效: {e}", exc_info=True)
            return False
        return self._enqueue_task(task)


emby_mediainfo_queue = EmbyMediainfoQueue()
