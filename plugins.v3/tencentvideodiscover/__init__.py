import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.plugins import _PluginBase
from app.schemas import DiscoverMediaSource, DiscoverSourceEventData, Response
from app.schemas.types import ChainEventType, MediaSource, MediaType
from app.sdk.cache import cached
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.media import MediaInfo, MetaInfo

BASE_UI: Optional[List[Dict[str, Any]]] = None

CHANNEL_PARAMS = {
    "tv": {"Id": "100113", "Name": "电视剧"},
    "movie": {"Id": "100173", "Name": "电影"},
    "variety": {"Id": "100109", "Name": "综艺"},
    "anime": {"Id": "100119", "Name": "动漫"},
    "children": {"Id": "100150", "Name": "少儿"},
    "documentary": {"Id": "100105", "Name": "纪录片"},
}

PARAMS = {
    "video_appid": "1000005",
    "vplatform": "2",
    "vversion_name": "8.9.10",
    "new_mark_label_enabled": "1",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://v.qq.com/",
}


def init_base_ui() -> List[Dict[str, Any]]:
    """
    获取腾讯视频动态筛选 UI

    :return List: 筛选 UI 配置列表
    """

    def get_page_data(channel_id):
        """
        获取指定频道页面的数据

        :param channel_id: 频道 ID
        :return: 频道条目数据列表
        """
        body = {
            "page_params": {
                "channel_id": channel_id,
                "page_type": "channel_operation",
                "page_id": "channel_list_second_page",
            }
        }
        url = "https://pbaccess.video.qq.com/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData"
        try:
            response = requests.post(
                url,
                params=PARAMS,
                json=body,
                headers=HEADERS,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json().get("data")
            if not data:
                logger.error(f"No data returned for channel_id {channel_id}")
                return []

            module_list_datas = data.get("module_list_datas", [])
            if len(module_list_datas) < 2:
                logger.error(
                    f"module_list_datas has insufficient length for channel_id {channel_id}: {module_list_datas}"
                )
                return []

            module_datas = module_list_datas[1].get("module_datas", [])
            if not module_datas:
                logger.error(f"No module_datas for channel_id {channel_id}")
                return []

            item_data_lists = module_datas[0].get("item_data_lists", {})
            item_datas = item_data_lists.get("item_datas", [])
            if not item_datas:
                logger.warning(f"No item_datas for channel_id {channel_id}")

            return item_datas
        except requests.RequestException as e:
            logger.error(f"Failed to fetch data for channel_id {channel_id}: {str(e)}")
            return []
        except (KeyError, IndexError) as e:
            logger.error(
                f"Invalid response structure for channel_id {channel_id}: {str(e)}"
            )
            return []

    ui = []
    for _key, _ in CHANNEL_PARAMS.items():
        data = []
        all_index = {}
        for item in get_page_data(CHANNEL_PARAMS[_key]["Id"]):
            if str(item.get("item_type")) == "11":
                if item.get("item_params", {}).get("index_name") not in all_index:
                    all_index[item["item_params"]["index_name"]] = []
                    all_index[item["item_params"]["index_name"]].append(item)
                else:
                    all_index[item["item_params"]["index_name"]].append(item)

        for _, value in all_index.items():
            data = [
                {
                    "component": "VChip",
                    "props": {
                        "filter": True,
                        "tile": True,
                        "value": j["item_params"]["option_value"],
                    },
                    "text": j["item_params"]["option_name"],
                }
                for j in value
                if str(j["item_params"].get("option_value", "")) != "-1"
            ]
            if str(value[0]["item_params"].get("option_value", "")) == "-1":
                text = value[0]["item_params"]["option_name"]
            else:
                text = value[0]["item_params"]["index_name"]
            ui.append(
                {
                    "component": "div",
                    "props": {
                        "class": "flex justify-start items-center",
                        "show": "{{mtype == '" + _key + "'}}",
                    },
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "mr-5"},
                            "content": [
                                {
                                    "component": "VLabel",
                                    "text": text,
                                }
                            ],
                        },
                        {
                            "component": "VChipGroup",
                            "props": {
                                "model": value[0]["item_params"]["index_item_key"]
                            },
                            "content": data,
                        },
                    ],
                }
            )

    return ui


class TencentVideoDiscover(_PluginBase):
    """
    腾讯视频探索插件，让探索支持腾讯视频的数据浏览
    """

    # 插件名称
    plugin_name = "腾讯视频探索"
    # 插件描述
    plugin_desc = "让探索支持腾讯视频的数据浏览。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/DDSRem-Dev/MoviePilot-Plugins/main/icons/tencentvideo_A.png"
    # 插件版本
    plugin_version = "3.0.0"
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "tencentvideodiscover_"
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
        if "puui.qpic.cn" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("puui.qpic.cn")
        BASE_UI = init_base_ui()

    def get_state(self) -> bool:
        """
        返回插件是否已启用

        :return: 插件启用状态
        """
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        """
        返回腾讯视频媒体识别模块

        :return Dict: 模块方法映射
        """
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

    @staticmethod
    def get_media_source() -> List[Dict[str, Any]]:
        """
        返回腾讯视频媒体数据源声明

        :return List: 媒体数据源声明列表
        """
        return [
            {
                "name": "腾讯视频",
                "media_source": MediaSource.TencentVideo,
                "media_types": [MediaType.MOVIE, MediaType.TV],
            }
        ]

    def _save_media_identities(self, items: List[Dict[str, Any]]) -> None:
        identities = self.get_data(self._identity_cache_key) or {}
        for item in items:
            media_id = str(item.get("cid") or "")
            title = item.get("title")
            if not media_id or not title:
                continue
            identities[media_id] = {
                "title": title,
                "year": str(item.get("year") or "").strip() or None,
            }
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))

    def _get_media_identity(self, media_id: str) -> Dict[str, Any]:
        identities = self.get_data(self._identity_cache_key) or {}
        return identities.get(str(media_id)) or {}

    def _remember_media_identity(
        self, media_id: str, title: str, year: Optional[str]
    ) -> None:
        identities = self.get_data(self._identity_cache_key) or {}
        identities[str(media_id)] = {"title": title, "year": year}
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))

    @staticmethod
    def _normalize_media_type(mtype: Any) -> Optional[MediaType]:
        if isinstance(mtype, MediaType):
            return mtype
        try:
            return MediaType(mtype) if mtype else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fetch_tencent_media(media_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                "https://node.video.qq.com/x/api/float_vinfo2",
                params={"cid": media_id},
                headers=HEADERS,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json().get("c") or {}
            if not data.get("title"):
                return None
            return {
                "title": data.get("title"),
                "year": str(data.get("year") or "").strip() or None,
                "overview": data.get("description"),
            }
        except (requests.RequestException, ValueError) as err:
            logger.warning(f"腾讯视频媒体详情查询失败：{media_id} - {err}")
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
        通过腾讯视频 CID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 腾讯视频 CID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower()
            not in {
                "tencentvideo",
                "tencentvideodiscover",
            }
            or not media_id
        ):
            return None
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        source_media = self._fetch_tencent_media(
            str(media_id)
        ) or self._get_media_identity(str(media_id))
        title = source_media.get("title") or getattr(meta, "title", None)
        year = source_media.get("year") or getattr(meta, "year", None)
        if not title:
            return None
        self._remember_media_identity(str(media_id), title, str(year) if year else None)
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
        mediainfo.media_source = MediaSource.TencentVideo
        mediainfo.media_id = str(media_id)
        if source_media.get("overview") and not mediainfo.overview:
            mediainfo.overview = source_media["overview"]
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
        异步通过腾讯视频 CID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 腾讯视频 CID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower()
            not in {
                "tencentvideo",
                "tencentvideodiscover",
            }
            or not media_id
        ):
            return None
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        source_media = await asyncio.to_thread(self._fetch_tencent_media, str(media_id))
        source_media = source_media or self._get_media_identity(str(media_id))
        title = source_media.get("title") or getattr(meta, "title", None)
        year = source_media.get("year") or getattr(meta, "year", None)
        if not title:
            return None
        identities = await self.async_get_data(self._identity_cache_key) or {}
        identities[str(media_id)] = {
            "title": title,
            "year": str(year) if year else None,
        }
        await self.async_save_data(
            self._identity_cache_key, dict(list(identities.items())[-2000:])
        )
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
        mediainfo.media_source = MediaSource.TencentVideo
        mediainfo.media_id = str(media_id)
        if source_media.get("overview") and not mediainfo.overview:
            mediainfo.overview = source_media["overview"]
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
                "path": "/tencentvideo_discover",
                "endpoint": self.tencentvideo_discover,
                "methods": ["GET"],
                "summary": "腾讯视频探索数据源",
                "description": "获取腾讯视频探索数据",
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

    @cached(region="tencentvideo_discover", ttl=1800, skip_none=True)
    def __request(self, page: int, mtype: str, **kwargs: Any) -> List[Dict]:
        """
        请求腾讯视频 API
        """
        page = max(int(page), 1)
        body = {
            "page_params": {
                "channel_id": CHANNEL_PARAMS[mtype]["Id"],
                "page_type": "channel_operation",
                "page_id": "channel_list_second_page",
            }
        }
        if kwargs:
            body["page_params"]["filter_params"] = "&".join(
                [f"{k}={v}" for k, v in kwargs.items()]
            )
        url = "https://pbaccess.video.qq.com/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData"

        def request_data() -> Dict[str, Any]:
            response = requests.post(url, params=PARAMS, json=body, headers=HEADERS)
            response.raise_for_status()
            return response.json().get("data") or {}

        try:
            data = request_data()
            if not data:
                logger.error(f"No data returned for mtype {mtype}, page {page}")
                return []

            if page > 1:
                next_page_context = data.get("next_page_context", {})
                page_context_key = next(
                    (
                        key
                        for key in next_page_context
                        if key.startswith("_ds_cli_") and key.endswith("_page")
                    ),
                    None,
                )
                if not page_context_key:
                    logger.error(
                        f"No page context returned for mtype {mtype}, page {page}"
                    )
                    return []
                body["page_context"] = {page_context_key: str(page - 1)}
                data = request_data()
                if not data:
                    logger.error(f"No data returned for mtype {mtype}, page {page}")
                    return []

            for module_list_data in data.get("module_list_datas", []):
                for module_data in module_list_data.get("module_datas", []):
                    item_datas = module_data.get("item_data_lists", {}).get(
                        "item_datas", []
                    )
                    if any(str(item.get("item_type")) == "2" for item in item_datas):
                        return item_datas

            logger.warning(f"No media item data for mtype {mtype}, page {page}")
            return []
        except requests.RequestException as e:
            logger.error(
                f"Failed to fetch data for mtype {mtype}, page {page}: {str(e)}"
            )
            return []
        except (KeyError, IndexError) as e:
            logger.error(
                f"Invalid response structure for mtype {mtype}, page {page}: {str(e)}"
            )
            return []

    def tencentvideo_discover(
        self,
        mtype: str = "tv",
        recommend_3: str = None,
        itrailer: str = None,
        exclusive: str = None,
        child_ip: str = None,
        characteristic: str = None,
        anime_status: str = None,
        recommend: str = None,
        language: str = None,
        iregion: str = None,
        iyear: str = None,
        all: str = None,
        sort: str = None,
        ipay: str = None,
        producer: str = None,
        iarea: str = None,
        pay: str = None,
        attr: str = None,
        item: str = None,
        itype: str = None,
        recommend_2: str = None,
        recommend_1: str = None,
        award: str = None,
        theater: str = None,
        gender: str = None,
        page: int = 1,
        count: int = 10,
    ) -> Response[List[MediaInfo]]:
        """
        获取腾讯视频探索数据

        :return Response: 媒体信息响应
        """

        def __movie_to_media(movie_info: dict) -> MediaInfo:
            """
            电影数据转换为MediaInfo
            """
            # 尝试获取 new_pic_vt 字段
            poster_url = movie_info.get("new_pic_vt", "")
            if not poster_url or not poster_url.startswith(("http://", "https://")):
                logger.warning(
                    f"Invalid or missing poster URL for {movie_info.get('title')}: {poster_url}"
                )
                # 尝试从 item_params 中寻找备用图片字段
                poster_url = (
                    movie_info.get("item_params", {}).get("pic_url")
                    or movie_info.get("item_params", {}).get("image_url")
                    or "https://v.qq.com/assets/default_poster.jpg"
                )  # 默认图片 URL
            else:
                # 移除 /350 后验证 URL
                poster_url = re.sub(r"/350", "", poster_url)
                if not poster_url.startswith(("http://", "https://")):
                    logger.warning(
                        f"Processed poster URL invalid for {movie_info.get('title')}: {poster_url}"
                    )
                    poster_url = "https://v.qq.com/assets/default_poster.jpg"

            logger.debug(
                f"Final poster URL for {movie_info.get('title')}: {poster_url}"
            )
            return MediaInfo(
                type=MediaType.MOVIE,
                media_source=MediaSource.TencentVideo,
                title=movie_info.get("title"),
                year=movie_info.get("year"),
                media_id=str(movie_info.get("cid")),
                poster_path=poster_url,
            )

        def __series_to_media(series_info: dict) -> MediaInfo:
            """
            电视剧数据转换为MediaInfo
            """
            # 尝试获取 new_pic_vt 字段
            poster_url = series_info.get("new_pic_vt", "")
            if not poster_url or not poster_url.startswith(("http://", "https://")):
                logger.warning(
                    f"Invalid or missing poster URL for {series_info.get('title')}: {poster_url}"
                )
                # 尝试从 item_params 中寻找备用图片字段
                poster_url = (
                    series_info.get("item_params", {}).get("pic_url")
                    or series_info.get("item_params", {}).get("image_url")
                    or "https://v.qq.com/assets/default_poster.jpg"
                )  # 默认图片 URL
            else:
                # 移除 /350 后验证 URL
                poster_url = re.sub(r"/350", "", poster_url)
                if not poster_url.startswith(("http://", "https://")):
                    logger.warning(
                        f"Processed poster URL invalid for {series_info.get('title')}: {poster_url}"
                    )
                    poster_url = "https://v.qq.com/assets/default_poster.jpg"

            logger.debug(
                f"Final poster URL for {series_info.get('title')}: {poster_url}"
            )
            return MediaInfo(
                type=MediaType.TV,
                media_source=MediaSource.TencentVideo,
                title=series_info.get("title"),
                year=series_info.get("year"),
                media_id=str(series_info.get("cid")),
                poster_path=poster_url,
            )

        try:
            params = {}
            if recommend_3:
                params.update({"recommend_3": recommend_3})
            if itrailer:
                params.update({"itrailer": itrailer})
            if exclusive:
                params.update({"exclusive": exclusive})
            if child_ip:
                params.update({"child_ip": child_ip})
            if characteristic:
                params.update({"characteristic": characteristic})
            if anime_status:
                params.update({"anime_status": anime_status})
            if recommend:
                params.update({"recommend": recommend})
            if language:
                params.update({"language": language})
            if iregion:
                params.update({"iregion": iregion})
            if iyear:
                params.update({"iyear": iyear})
            if all:
                params.update({"all": all})
            if sort:
                params.update({"sort": sort})
            if ipay:
                params.update({"ipay": ipay})
            if producer:
                params.update({"producer": producer})
            if iarea:
                params.update({"iarea": iarea})
            if pay:
                params.update({"pay": pay})
            if attr:
                params.update({"attr": attr})
            if item:
                params.update({"item": item})
            if itype:
                params.update({"itype": itype})
            if recommend_2:
                params.update({"recommend_2": recommend_2})
            if recommend_1:
                params.update({"recommend_1": recommend_1})
            if award:
                params.update({"award": award})
            if theater:
                params.update({"theater": theater})
            if gender:
                params.update({"gender": gender})
            result = self.__request(page, mtype, **params)
        except Exception as err:
            logger.error(f"Error fetching Tencent Video data: {str(err)}")
            return Response(success=True, data=[])
        if not result:
            return Response(success=True, data=[])
        media_items = [
            item.get("item_params", {})
            for item in result
            if str(item.get("item_type", "")) == "2"
        ]
        self._save_media_identities(media_items)
        if mtype == "movie":
            results = [__movie_to_media(movie_info) for movie_info in media_items]
        else:
            results = [__series_to_media(series_info) for series_info in media_items]
        return Response(success=True, data=results)

    @staticmethod
    def tencentvideo_filter_ui() -> List[dict]:
        """
        腾讯视频过滤参数UI配置
        """
        mtype_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": value["Name"],
            }
            for key, value in CHANNEL_PARAMS.items()
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
            }
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
        tencentvideo_source = DiscoverMediaSource(
            name="腾讯视频",
            media_source=MediaSource.TencentVideo,
            mediaid_prefix="tencentvideo",
            api_path=f"plugin/TencentVideoDiscover/tencentvideo_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "tv",
                "recommend_3": None,
                "itrailer": None,
                "exclusive": None,
                "child_ip": None,
                "characteristic": None,
                "anime_status": None,
                "recommend": None,
                "language": None,
                "iregion": None,
                "iyear": None,
                "all": None,
                "sort": None,
                "ipay": None,
                "producer": None,
                "iarea": None,
                "pay": None,
                "attr": None,
                "item": None,
                "itype": None,
                "recommend_2": None,
                "recommend_1": None,
                "award": None,
                "theater": None,
                "gender": None,
            },
            filter_ui=self.tencentvideo_filter_ui(),
            depends={
                "recommend_3": ["mtype"],
                "itrailer": ["mtype"],
                "exclusive": ["mtype"],
                "child_ip": ["mtype"],
                "characteristic": ["mtype"],
                "anime_status": ["mtype"],
                "recommend": ["mtype"],
                "language": ["mtype"],
                "iregion": ["mtype"],
                "iyear": ["mtype"],
                "all": ["mtype"],
                "sort": ["mtype"],
                "ipay": ["mtype"],
                "producer": ["mtype"],
                "iarea": ["mtype"],
                "pay": ["mtype"],
                "attr": ["mtype"],
                "item": ["mtype"],
                "itype": ["mtype"],
                "recommend_2": ["mtype"],
                "recommend_1": ["mtype"],
                "award": ["mtype"],
                "theater": ["mtype"],
                "gender": ["mtype"],
            },
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [tencentvideo_source]
        else:
            event_data.extra_sources.append(tencentvideo_source)

    def stop_service(self):
        """
        退出插件
        """
        pass
