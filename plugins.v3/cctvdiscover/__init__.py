import asyncio
import re
from dataclasses import dataclass
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


@dataclass
class VideoAlbum:
    """
    CCTV 视频专辑数据模型
    """

    sc: str
    image: str
    fc: str
    id: str
    image2: str
    title: str
    vsetid: str
    vset_cs: str
    channel: str
    image3: str


@dataclass
class VideoAlbumListData:
    """
    CCTV 视频专辑列表数据模型
    """

    total: int
    list: List[VideoAlbum]


@dataclass
class VideoAlbumList:
    """
    CCTV 视频专辑列表响应模型
    """

    data: VideoAlbumListData


class CCTVDiscover(_PluginBase):
    """
    CCTV 探索插件，让探索支持 CCTV 的数据浏览
    """

    # 插件名称
    plugin_name = "CCTV探索"
    # 插件描述
    plugin_desc = "让探索支持CCTV的数据浏览。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/DDSRem-Dev/MoviePilot-Plugins/main/icons/CCTV_A.png"
    # 插件版本
    plugin_version = "3.0.0"
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "cctvdiscover_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _base_api = "https://api.cntv.cn/newVideoset/getCboxVideoAlbumList"
    _enabled = False
    _identity_cache_key = "media_identity"

    def init_plugin(self, config: dict = None):
        """
        根据配置初始化插件启用状态

        :param config: 插件配置字典
        """
        if config:
            self._enabled = config.get("enabled")

    def get_state(self) -> bool:
        """
        返回插件是否已启用

        :return: 插件启用状态
        """
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        """
        返回 CCTV 媒体识别模块

        :return Dict: 模块方法映射
        """
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

    @staticmethod
    def get_media_source() -> List[Dict[str, Any]]:
        """
        返回 CCTV 媒体数据源声明

        :return List: 媒体数据源声明列表
        """
        return [
            {
                "name": "CCTV",
                "media_source": MediaSource("cctv"),
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

    def _save_media_identities(self, items: List[VideoAlbum]) -> None:
        identities = self.get_data(self._identity_cache_key) or {}
        for item in items:
            media_id = str(item.vsetid or item.id or "")
            title = re.sub("[《》]", "", item.title or "")
            if not media_id or not title:
                continue
            identity = {"title": title}
            identities[media_id] = identity
            if item.id:
                identities[str(item.id)] = identity
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))

    @classmethod
    def _fetch_cctv_media(cls, media_id: str) -> Optional[Dict[str, Any]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://app.cctv.com/",
        }
        try:
            for category in ("电视剧", "电影", "动画片", "纪录片", "特别节目"):
                response = RequestUtils(headers=headers, timeout=8).get_res(
                    cls._base_api,
                    params={
                        "p": "1",
                        "n": "100",
                        "serviceId": "cbox",
                        "sort": "desc",
                        "fc": category,
                    },
                )
                if response is None or not response.ok:
                    continue
                for item in (response.json().get("data") or {}).get("list", []):
                    if (
                        str(item.get("vsetid") or "") != media_id
                        and str(item.get("id") or "") != media_id
                    ):
                        continue
                    return {
                        "title": re.sub("[《》]", "", item.get("title") or ""),
                    }
        except Exception as err:
            logger.warning(f"CCTV 媒体详情查询失败：{media_id} - {err}")
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
        通过 CCTV 专辑 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): CCTV 专辑或旧视频 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower() not in {"cctv", "cctvdiscover"}
            or not media_id
        ):
            return None
        identities = self.get_data(self._identity_cache_key) or {}
        source_media = (
            identities.get(str(media_id)) or self._fetch_cctv_media(str(media_id)) or {}
        )
        title = source_media.get("title") or getattr(meta, "title", None)
        if not title:
            return None
        identities[str(media_id)] = {"title": title}
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        recognize_meta = MetaInfo(title)
        recognize_meta.year = getattr(meta, "year", None)
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
        mediainfo.media_source = MediaSource("cctv")
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
        异步通过 CCTV 专辑 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): CCTV 专辑或旧视频 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower() not in {"cctv", "cctvdiscover"}
            or not media_id
        ):
            return None
        identities = await self.async_get_data(self._identity_cache_key) or {}
        source_media = (
            identities.get(str(media_id))
            or await asyncio.to_thread(self._fetch_cctv_media, str(media_id))
            or {}
        )
        title = source_media.get("title") or getattr(meta, "title", None)
        if not title:
            return None
        identities[str(media_id)] = {"title": title}
        await self.async_save_data(
            self._identity_cache_key, dict(list(identities.items())[-2000:])
        )
        media_type = self._normalize_media_type(mtype or getattr(meta, "type", None))
        recognize_meta = MetaInfo(title)
        recognize_meta.year = getattr(meta, "year", None)
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
        mediainfo.media_source = MediaSource("cctv")
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
                "path": "/cctv_discover",
                "endpoint": self.cctv_discover,
                "methods": ["GET"],
                "summary": "CCTV探索数据源",
                "description": "获取CCTV探索数据",
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

    @staticmethod
    def _parse_response(data: Dict[str, Any]) -> VideoAlbumList:
        """
        解析API响应数据
        """
        data_body = data.get("data", {})
        albums = [
            VideoAlbum(
                sc=item.get("sc", ""),
                image=item.get("image", ""),
                fc=item.get("fc", ""),
                id=item.get("id", ""),
                image2=item.get("image2", ""),
                title=item.get("title", ""),
                vsetid=item.get("vsetid", ""),
                vset_cs=item.get("vset_cs", ""),
                channel=item.get("channel", ""),
                image3=item.get("image3", ""),
            )
            for item in data_body.get("list", [])
        ]

        return VideoAlbumList(
            data=VideoAlbumListData(total=data_body.get("total", 0), list=albums)
        )

    @cached(region="cctv_discover_v3", ttl=1800, skip_none=True)
    def __request(self, page_num: int, page_size: int, **kwargs) -> Dict[str, Any]:
        """
        请求CCTV API
        """
        api_url = self._base_api
        params = {
            "p": str(page_num),
            "n": str(page_size),
            "serviceId": "cbox",
            "sort": "desc",
        }
        if kwargs:
            params.update(kwargs)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://app.cctv.com/",
        }
        res = RequestUtils(headers=headers).get_res(
            api_url,
            params=params,
        )
        if res is None:
            raise ConnectionError("无法连接CCTV，请检查网络连接！")
        if not res.ok:
            raise ValueError(f"请求CCTV API失败：{res.text}")
        return res.json()

    def cctv_discover(
        self,
        fc: str = "电视剧",
        area: str = None,
        sc: str = None,
        year: str = None,
        fl: str = None,
        channel: str = None,
        page: int = 1,
        count: int = 30,
    ) -> Response[List[MediaInfo]]:
        """
        获取CCTV探索数据

        :return Response: 媒体信息响应
        """

        def __movie_to_media(movie_info: VideoAlbum) -> MediaInfo:
            return MediaInfo(
                type=MediaType.MOVIE,
                media_source=MediaSource("cctv"),
                title=re.sub("[《》]", "", movie_info.title),
                media_id=movie_info.vsetid or movie_info.id,
                poster_path=movie_info.image,
            )

        def __series_to_media(series_info: VideoAlbum) -> MediaInfo:
            return MediaInfo(
                type=MediaType.TV,
                media_source=MediaSource("cctv"),
                title=re.sub("[《》]", "", series_info.title),
                media_id=series_info.vsetid or series_info.id,
                poster_path=series_info.image,
            )

        try:
            params = {
                "page_num": page,
                "page_size": count,
                "fc": fc,
            }
            if fc:
                params.update({"fc": fc})
            if area:
                params.update({"area": area})
            if sc:
                params.update({"sc": sc})
            if year:
                params.update({"year": year})
            if fl:
                params.update({"fl": fl})
            if channel:
                params.update({"channel": channel})
            result = self._parse_response(self.__request(**params))
        except Exception as err:
            logger.error(str(err))
            return Response(success=True, data=[])
        if not result:
            return Response(success=True, data=[])
        self._save_media_identities(result.data.list)
        if fc == "电影":
            results = [__movie_to_media(movie) for movie in result.data.list[:]]
        else:
            results = [__series_to_media(series) for series in result.data.list[:]]
        return Response(success=True, data=results)

    @staticmethod
    def cctv_filter_ui() -> List[dict]:
        """
        CCTV过滤参数UI配置
        """

        # 媒体类型
        fc = ["电视剧", "电影", "动画片", "纪录片", "特别节目"]
        fc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in fc
        ]

        # 地区分类（电视剧，动画片）
        all_area = [
            "内地（大陆）",
            "港澳台",
            "欧美",
            "日韩",
            "其他",
            "中国大陆",
            "香港",
            "美国",
            "欧洲",
            "泰国",
        ]
        tv_area_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in all_area
        ]
        cartoon_area_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in all_area[0:5]
        ]

        # fc分类
        tv_sc = [
            "谍战",
            "悬疑",
            "刑侦",
            "历史",
            "古装",
            "武侠",
            "军事",
            "战争",
            "喜剧",
            "青春",
            "言情",
            "偶像",
            "家庭",
            "年代",
            "革命",
            "农村",
            "都市",
            "其他",
        ]
        tv_sc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in tv_sc
        ]
        movie_sc = [
            "全部",
            "偶像",
            "古装",
            "喜剧",
            "农村",
            "军旅",
            "惊悚",
            "爱情",
            "文艺",
            "战争",
            "历史",
            "谍战",
            "传记",
            "军事",
            "生活",
            "现代",
            "其他",
        ]
        movie_sc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in movie_sc
        ]
        cartoon_sc = [
            "亲子",
            "搞笑",
            "冒险",
            "动作",
            "宠物",
            "体育",
            "益智",
            "历史",
            "教育",
            "校园",
            "言情",
            "武侠",
            "经典",
            "未来",
            "古代",
            "神话",
            "真人",
            "励志",
            "热血",
            "奇幻",
            "童话",
            "剧情",
            "夺宝",
            "其他",
        ]
        cartoon_sc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in cartoon_sc
        ]
        documentary_sc = [
            "人文历史",
            "人物",
            "军事",
            "探索",
            "社会",
            "自然",
            "时政",
            "经济",
            "科技",
        ]
        documentary_sc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in documentary_sc
        ]
        special_programs_sc = [
            "新闻",
            "经济",
            "综艺",
            "体育",
            "军事",
            "影视",
            "科教",
            "戏曲",
            "青少",
            "音乐",
            "社会",
            "文化",
            "公益",
            "其他",
        ]
        special_programs_sc_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in special_programs_sc
        ]

        # 年份分类（电视剧，电影，纪录片）
        year = [str(i) for i in range(2025, 1996, -1)]
        year_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in year
        ]

        # 字母排序（全部）
        fl = [chr(i) for i in range(ord("A"), ord("Z") + 1)]
        fl_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in fl
        ]

        # 频道分类（纪录片，特别节目）
        channel = {
            "CCTV-1综合,CCTV-1高清,CCTV-1综合高清": "CCTV-1 综合",
            "CCTV-2财经,CCTV-2高清,CCTV-2财经高清": "CCTV-2 财经",
            "CCTV-3综艺,CCTV-3高清,CCTV-3综艺高清": "CCTV-3 综艺",
            "CCTV-4中文国际,CCTV-4高清,CCTV-4中文国际(亚)高清": "CCTV-4 中文国际",
            "CCTV-5体育,CCTV-5高清,CCTV-5体育高清": "CCTV-5 体育",
            "CCTV-6电影,CCTV-6高清,CCTV-6电影高清": "CCTV-6 电影",
            "CCTV-7军事农业,CCTV-7高清,CCTV-7军事农业高清,CCTV-7国防军事高清": "CCTV-7 国防军事",
            "CCTV-8电视剧,CCTV-8高清,CCTV-8电视剧高清": "CCTV-8 电视剧",
            "CCTV-9纪录,CCTV-9高清,CCTV-9纪录高清": "CCTV-9 纪录",
            "CCTV-10科教,CCTV-10高清,CCTV-10科教高清": "CCTV-10 科教",
            "CCTV-11戏曲,CCTV-11高清": "CCTV-11 戏曲",
            "CCTV-12社会与法,CCTV-12高清,CCTV-12社会与法高清": "CCTV-12 社会与法",
            "CCTV-13新闻,CCTV-13高清": "CCTV-13 新闻",
            "CCTV-14少儿,CCTV-14高清,CCTV-14少儿高清": "CCTV-14 少儿",
            "CCTV-15音乐,CCTV-15高清,CCTV-15音乐高清": "CCTV-15 音乐",
            "CCTV-17农业农村高清": "CCTV-17农业农村",
        }
        channel_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": value,
            }
            for key, value in channel.items()
        ]

        return [
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
                        "props": {"model": "fc"},
                        "content": fc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '纪录片' || fc == '特别节目'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "频道"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "channel"},
                        "content": channel_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '电视剧'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "地区"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "area"},
                        "content": tv_area_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '动画片'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "地区"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "area"},
                        "content": cartoon_area_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '电视剧'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "sc"},
                        "content": tv_sc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '电影'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "sc"},
                        "content": movie_sc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '动画片'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "sc"},
                        "content": cartoon_sc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '纪录片'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "sc"},
                        "content": documentary_sc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '特别节目'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "sc"},
                        "content": special_programs_sc_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{fc == '电视剧' || fc == '电影' || fc == '纪录片'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "年份"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "year"},
                        "content": year_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {"class": "flex justify-start items-center"},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "字母顺序"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "fl"},
                        "content": fl_ui,
                    },
                ],
            },
        ]

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听识别事件，使用ChatGPT辅助识别名称
        """
        if not self._enabled:
            return
        event_data: DiscoverSourceEventData = event.event_data
        cctv_source = DiscoverMediaSource(
            name="CCTV",
            media_source=MediaSource("cctv"),
            mediaid_prefix="cctv",
            api_path=f"plugin/CCTVDiscover/cctv_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "fc": "电视剧",
                "area": None,
                "sc": None,
                "year": None,
                "fl": None,
                "channel": None,
            },
            filter_ui=self.cctv_filter_ui(),
            depends={
                "area": ["fc"],
                "sc": ["fc"],
                "year": ["fc"],
                "fl": ["fc"],
                "channel": ["fc"],
            },
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [cctv_source]
        else:
            event_data.extra_sources.append(cctv_source)

    def stop_service(self):
        """
        退出插件
        """
        pass
