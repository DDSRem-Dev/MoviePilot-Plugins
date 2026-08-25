import asyncio
import re
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

from app.plugins import _PluginBase
from app.schemas import DiscoverMediaSource, DiscoverSourceEventData, Response
from app.schemas.types import ChainEventType, MediaSource, MediaType
from app.sdk.cache import cached
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.media import MediaInfo, MetaInfo
from app.sdk.network import RequestUtils

CHANNEL_PARAMS = {
    "电视剧": "2",
    "电影": "3",
    "动漫": "50",
    "少儿": "10",
    "综艺": "1",
    "纪录片": "51",
    "教育": "115",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.mgtv.com",
}

BASE_UI: Optional[List[Dict[str, Any]]] = None


def init_base_ui() -> List[Dict[str, Any]]:
    """
    获取芒果 TV 动态筛选 UI

    :return List: 筛选 UI 配置列表
    """
    ui: List[Dict[str, Any]] = []
    for key, _ in CHANNEL_PARAMS.items():
        params_ui = {
            "platform": "pcweb",
            "allowedRC": "1",
            "channelId": CHANNEL_PARAMS[key],
            "_support": "10000000",
        }
        try:
            res = RequestUtils(headers=HEADERS, timeout=15).get_res(
                "https://pianku.api.mgtv.com/rider/config/channel/v1",
                params=params_ui,
            )
            if res is None or not res.ok:
                continue
            items = (res.json().get("data") or {}).get("listItems") or []
        except Exception as err:
            logger.warning(f"芒果 TV 筛选配置获取失败：{key} - {err}", exc_info=True)
            continue
        for item in items:
            data = [
                {
                    "component": "VChip",
                    "props": {
                        "filter": True,
                        "tile": True,
                        "value": j["tagId"],
                    },
                    "text": j["tagName"],
                }
                for j in item["items"]
                if j["tagName"] != "全部"
            ]
            ui.append(
                {
                    "component": "div",
                    "props": {
                        "class": "flex justify-start items-center",
                        "show": "{{mtype == '" + key + "'}}",
                    },
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "mr-5"},
                            "content": [
                                {"component": "VLabel", "text": item["typeName"]}
                            ],
                        },
                        {
                            "component": "VChipGroup",
                            "props": {"model": item["eName"]},
                            "content": data,
                        },
                    ],
                }
            )
    return ui


class MangGuoDiscover(_PluginBase):
    """
    芒果 TV 探索插件，让探索支持芒果 TV 的数据浏览
    """

    # 插件名称
    plugin_name = "芒果TV探索"
    # 插件描述
    plugin_desc = "让探索支持芒果TV的数据浏览。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/DDSRem-Dev/MoviePilot-Plugins/main/icons/mangguo_A.jpg"
    # 插件版本
    plugin_version = "3.0.0"
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "mangguodiscover_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _identity_cache_key = "media_identity"

    def init_plugin(self, config: dict = None):
        """
        根据配置初始化插件启用状态

        :param config: 插件配置字典
        """
        global BASE_UI
        if config:
            self._enabled = config.get("enabled")
        if "hitv.com" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("hitv.com")
        BASE_UI = init_base_ui()

    def get_state(self) -> bool:
        """
        返回插件是否已启用

        :return: 插件启用状态
        """
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        """
        返回芒果 TV 媒体识别模块

        :return Dict: 模块方法映射
        """
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

    @staticmethod
    def get_media_source() -> List[Dict[str, Any]]:
        """
        返回芒果 TV 媒体数据源声明

        :return List: 媒体数据源声明列表
        """
        return [
            {
                "name": "芒果TV",
                "media_source": MediaSource.MangoTV,
                "media_types": [MediaType.MOVIE, MediaType.TV],
            }
        ]

    @staticmethod
    def _normalize_media_type(mtype: Any) -> Optional[MediaType]:
        if isinstance(mtype, MediaType):
            return mtype
        try:
            return MediaType(mtype) if mtype else None
        except (TypeError, ValueError):
            return None

    def _save_media_identities(self, items: List[Dict[str, Any]]) -> None:
        identities = self.get_data(self._identity_cache_key) or {}
        for item in items:
            media_id = str(item.get("clipId") or "")
            title = item.get("title")
            if not media_id or not title:
                continue
            identities[media_id] = {
                "title": title,
                "year": str(item.get("year") or "").strip() or None,
            }
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))

    @staticmethod
    def _fetch_mangguo_media(media_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = RequestUtils(headers=HEADERS).get_res(
                f"https://www.mgtv.com/b/{media_id}/"
            )
            if response is None or not response.ok:
                return None
            match = re.search(
                r"<title>([^<]+?)(?:\s+第\d+集)?\s+-\s+芒果TV", response.text
            )
            if not match:
                return None
            return {"title": unescape(match.group(1)).strip()}
        except (AttributeError, TypeError, ValueError) as err:
            logger.warning(f"芒果 TV 媒体详情查询失败：{media_id} - {err}")
            return None

    def recognize_media(
        self,
        meta: Any = None,
        mtype: Any = None,
        media_source: Optional[MediaSource] = None,
        media_id: Optional[str] = None,
        episode_group: Optional[str] = None,
        cache: bool = True,
        **kwargs: Any,
    ) -> Any:
        """
        通过芒果 TV 专辑 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 芒果 TV 专辑 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower()
            not in {
                "mangguo",
                "mangguodiscover",
            }
            or not media_id
        ):
            return None
        identities = self.get_data(self._identity_cache_key) or {}
        source_media = (
            self._fetch_mangguo_media(str(media_id))
            or identities.get(str(media_id))
            or {}
        )
        title = source_media.get("title") or getattr(meta, "title", None)
        year = source_media.get("year") or getattr(meta, "year", None)
        if not title:
            return None
        identities[str(media_id)] = {
            "title": title,
            "year": str(year) if year else None,
        }
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        recognize_meta = MetaInfo(title)
        recognize_meta.year = str(year) if year else None
        recognize_meta.type = media_type
        mediainfo = self.chain.run_module(
            "recognize_media",
            meta=recognize_meta,
            mtype=media_type,
            media_source=MediaSource.TMDB,
            media_id=None,
            episode_group=episode_group,
            cache=cache,
        )
        if not mediainfo:
            return None
        mediainfo.media_source = MediaSource.MangoTV
        mediainfo.media_id = str(media_id)
        return mediainfo

    async def async_recognize_media(
        self,
        meta: Any = None,
        mtype: Any = None,
        media_source: Optional[MediaSource] = None,
        media_id: Optional[str] = None,
        episode_group: Optional[str] = None,
        cache: bool = True,
        **kwargs: Any,
    ) -> Any:
        """
        异步通过芒果 TV 专辑 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 芒果 TV 专辑 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower()
            not in {
                "mangguo",
                "mangguodiscover",
            }
            or not media_id
        ):
            return None
        identities = await self.async_get_data(self._identity_cache_key) or {}
        source_media = await asyncio.to_thread(self._fetch_mangguo_media, str(media_id))
        source_media = source_media or identities.get(str(media_id)) or {}
        title = source_media.get("title") or getattr(meta, "title", None)
        year = source_media.get("year") or getattr(meta, "year", None)
        if not title:
            return None
        identities[str(media_id)] = {
            "title": title,
            "year": str(year) if year else None,
        }
        await self.async_save_data(
            self._identity_cache_key, dict(list(identities.items())[-2000:])
        )
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        recognize_meta = MetaInfo(title)
        recognize_meta.year = str(year) if year else None
        recognize_meta.type = media_type
        mediainfo = await self.chain.async_run_module(
            "async_recognize_media",
            meta=recognize_meta,
            mtype=media_type,
            media_source=MediaSource.TMDB,
            media_id=None,
            episode_group=episode_group,
            cache=cache,
        )
        if not mediainfo:
            return None
        mediainfo.media_source = MediaSource.MangoTV
        mediainfo.media_id = str(media_id)
        return mediainfo

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件命令列表

        :return: 命令列表
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表

        :return: API 端点列表
        """
        return [
            {
                "path": "/mangguo_discover",
                "endpoint": self.mangguo_discover,
                "methods": ["GET"],
                "summary": "芒果TV探索数据源",
                "description": "获取芒果TV探索数据",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ], {"enabled": False}

    def get_page(self) -> List[dict]:
        """
        返回插件静态页面列表

        :return: 静态页面列表
        """
        pass

    @cached(region="mangguo_discover", ttl=1800, skip_none=True)
    def __request(self, **kwargs) -> Dict:
        """
        请求芒果TV API
        """
        api_url = "https://pianku.api.mgtv.com/rider/list/pcweb/v3"
        res = RequestUtils(headers=HEADERS).get_res(api_url, params=kwargs)
        if res is None:
            raise ConnectionError("无法连接芒果TV，请检查网络连接！")
        if not res.ok:
            raise ValueError(f"请求芒果TV API失败：{res.text}")
        return res.json().get("data").get("hitDocs")

    def mangguo_discover(
        self,
        mtype: str = "电视剧",
        chargeInfo: str = None,
        sort: str = None,
        kind: str = None,
        edition: str = None,
        area: str = None,
        fitAge: str = None,
        year: str = None,
        feature: str = None,
        page: int = 1,
        count: int = 80,
    ) -> Response[List[MediaInfo]]:
        """
        获取芒果TV探索数据

        :return Response: 媒体信息响应
        """

        def __movie_to_media(movie_info: dict) -> MediaInfo:
            """
            电影数据转换为MediaInfo
            """
            return MediaInfo(
                type=MediaType.MOVIE,
                media_source=MediaSource.MangoTV,
                title=movie_info.get("title"),
                year=movie_info.get("year"),
                media_id=str(movie_info.get("clipId")),
                poster_path=movie_info.get("img"),
            )

        def __series_to_media(series_info: dict) -> MediaInfo:
            """
            电视剧数据转换为MediaInfo
            """
            return MediaInfo(
                type=MediaType.TV,
                media_source=MediaSource.MangoTV,
                title=series_info.get("title"),
                year=series_info.get("year"),
                media_id=str(series_info.get("clipId")),
                poster_path=series_info.get("img"),
            )

        try:
            params = {
                "allowedRC": "1",
                "platform": "pcweb",
                "channelId": CHANNEL_PARAMS[mtype],
                "pn": str(page),
                "pc": str(count),
                "hudong": "1",
                "_support": "10000000",
            }
            if chargeInfo:
                params.update({"chargeInfo": chargeInfo})
            if sort:
                params.update({"sort": sort})
            if kind:
                params.update({"kind": kind})
            if edition:
                params.update({"edition": edition})
            if area:
                params.update({"area": area})
            if fitAge:
                params.update({"fitAge": fitAge})
            if year:
                params.update({"year": year})
            if feature:
                params.update({"feature": feature})
            result = self.__request(**params)
        except Exception as err:
            logger.error(str(err))
            return Response(success=True, data=[])
        if not result:
            return Response(success=True, data=[])
        self._save_media_identities(result)
        if mtype == "电影":
            results = [__movie_to_media(movie) for movie in result]
        else:
            results = [__series_to_media(series) for series in result]
        return Response(success=True, data=results)

    @staticmethod
    def mangguo_filter_ui() -> List[dict]:
        """
        芒果TV过滤参数UI配置
        """

        mtype_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": key,
            }
            for key in CHANNEL_PARAMS
        ]
        ui = [
            {
                "component": "div",
                "props": {"class": "flex justify-start items-center"},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "种类"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "mtype"},
                        "content": mtype_ui,
                    },
                ],
            },
        ]
        for i in BASE_UI or []:
            ui.append(i)

        return ui

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听识别事件，使用ChatGPT辅助识别名称
        """
        if not self._enabled:
            return
        event_data: DiscoverSourceEventData = event.event_data
        mangguo_source = DiscoverMediaSource(
            name="芒果TV",
            media_source=MediaSource.MangoTV,
            mediaid_prefix="mangguo",
            api_path=f"plugin/MangGuoDiscover/mangguo_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "电视剧",
                "chargeInfo": None,
                "sort": None,
                "kind": None,
                "edition": None,
                "area": None,
                "fitAge": None,
                "year": None,
                "feature": None,
            },
            filter_ui=self.mangguo_filter_ui(),
            depends={
                "chargeInfo": ["mtype"],
                "sort": ["mtype"],
                "kind": ["mtype"],
                "edition": ["mtype"],
                "area": ["mtype"],
                "fitAge": ["mtype"],
                "year": ["mtype"],
                "feature": ["mtype"],
            },
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [mangguo_source]
        else:
            event_data.extra_sources.append(mangguo_source)

    def stop_service(self):
        """
        退出插件
        """
        pass
