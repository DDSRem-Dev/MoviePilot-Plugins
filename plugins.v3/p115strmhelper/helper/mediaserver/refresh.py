from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from app.chain.media import MediaChain
from app.schemas import MediaInfo, RefreshMediaItem, ServiceInfo
from app.sdk.logging import logger
from app.sdk.media import MetaInfoPath
from app.sdk.services import MediaServerHelper as MpMediaServerHelper

from ...utils.path import PathUtils


class MediaServerRefresh:
    """
    媒体服务器操作
    """

    def __init__(
        self,
        func_name: str,
        enabled: bool = False,
        mediaservers: Optional[List[str]] = None,
        mp_mediaserver: Optional[str] = None,
        delay_seconds: int = 0,
    ):
        """
        初始化媒体服务器刷新器

        :param func_name (str): 调用方标识，用于日志
        :param enabled (bool): 是否启用刷新
        :param mediaservers (List): 媒体服务器名称列表
        :param mp_mediaserver (str): MoviePilot 媒体服务器路径配置
        :param delay_seconds (int): 刷新延迟秒数
        """
        self.func_name = func_name
        self.media_servers = mediaservers
        self.mp_mediaserver = mp_mediaserver
        self.enabled = enabled
        self.delay_seconds = max(0, delay_seconds)

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        """
        媒体服务器服务信息

        :return Dict: 媒体服务器服务信息
        """
        if not self.media_servers:
            logger.warning(f"{self.func_name}尚未配置媒体服务器，请检查配置")
            return None

        mediaserver_helper = MpMediaServerHelper()

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
                active_services[service_name] = service_info

        if not active_services:
            logger.warning(f"{self.func_name}没有已连接的媒体服务器，请检查配置")
            return None

        return active_services

    def _try_emby_native_refresh(
        self, file_path: str, file_name: Optional[str]
    ) -> bool:
        """
        尝试通知 Emby 发现新增文件

        :param file_path (str): 文件路径
        :param file_name (str): 文件名

        :return bool: 是否已向所有选中服务成功提交发现请求
        """
        from .emby import EmbyOperate

        services = self.service_infos or {}
        emby_services = {
            name: service
            for name, service in services.items()
            if service.type == "emby"
        }
        if not emby_services:
            return False

        emby_operate = EmbyOperate(func_name=self.func_name)
        success = True
        for name in emby_services:
            if emby_operate.notify_media_updated(name, file_path):
                logger.info(f"{self.func_name}{file_name} Emby 文件发现请求已提交")
            else:
                success = False
                logger.warning(f"{self.func_name}{file_name} Emby 文件发现请求提交失败")

        non_emby_services = [
            name for name, service in services.items() if service.type != "emby"
        ]
        if non_emby_services:
            logger.warning(
                f"{self.func_name}{file_name} 其他媒体服务器 {', '.join(non_emby_services)} 无法刷新媒体库"
            )
        return success and not non_emby_services

    def refresh_mediaserver(
        self,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        mediainfo: Optional[MediaInfo] = None,
        refresh_all: bool = False,
    ) -> bool:
        """
        刷新媒体服务器

        :param file_path (str): 文件路径
        :param file_name (str): 文件名
        :param mediainfo (MediaInfo): 媒体信息
        :param refresh_all (bool): 是否刷新所有媒体服务器

        :return bool: 是否刷新成功
        """
        if not self.enabled:
            return True
        if not self.service_infos:
            return False
        if self.delay_seconds > 0:
            from ...service.one_shot import schedule_plugin_one_shot

            logger.info(
                f"{self.func_name}{file_name} 延迟 {self.delay_seconds} 秒后刷新媒体服务器"
            )
            return schedule_plugin_one_shot(
                service_id=f"mediaserver_refresh_{uuid4().hex}",
                name=f"{self.func_name}媒体库刷新",
                func=self._run_delayed_refresh,
                func_kwargs={
                    "file_path": file_path,
                    "file_name": file_name,
                    "mediainfo": mediainfo,
                    "refresh_all": refresh_all,
                },
                delay_sec=self.delay_seconds,
            )
        return self._do_refresh(file_path, file_name, mediainfo, refresh_all)

    def _run_delayed_refresh(
        self,
        file_path: Optional[str],
        file_name: Optional[str],
        mediainfo: Optional[MediaInfo],
        refresh_all: bool,
    ) -> None:
        if not self._do_refresh(file_path, file_name, mediainfo, refresh_all):
            raise RuntimeError(f"{self.func_name}媒体库刷新请求失败，请检查日志")

    def _do_refresh(
        self,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        mediainfo: Optional[MediaInfo] = None,
        refresh_all: bool = False,
    ) -> bool:
        """
        执行媒体服务器刷新

        :param file_path (str): 文件路径
        :param file_name (str): 文件名
        :param mediainfo (MediaInfo): 媒体信息
        :param refresh_all (bool): 是否刷新所有媒体服务器

        :return bool: 是否刷新成功
        """
        logger.info(f"{self.func_name}{file_name} 开始刷新媒体服务器")
        if refresh_all:
            for name, service in self.service_infos.items():
                if hasattr(service.instance, "refresh_root_library"):
                    service.instance.refresh_root_library()
                else:
                    logger.warning(f"{self.func_name}{name} 不支持刷新")
            return True
        if not file_path:
            logger.warning(f"{self.func_name}未提供文件路径，跳过刷新")
            return False
        if self.mp_mediaserver:
            status, mediaserver_path, moviepilot_path = PathUtils.get_media_path(
                self.mp_mediaserver,
                file_path,
            )
            if status:
                logger.info(f"{self.func_name}{file_name} 刷新媒体服务器目录替换中...")
                file_path = file_path.replace(
                    moviepilot_path, mediaserver_path, 1
                ).replace("\\", "/")
                logger.info(
                    f"{self.func_name}刷新媒体服务器目录替换: {moviepilot_path} --> {mediaserver_path}"
                )
                logger.info(f"{self.func_name}刷新媒体服务器目录: {file_path}")
            else:
                logger.warning(
                    f"{self.func_name}{file_name} 无法匹配媒体服务器路径，跳过刷新"
                )
                return False
        if not mediainfo:
            media_chain = MediaChain()
            meta = MetaInfoPath(path=Path(file_path))
            mediainfo = media_chain.recognize_media(meta=meta)
            if not mediainfo:
                if self._try_emby_native_refresh(file_path, file_name):
                    return True
                logger.warning(f"{self.func_name}{file_name} 无法刷新媒体库")
                return False
        items = [
            RefreshMediaItem(
                title=mediainfo.title,
                year=mediainfo.year,
                type=mediainfo.type,
                category=mediainfo.category,
                target_path=Path(file_path),
            )
        ]
        for name, service in self.service_infos.items():
            if hasattr(service.instance, "refresh_library_by_items"):
                service.instance.refresh_library_by_items(items)
            else:
                logger.warning(f"{self.func_name}{file_name} {name} 不支持刷新")
        return True
