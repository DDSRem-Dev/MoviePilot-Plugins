import asyncio
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


class MiGuDiscover(_PluginBase):
    """
    咪咕视频探索插件，让探索支持咪咕视频的数据浏览
    """

    # 插件名称
    plugin_name = "咪咕视频探索"
    # 插件描述
    plugin_desc = "让探索支持咪咕视频的数据浏览。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/DDSRem-Dev/MoviePilot-Plugins/main/icons/migu_A.png"
    # 插件版本
    plugin_version = "3.0.0"
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "migudiscover_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _base_api = "https://jadeite.migu.cn/search/v3/category"
    _enabled = False
    _identity_cache_key = "media_identity"

    def init_plugin(self, config: dict = None):
        """
        根据配置初始化插件启用状态

        :param config: 插件配置字典
        """
        if config:
            self._enabled = config.get("enabled")
        if "https://wapx.cmvideo.cn" not in settings.SECURITY_IMAGE_DOMAINS:
            settings.SECURITY_IMAGE_DOMAINS.append("https://wapx.cmvideo.cn")

    def get_state(self) -> bool:
        """
        返回插件是否已启用

        :return: 插件启用状态
        """
        return self._enabled

    def get_module(self) -> Dict[str, Any]:
        """
        返回咪咕视频媒体识别模块

        :return Dict: 模块方法映射
        """
        return {
            "recognize_media": self.recognize_media,
            "async_recognize_media": self.async_recognize_media,
        }

    @staticmethod
    def get_media_source() -> List[Dict[str, Any]]:
        """
        返回咪咕视频媒体数据源声明

        :return List: 媒体数据源声明列表
        """
        return [
            {
                "name": "咪咕视频",
                "media_source": MediaSource.MiguVideo,
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
            media_id = str(item.get("pID") or "")
            title = item.get("name")
            if not media_id or not title:
                continue
            identities[media_id] = {
                "title": title,
                "year": str(item.get("year") or "").strip() or None,
            }
        self.save_data(self._identity_cache_key, dict(list(identities.items())[-2000:]))

    @staticmethod
    def _fetch_migu_media(media_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = RequestUtils(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Referer": "https://www.miguvideo.com/",
                },
                timeout=8,
            ).get_res(
                f"https://program-sc.miguvideo.com/program/v4/cont/content-info/{media_id}/1"
            )
            if response is None or not response.ok:
                return None
            media = (response.json().get("body") or {}).get("data") or {}
            if not media.get("name"):
                return None
            return {
                "title": media.get("name"),
                "year": str(media.get("year") or "").strip() or None,
                "overview": media.get("detail"),
            }
        except Exception as err:
            logger.warning(f"咪咕视频媒体详情查询失败：{media_id} - {err}")
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
        通过咪咕视频节目 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 咪咕视频节目 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower() not in {"migu", "migudiscover"}
            or not media_id
        ):
            return None
        identities = self.get_data(self._identity_cache_key) or {}
        source_media = (
            identities.get(str(media_id)) or self._fetch_migu_media(str(media_id)) or {}
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
        mediainfo.media_source = MediaSource.MiguVideo
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
        异步通过咪咕视频节目 ID 识别媒体信息

        :param meta (Any): 已知媒体元数据
        :param mtype (MediaType): 媒体类型
        :param media_source (MediaSource): 媒体来源
        :param media_id (str): 咪咕视频节目 ID
        :param episode_group (str): 剧集组
        :param cache (bool): 是否使用 MoviePilot 识别缓存
        :param kwargs (Any): 兼容 MoviePilot 模块参数

        :return Any: 识别成功返回媒体信息，否则返回 None
        """
        if (
            str(media_source or "").lower() not in {"migu", "migudiscover"}
            or not media_id
        ):
            return None
        identities = await self.async_get_data(self._identity_cache_key) or {}
        source_media = (
            identities.get(str(media_id))
            or await asyncio.to_thread(self._fetch_migu_media, str(media_id))
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
        mediainfo.media_source = MediaSource.MiguVideo
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
                "path": "/migu_discover",
                "endpoint": self.migu_discover,
                "methods": ["GET"],
                "summary": "咪咕视频探索数据源",
                "description": "获取咪咕视频探索数据",
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

    @cached(region="migu_discover", ttl=1800, skip_none=True)
    def __request(self, page_num: int, page_size: int, **kwargs) -> List[Dict]:
        """
        请求 咪咕视频 API
        """
        api_url = self._base_api
        params = {
            "pageStart": str(page_num),
            "pageNum": str(page_size),
            "copyrightTerminal": 3,
        }
        if kwargs:
            params.update(kwargs)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.miguvideo.com/",
        }
        res = RequestUtils(headers=headers).get_res(
            api_url,
            params=params,
        )
        if res is None:
            raise ConnectionError("无法连接咪咕视频，请检查网络连接！")
        if not res.ok:
            raise ValueError(f"请求咪咕视频 API失败：{res.text}")
        return res.json().get("body").get("data")

    def migu_discover(
        self,
        mtype: str = "电视剧",
        mediaType: str = None,
        mediaArea: str = None,
        mediaYear: str = None,
        rankingType: str = None,
        payType: str = None,
        gender: str = None,
        mediaAge: str = None,
        page: int = 1,
        count: int = 21,
    ) -> Response[List[MediaInfo]]:
        """
        获取咪咕视频探索数据

        :return Response: 媒体信息响应
        """

        def __movie_to_media(movie_info: dict) -> MediaInfo:
            """
            电影数据转换为MediaInfo
            """
            year = str(movie_info.get("year") or "").strip() or None
            first_air_date = None
            if movie_info.get("publishTime"):
                first_air_date = movie_info.get("publishTime")
            return MediaInfo(
                type=MediaType.MOVIE,
                media_source=MediaSource.MiguVideo,
                title=movie_info.get("name"),
                year=year,
                media_id=str(movie_info.get("pID")),
                poster_path=movie_info.get("h5pics")
                .get("highResolutionV")
                .replace("http://wapx.cmvideo.cn:8080", "https://wapx.cmvideo.cn"),
                vote_average=movie_info.get("score"),
                first_air_date=first_air_date,
            )

        def __series_to_media(series_info: dict) -> MediaInfo:
            """
            电视剧数据转换为MediaInfo
            """
            year = str(series_info.get("year") or "").strip() or None
            first_air_date = None
            if series_info.get("publishTime"):
                first_air_date = series_info.get("publishTime")
            return MediaInfo(
                type=MediaType.TV,
                media_source=MediaSource.MiguVideo,
                title=series_info.get("name"),
                year=year,
                media_id=str(series_info.get("pID")),
                release_date=series_info.get("publishTime"),
                poster_path=series_info.get("h5pics")
                .get("highResolutionV")
                .replace("http://wapx.cmvideo.cn:8080", "https://wapx.cmvideo.cn"),
                vote_average=series_info.get("score"),
                first_air_date=first_air_date,
            )

        try:
            if mtype == "电视剧":
                media_info = [
                    "1002581,1003861,1003863,1003866,1002601,1004761,1004121,1004641,1005521,1005261",
                    "1001",
                    "",
                    "",
                ]
            elif mtype == "电影":
                media_info = [
                    "1002581,1002601,1003862,1003864,1003866,1004121,1003861,1004761,1004641",
                    "1000",
                    "全片",
                    "2",
                ]
            elif mtype == "综艺":
                media_info = [
                    "1002581,1002601",
                    "1005",
                    "连载",
                    "2",
                ]
            elif mtype == "纪实":
                media_info = [
                    "1002581,1002601",
                    "1002",
                    "连载",
                    "2",
                ]
            elif mtype == "动漫":
                media_info = [
                    "1002581,1003861,1003863,1003866,1002601,1004761,1004121,1004641",
                    "1007",
                    "连载",
                    "",
                ]
            else:
                media_info = [
                    "1002581,1002601",
                    "601382",
                    "",
                    "",
                ]
            params = {
                "page_num": page,
                "page_size": count,
                "packId": str(media_info[0]),
                "contDisplayType": str(media_info[1]),
            }
            if media_info[2]:
                params.update({"mediaShape": str(media_info[2])})
            if media_info[3]:
                params.update({"order": str(media_info[3])})
            if mediaType:
                params.update({"mediaType": mediaType})
            if mediaArea:
                params.update({"mediaArea": mediaArea})
            if mediaYear:
                params.update({"mediaYear": mediaYear})
            if rankingType:
                params.update({"rankingType": rankingType})
            if payType:
                params.update({"payType": payType})
            if gender:
                params.update({"gender": gender})
            if mediaAge:
                params.update({"mediaAge": mediaAge})
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
    def migu_filter_ui() -> List[dict]:
        """
        咪咕视频过滤参数UI配置
        """
        mtype = [
            "电视剧",
            "电影",
            "综艺",
            "纪实",
            "动漫",
            "少儿",
        ]
        mtype_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in mtype
        ]

        rankingType = {
            "0": "最热",
            "1": "最新",
            "2": "好评",
        }
        rankingType_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": value,
            }
            for key, value in rankingType.items()
        ]

        gender = {
            "0": "男",
            "1": "女",
        }
        gender_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": key},
                "text": value,
            }
            for key, value in gender.items()
        ]

        mediaAge = [
            "0~3岁",
            "4~6岁",
            "7~12岁",
        ]
        mediaAge_ui = [
            {
                "component": "VChip",
                "props": {"filter": True, "tile": True, "value": value},
                "text": value,
            }
            for value in mediaAge
        ]

        mediaType = [
            [
                "爱情",
                "古装",
                "战争",
                "悬疑",
                "青春",
                "都市",
                "言情",
                "玄幻",
                "警匪",
                "谍战",
                "喜剧",
                "家庭",
                "军旅",
                "武侠",
                "职场",
                "奇幻",
                "科幻",
                "偶像",
                "历史",
                "年代",
                "农村",
                "剧情",
                "微短剧",
            ],
            [
                "动作",
                "喜剧",
                "惊悚",
                "谍战",
                "悬疑",
                "犯罪",
                "战争",
                "爱情",
                "历史",
                "动画",
                "科幻",
                "奇幻",
                "冒险",
                "灾难",
                "恐怖",
                "剧情",
                "西部",
                "传记",
            ],
            [
                "真人秀",
                "搞笑",
                "情感",
                "音乐",
                "游戏",
                "晚会",
                "生活",
                "职场",
                "美食",
                "文化",
                "旅行",
                "益智",
                "亲子",
            ],
            [
                "军事",
                "社会",
                "自然",
                "历史",
                "刑侦",
                "科技",
                "人物",
                "艺术",
                "动物",
                "文物",
                "美食",
                "旅游",
                "古迹",
                "探秘",
                "其他",
            ],
            [
                "热血",
                "奇幻",
                "青春",
                "爱情",
                "搞笑",
                "悬疑",
                "竞技",
            ],
            [
                "动画",
                "故事",
                "儿歌",
            ],
        ]
        mediaType_list = []
        for i in range(len(mtype)):
            mediaType_list.append(
                [
                    {
                        "component": "VChip",
                        "props": {"filter": True, "tile": True, "value": value},
                        "text": value,
                    }
                    for value in mediaType[i]
                ]
            )
        mediaType_ui = (
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == '" + mtype[i] + "'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "类别"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "mediaType"},
                        "content": mediaType_list[i],
                    },
                ],
            }
            for i in range(len(mtype))
        )

        mediaArea = [
            [
                "内地",
                "香港地区",
                "日本",
                "美国",
                "英国",
                "韩国",
                "泰国",
                "台湾地区",
            ],
            [
                "内地",
                "中国香港",
                "中国台湾",
                "美国",
                "英国",
                "日本",
                "韩国",
                "泰国",
                "印度",
                "德国",
                "巴西",
                "埃及",
                "意大利",
                "俄罗斯",
                "捷克",
                "西班牙",
                "法国",
                "澳大利亚",
                "新加坡",
                "新西兰",
                "瑞典",
                "爱尔兰",
                "丹麦",
                "土耳其",
                "其他",
            ],
            ["内地"],
            [
                "中国",
                "美国",
                "英国",
                "其他",
            ],
            ["内地", "日本"],
            [
                "内地",
                "韩国",
                "日本",
                "爱尔兰",
                "英国",
                "澳大利亚",
                "美国",
                "巴西",
                "俄罗斯",
                "法国",
                "加拿大",
                "西班牙",
                "意大利",
            ],
        ]
        mediaArea_list = []
        for i in range(len(mtype)):
            mediaArea_list.append(
                [
                    {
                        "component": "VChip",
                        "props": {"filter": True, "tile": True, "value": value},
                        "text": value,
                    }
                    for value in mediaArea[i]
                ]
            )
        mediaArea_ui = (
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == '" + mtype[i] + "'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "地区"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "mediaArea"},
                        "content": mediaArea_list[i],
                    },
                ],
            }
            for i in range(len(mtype))
        )

        mediaYear = [
            [
                "2024",
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
                "2011",
                "2010",
                "2009",
                "2008",
                "2007",
                "2006",
                "2005",
                "2004",
                "2003",
                "2002",
                "2001",
                "2000",
                "90年代",
                "80年代",
            ],
            [
                "2024",
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
                "2011",
                "2010",
                "2009",
                "2008",
                "2007",
                "2006",
                "2005",
                "2004",
                "2003",
                "更早",
            ],
            [
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
            ],
            [
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
                "2011",
                "2010",
                "2009",
                "2008",
                "2007",
                "2006",
                "2005",
                "2004",
                "2003",
            ],
            [
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
                "更早",
            ],
            [
                "2023",
                "2022",
                "2021",
                "2020",
                "2019",
                "2018",
                "2017",
                "2016",
                "2015",
                "2014",
                "2013",
                "2012",
                "2011",
                "2010",
                "2009",
                "2008",
                "2007",
                "2006",
                "2005",
                "2004",
                "2003",
                "2002",
                "2001",
                "90年代",
                "80年代",
                "更早",
            ],
        ]
        mediaYear_list = []
        for i in range(len(mtype)):
            mediaYear_list.append(
                [
                    {
                        "component": "VChip",
                        "props": {"filter": True, "tile": True, "value": value},
                        "text": value,
                    }
                    for value in mediaYear[i]
                ]
            )
        mediaYear_ui = (
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == '" + mtype[i] + "'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "年代"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "mediaYear"},
                        "content": mediaYear_list[i],
                    },
                ],
            }
            for i in range(len(mtype))
        )

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
            {
                "component": "div",
                "props": {"class": "flex justify-start items-center"},
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "排序类型"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "rankingType"},
                        "content": rankingType_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == '少儿'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "性别"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "channel"},
                        "content": gender_ui,
                    },
                ],
            },
            {
                "component": "div",
                "props": {
                    "class": "flex justify-start items-center",
                    "show": "{{mtype == '少儿'}}",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "mr-5"},
                        "content": [{"component": "VLabel", "text": "年龄"}],
                    },
                    {
                        "component": "VChipGroup",
                        "props": {"model": "channel"},
                        "content": mediaAge_ui,
                    },
                ],
            },
        ]
        for i in mediaType_ui:
            ui.insert(-3, i)
        for i in mediaArea_ui:
            ui.insert(-3, i)
        for i in mediaYear_ui:
            ui.insert(-3, i)

        return ui

    @eventmanager.register(ChainEventType.DiscoverSource)
    def discover_source(self, event: Event):
        """
        监听识别事件，使用ChatGPT辅助识别名称
        """
        if not self._enabled:
            return
        event_data: DiscoverSourceEventData = event.event_data
        migu_source = DiscoverMediaSource(
            name="咪咕视频",
            media_source=MediaSource.MiguVideo,
            mediaid_prefix="migu",
            api_path=f"plugin/MiGuDiscover/migu_discover?apikey={settings.API_TOKEN}",
            filter_params={
                "mtype": "电视剧",
                "mediaType": None,
                "mediaArea": None,
                "mediaYear": None,
                "rankingType": None,
                "payType": None,
                "gender": None,
                "mediaAge": None,
            },
            filter_ui=self.migu_filter_ui(),
            depends={
                "mediaType": ["mtype"],
                "mediaArea": ["mtype"],
                "mediaYear": ["mtype"],
                "rankingType": ["mtype"],
                "payType": ["mtype"],
                "gender": ["mtype"],
                "mediaAge": ["mtype"],
            },
        )
        if not event_data.extra_sources:
            event_data.extra_sources = [migu_source]
        else:
            event_data.extra_sources.append(migu_source)

    def stop_service(self):
        """
        退出插件
        """
        pass
