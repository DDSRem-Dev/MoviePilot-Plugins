import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler

from app import schemas
from app.chain.storage import StorageChain
from app.chain.transfer import TransferChain
from app.db.models.transferhistory import TransferHistory
from app.db.oper.downloadhistory import DownloadHistoryOper
from app.db.oper.transferhistory import TransferHistoryOper
from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.network import RequestUtils
from app.sdk.services import DownloaderHelper, MediaServerHelper
from app.sdk.utilities import SystemUtils
from app.schemas.types import (
    EventType,
    MediaImageType,
    MediaSource,
    MediaType,
    NotificationType,
)


class SaMediaSyncDel(_PluginBase):
    """
    神医媒体文件同步删除插件：监听 Emby 删除事件，同步删除转移记录、源文件、下载任务
    """

    # 插件名称
    plugin_name = "神医媒体文件同步删除"
    # 插件描述
    plugin_desc = "通过神医插件通知同步删除历史记录、源文件和下载任务。"
    # 插件图标
    plugin_icon = "mediasyncdel.png"
    # 插件版本
    plugin_version = "3.0.0"
    # 插件作者
    plugin_author = "DDSRem,thsrite"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "samediasyncdel_"
    # 加载顺序
    plugin_order = 9
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled = False
    _notify = False
    _del_source = False
    _del_history = False
    _local_library_path = None
    _p115_library_path = None
    _p115_force_delete_files = False
    _p123_library_path = None
    _p123_force_delete_files = False
    _transferchain = None
    _downloader_helper = None
    _transferhis = None
    _downloadhis = None
    _storagechain = None
    _mediaserver_helper = None
    _default_downloader = None
    _mediaserver = None
    _mediaservers = None
    _emby_host = None
    _emby_apikey = None
    _emby_user = None

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化插件：读取配置，获取下载器和媒体服务器信息

        :param config: 插件配置字典
        """
        self._transferchain = TransferChain()
        self._downloader_helper = DownloaderHelper()
        self._transferhis = TransferHistoryOper()
        self._downloadhis = DownloadHistoryOper()
        self._storagechain = StorageChain()
        self._mediaserver_helper = MediaServerHelper()
        self._mediaserver = None

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._del_source = config.get("del_source")
            self._del_history = config.get("del_history")
            self._local_library_path = config.get("local_library_path")
            self._p115_library_path = config.get("p115_library_path")
            self._p115_force_delete_files = config.get("p115_force_delete_files")
            self._p123_library_path = config.get("p123_library_path")
            self._p123_force_delete_files = config.get("p123_force_delete_files")
            self._mediaservers = config.get("mediaservers") or []

            # 获取媒体服务器
            if self._mediaservers:
                self._mediaserver = [self._mediaservers[0]]

            # 获取默认下载器
            downloader_services = self._downloader_helper.get_services()
            for downloader_name, downloader_info in downloader_services.items():
                if downloader_info.config.default:
                    self._default_downloader = downloader_name

            # 清理插件历史
            if self._del_history:
                self.del_data(key="history")

            self.update_config(
                {
                    "enabled": self._enabled,
                    "notify": self._notify,
                    "del_source": self._del_source,
                    "del_history": False,
                    "local_library_path": self._local_library_path,
                    "p115_library_path": self._p115_library_path,
                    "p115_force_delete_files": self._p115_force_delete_files,
                    "p123_library_path": self._p123_library_path,
                    "p123_force_delete_files": self._p123_force_delete_files,
                    "mediaservers": self._mediaserver,
                }
            )

        # 获取媒体服务信息
        if self._mediaserver:
            emby_servers = self._mediaserver_helper.get_services(
                name_filters=self._mediaserver, type_filter="emby"
            )

            for _, emby_server in emby_servers.items():
                self._emby_user = emby_server.instance.get_user()
                self._emby_apikey = emby_server.config.config.get("apikey")
                self._emby_host = emby_server.config.config.get("host")
                if not self._emby_host.endswith("/"):
                    self._emby_host += "/"
                if not self._emby_host.startswith("http"):
                    self._emby_host = "http://" + self._emby_host

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表

        :return: delete_history 删除订阅历史记录端点
        """
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除订阅历史记录",
            }
        ]

    def delete_history(self, key: str, apikey: str) -> schemas.Response:
        """
        删除历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        historys = self.get_data("history")
        if not historys:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        historys = [h for h in historys if h.get("unique") != key]
        self.save_data("history", historys)
        return schemas.Response(success=True, message="删除成功")

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """

        local_media_tab = [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model": "local_library_path",
                                    "rows": "2",
                                    "label": "本地媒体库路径映射",
                                    "placeholder": "媒体服务器路径#MoviePilot路径（一行一个）",
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "div",
                        "text": "关于路径映射（转移后文件路径）：",
                    },
                    {
                        "component": "div",
                        "text": "emby目录：/data/A.mp4",
                    },
                    {
                        "component": "div",
                        "text": "moviepilot目录：/mnt/link/A.mp4",
                    },
                    {
                        "component": "div",
                        "text": "路径映射填：/data#/mnt/link",
                    },
                    {
                        "component": "div",
                        "text": "不正确配置会导致查询不到转移记录！",
                    },
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                    "text": "注意：不同的存储模块不能配置同一个媒体路径，否则会导致匹配失败或误删除！",
                },
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                    "text": "注意：本地同步删除功能需要使用神医助手PRO且版本在v3.0.0.3及以上或神医助手社区版且版本在v2.0.0.27及以上！",
                },
            },
        ]

        p115_media_tab = [
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
                                    "model": "p115_force_delete_files",
                                    "label": "强制网盘删除",
                                    "hint": "MP不存在历史记录或无法获取TMDB ID时强制删除网盘文件",
                                },
                            }
                        ],
                    },
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model": "p115_library_path",
                                    "rows": "2",
                                    "label": "115网盘媒体库路径映射",
                                    "placeholder": "媒体服务器STRM路径#MoviePilot路径#115网盘路径（一行一个）",
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "div",
                        "text": "关于路径映射（转移后文件路径）：",
                    },
                    {
                        "component": "div",
                        "text": "emby目录：/media/strm",
                    },
                    {
                        "component": "div",
                        "text": "moviepilot目录：/mnt/strm",
                    },
                    {
                        "component": "div",
                        "text": "115网盘媒体库目录：/影视",
                    },
                    {
                        "component": "div",
                        "text": "路径映射填：/media/strm#/mnt/strm#/影视",
                    },
                    {
                        "component": "div",
                        "text": "不正确配置会导致查询不到转移记录！",
                    },
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                    "text": "注意：不同的存储模块不能配置同一个媒体路径，否则会导致匹配失败或误删除！",
                },
            },
        ]

        p123_media_tab = [
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
                                    "model": "p123_force_delete_files",
                                    "label": "强制网盘删除",
                                    "hint": "MP不存在历史记录或无法获取TMDB ID时强制删除网盘文件",
                                },
                            }
                        ],
                    },
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model": "p123_library_path",
                                    "rows": "2",
                                    "label": "123云盘媒体库路径映射",
                                    "placeholder": "媒体服务器STRM路径#MoviePilot路径#115网盘路径（一行一个）",
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "div",
                        "text": "关于路径映射（转移后文件路径）：",
                    },
                    {
                        "component": "div",
                        "text": "emby目录：/media/strm",
                    },
                    {
                        "component": "div",
                        "text": "moviepilot目录：/mnt/strm",
                    },
                    {
                        "component": "div",
                        "text": "123云盘媒体库目录：/影视",
                    },
                    {
                        "component": "div",
                        "text": "路径映射填：/media/strm#/mnt/strm#/影视",
                    },
                    {
                        "component": "div",
                        "text": "不正确配置会导致查询不到转移记录！",
                    },
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {
                            "cols": 12,
                        },
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "warning",
                                    "variant": "tonal",
                                    "text": "注意：不同的存储模块不能配置同一个媒体路径，否则会导致匹配失败或误删除！",
                                },
                            },
                        ],
                    }
                ],
            },
        ]

        return [
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "mb-3"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "d-flex align-center"},
                        "content": [
                            {
                                "component": "VIcon",
                                "props": {
                                    "icon": "mdi-cog",
                                    "color": "primary",
                                    "class": "mr-2",
                                },
                            },
                            {"component": "span", "text": "基础设置"},
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 2},
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "enabled",
                                                    "label": "启用插件",
                                                },
                                            }
                                        ],
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 2},
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "notify",
                                                    "label": "发送通知",
                                                },
                                            }
                                        ],
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 2},
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "del_source",
                                                    "label": "删除源文件",
                                                },
                                            }
                                        ],
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 2},
                                        "content": [
                                            {
                                                "component": "VSwitch",
                                                "props": {
                                                    "model": "del_history",
                                                    "label": "删除历史",
                                                },
                                            }
                                        ],
                                    },
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12, "md": 4},
                                        "content": [
                                            {
                                                "component": "VSelect",
                                                "props": {
                                                    "multiple": True,
                                                    "chips": True,
                                                    "clearable": True,
                                                    "model": "mediaservers",
                                                    "label": "媒体服务器",
                                                    "items": [
                                                        {
                                                            "title": config.name,
                                                            "value": config.name,
                                                        }
                                                        for config in self._mediaserver_helper.get_configs().values()
                                                        if config.type == "emby"
                                                    ],
                                                },
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {
                                            "cols": 12,
                                        },
                                        "content": [
                                            {
                                                "component": "VAlert",
                                                "props": {
                                                    "type": "info",
                                                    "variant": "tonal",
                                                    "text": "只能配置一个Emby媒体服务器，配置多个默认查寻第一个媒体服务器信息",
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                "component": "VCard",
                "props": {"variant": "outlined"},
                "content": [
                    {
                        "component": "VTabs",
                        "props": {"model": "tab", "grow": True, "color": "primary"},
                        "content": [
                            {
                                "component": "VTab",
                                "props": {"value": "tab-local"},
                                "content": [
                                    {"component": "span", "text": "本地媒体配置"},
                                ],
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "tab-p115"},
                                "content": [
                                    {"component": "span", "text": "115网盘媒体配置"},
                                ],
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "tab-p123"},
                                "content": [
                                    {"component": "span", "text": "123云盘媒体配置"},
                                ],
                            },
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VWindow",
                        "props": {"model": "tab"},
                        "content": [
                            {
                                "component": "VWindowItem",
                                "props": {"value": "tab-local"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "content": local_media_tab,
                                    }
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "tab-p115"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "content": p115_media_tab,
                                    }
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "tab-p123"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "content": p123_media_tab,
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "notify": True,
            "del_source": False,
            "del_history": False,
            "local_library_path": "",
            "p115_library_path": "",
            "p115_force_delete_files": False,
            "p123_library_path": "",
            "p123_force_delete_files": False,
            "mediaservers": [],
            "tab": "local_media_tab",
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        historys = self.get_data("history")
        if not historys:
            return [
                {
                    "component": "div",
                    "text": "暂无数据",
                    "props": {
                        "class": "text-center",
                    },
                }
            ]
        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get("del_time"), reverse=True)
        # 拼装页面
        contents = []
        for history in historys:
            htype = history.get("type")
            title = history.get("title")
            unique = history.get("unique")
            year = history.get("year")
            season = history.get("season")
            episode = history.get("episode")
            image = history.get("image")
            del_time = history.get("del_time")

            if season:
                sub_contents = [
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"类型：{htype}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"标题：{title}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"年份：{year}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"季：{season}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"集：{episode}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"时间：{del_time}",
                    },
                ]
            else:
                sub_contents = [
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"类型：{htype}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"标题：{title}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"年份：{year}",
                    },
                    {
                        "component": "VCardText",
                        "props": {"class": "pa-0 px-2"},
                        "text": f"时间：{del_time}",
                    },
                ]

            contents.append(
                {
                    "component": "VCard",
                    "content": [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                "innerClass": "absolute top-0 right-0",
                            },
                            "events": {
                                "click": {
                                    "api": "plugin/SaMediaSyncDel/delete_history",
                                    "method": "get",
                                    "params": {
                                        "key": unique,
                                        "apikey": settings.API_TOKEN,
                                    },
                                }
                            },
                        },
                        {
                            "component": "div",
                            "props": {
                                "class": "d-flex justify-space-start flex-nowrap flex-row",
                            },
                            "content": [
                                {
                                    "component": "div",
                                    "content": [
                                        {
                                            "component": "VImg",
                                            "props": {
                                                "src": image,
                                                "height": 120,
                                                "width": 80,
                                                "aspect-ratio": "2/3",
                                                "class": "object-cover shadow ring-gray-500",
                                                "cover": True,
                                            },
                                        }
                                    ],
                                },
                                {"component": "div", "content": sub_contents},
                            ],
                        },
                    ],
                }
            )

        return [
            {
                "component": "div",
                "props": {
                    "class": "grid gap-3 grid-info-card",
                },
                "content": contents,
            }
        ]

    def has_prefix(self, full_path: str, prefix_path: str) -> bool:
        """
        判断路径是否包含
        """
        full = Path(full_path).parts
        prefix = Path(prefix_path).parts

        if len(prefix) > len(full):
            return False

        return full[: len(prefix)] == prefix

    def __get_local_media_path(self, media_path):
        """
        获取本地媒体目录路径
        """
        media_paths = self._local_library_path.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 1)
            if self.has_prefix(media_path, parts[0]):
                return True, parts
        return False, None

    def __get_p115_media_path(self, media_path):
        """
        获取115网盘媒体目录路径
        """
        media_paths = self._p115_library_path.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 2)
            if self.has_prefix(media_path, parts[0]):
                return True, parts
        return False, None

    def __get_p123_media_path(self, media_path):
        """
        获取123云盘媒体目录路径
        """
        media_paths = self._p123_library_path.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 2)
            if self.has_prefix(media_path, parts[0]):
                return True, parts
        return False, None

    @eventmanager.register(EventType.WebhookMessage)
    def sync_del_by_plugin(self, event: Event) -> None:
        """
        emby删除媒体库同步删除历史记录
        """
        if not self._enabled:
            return

        media_suffix = None
        media_storage = None

        event_data = event.event_data
        event_type = event_data.event

        # 神医助手深度删除标识
        if not event_type or str(event_type) != "deep.delete":
            return

        logger.debug(event.event_data)

        # 媒体类型
        media_type = event_data.item_type
        # 媒体名称
        media_name = event_data.item_name
        # 媒体路径
        media_path = event_data.item_path
        media_source = event_data.media_source
        media_id = event_data.media_id
        if media_source:
            media_source = MediaSource(media_source)
        # 季数
        season_num = event_data.season_id
        # 集数
        episode_num = event_data.episode_id

        # 执行删除逻辑
        if not media_path:
            return

        # 对于 Emby 新版本 API 单独处理，兼容季删除
        if event_data.json_object.get("Item", {}).get("Type", None) == "Season":
            if not season_num and episode_num:
                season_num = episode_num
                episode_num = None

        # 匹配媒体存储模块
        if (
            self._local_library_path
            or self._p115_library_path
            or self._p123_library_path
        ):
            if self._local_library_path:
                status, _ = self.__get_local_media_path(media_path)
                if status:
                    media_storage = "local"

            if not media_storage and self._p115_library_path:
                status, _ = self.__get_p115_media_path(media_path)
                if status:
                    media_storage = "p115"

            if not media_storage and self._p123_library_path:
                status, _ = self.__get_p123_media_path(media_path)
                if status:
                    media_storage = "p123"

            if not media_storage:
                logger.error(f"{media_name} 同步删除失败，未识别到储存类型")
                return
        else:
            return

        # 对于网盘文件需要获取媒体后缀名
        if media_storage == "p115" or media_storage == "p123":
            if Path(media_path).suffix:
                media_suffix = event_data.json_object.get("Item", {}).get(
                    "Container", None
                )
                if not media_suffix:
                    if media_storage == "p115":
                        media_suffix = self.__get_p115_media_suffix(media_path)
                    else:
                        media_suffix = self.__get_p123_media_suffix(media_path)
                    if not media_suffix:
                        logger.error(f"{media_name} 同步删除失败，未识别媒体后缀名")
                        return
            else:
                logger.debug(f"{media_name} 跳过识别媒体后缀名")

        if (episode_num or season_num) and not media_id:
            media_id = self.__get_series_media_id(
                event_data.json_object["Item"]["SeriesId"]
            )
            if media_id:
                media_source = MediaSource.TMDB

        if not media_source or not media_id:
            if not (media_storage == "p115" and self._p115_force_delete_files):
                if not (media_storage == "p123" and self._p123_force_delete_files):
                    logger.error(
                        f"{media_name} 同步删除失败，未获取到媒体身份，请检查媒体库媒体是否刮削"
                    )
                    return

        self.__sync_del(
            media_type=media_type,
            media_name=media_name,
            media_path=media_path,
            media_source=media_source,
            media_id=media_id,
            season_num=season_num,
            episode_num=episode_num,
            media_storage=media_storage,
            media_suffix=media_suffix,
        )

    def __sync_del(
        self,
        media_type: str,
        media_name: str,
        media_path: str,
        media_source: Optional[MediaSource],
        media_id: Optional[str],
        season_num: str,
        episode_num: str,
        media_storage: str,
        media_suffix: str,
    ):
        if not media_type:
            logger.error(
                f"{media_name} 同步删除失败，未获取到媒体类型，请检查媒体是否刮削"
            )
            return

        if media_storage == "local":
            # 处理路径映射
            if self._local_library_path:
                _, sub_paths = self.__get_local_media_path(media_path)
                media_path = media_path.replace(sub_paths[0], sub_paths[1]).replace(
                    "\\", "/"
                )

            # 兼容重新整理的场景
            if Path(media_path).exists():
                logger.warn(f"转移路径 {media_path} 未被删除或重新生成，跳过处理")
                return

            # 查询转移记录
            msg, transfer_history = self.__get_transfer_his(
                media_type=media_type,
                media_name=media_name,
                media_path=media_path,
                media_source=media_source,
                media_id=media_id,
                season_num=season_num,
                episode_num=episode_num,
            )

            logger.info(f"正在同步删除{msg}")

            if not transfer_history:
                logger.warn(
                    f"{media_type} {media_name} 未获取到可删除数据，请检查路径映射是否配置错误，请检查media_id获取是否正确"
                )
                return

            logger.info(f"获取到 {len(transfer_history)} 条转移记录，开始同步删除")
            # 开始删除
            year = None
            del_torrent_hashs = []
            stop_torrent_hashs = []
            error_cnt = 0
            image = "https://emby.media/notificationicon.png"
            for transferhis in transfer_history:
                title = transferhis.title
                if title not in media_name:
                    logger.warn(
                        f"当前转移记录 {transferhis.id} {title} {transferhis.media_id} 与删除媒体{media_name}不符，防误删，暂不自动删除"
                    )
                    continue
                image = transferhis.image or image
                year = transferhis.year

                # 0、删除转移记录
                self._transferhis.delete(transferhis.id)

                # 删除种子任务
                if self._del_source:
                    # 1、直接删除源文件
                    # 当源文件是本地文件且整理方式不是移动才进行源文件删除
                    if (
                        transferhis.src
                        and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT
                        and transferhis.src_storage == "local"
                        and transferhis.mode != "move"
                    ):
                        # 删除硬链接文件和源文件
                        if Path(transferhis.dest).exists():
                            Path(transferhis.dest).unlink(missing_ok=True)
                            self.__remove_parent_dir(Path(transferhis.dest))
                        if Path(transferhis.src).exists():
                            logger.info(f"源文件 {transferhis.src} 开始删除")
                            Path(transferhis.src).unlink(missing_ok=True)
                            logger.info(f"源文件 {transferhis.src} 已删除")
                            self.__remove_parent_dir(Path(transferhis.src))

                        if transferhis.download_hash:
                            try:
                                # 2、判断种子是否被删除完
                                delete_flag, success_flag, handle_torrent_hashs = (
                                    self.handle_torrent(
                                        type=transferhis.type,
                                        src=transferhis.src,
                                        torrent_hash=transferhis.download_hash,
                                    )
                                )
                                if not success_flag:
                                    error_cnt += 1
                                else:
                                    if delete_flag:
                                        del_torrent_hashs += handle_torrent_hashs
                                    else:
                                        stop_torrent_hashs += handle_torrent_hashs
                            except Exception as e:
                                logger.error("删除种子失败：%s" % str(e))

        elif media_storage == "p115":
            mp_media_path: Path
            if self._p115_library_path:
                _, sub_paths = self.__get_p115_media_path(media_path)
                mp_media_path = media_path.replace(sub_paths[0], sub_paths[1]).replace(
                    "\\", "/"
                )
                media_path = media_path.replace(sub_paths[0], sub_paths[2]).replace(
                    "\\", "/"
                )

            if Path(media_path).suffix:
                # 自动替换媒体文件后缀名称为真实名称
                media_path = str(
                    Path(media_path).parent
                    / str(Path(media_path).stem + "." + media_suffix)
                )
                # 这里做一次大小写转换，避免资源后缀名为全大写情况
                if media_suffix.isupper():
                    media_suffix = media_suffix.lower()
                elif media_suffix.islower():
                    media_suffix = media_suffix.upper()
                media_path_2 = str(
                    Path(media_path).parent
                    / str(Path(media_path).stem + "." + media_suffix)
                )
            else:
                media_path_2 = media_path

            # 兼容重新整理的场景
            if Path(mp_media_path).exists():
                logger.warn(f"转移路径 {media_path} 未被删除或重新生成，跳过处理")
                return

            # 查询转移记录
            msg, transfer_history = self.__get_transfer_his(
                media_type=media_type,
                media_name=media_name,
                media_path=media_path,
                media_source=media_source,
                media_id=media_id,
                season_num=season_num,
                episode_num=episode_num,
            )

            # 如果没有msg使用媒体名称替代
            if not msg:
                msg = media_name

            logger.info(f"正在同步删除 {msg}")

            if not transfer_history:
                msg, transfer_history = self.__get_transfer_his(
                    media_type=media_type,
                    media_name=media_name,
                    media_path=media_path_2,
                    media_source=media_source,
                    media_id=media_id,
                    season_num=season_num,
                    episode_num=episode_num,
                )
                # 如果没有msg使用媒体名称替代
                if not msg:
                    msg = media_name
                if not transfer_history:
                    if self._p115_force_delete_files:
                        logger.warn(f"{media_name} 强制删除网盘媒体文件")
                        self.__delete_p115_files(
                            file_path=media_path,
                            media_name=media_name,
                        )
                    else:
                        logger.warn(
                            f"{media_type} {media_name} 未获取到可删除数据，请检查路径映射是否配置错误，请检查media_id获取是否正确"
                        )
                        return
                else:
                    media_path = media_path_2

            year = None
            del_torrent_hashs = []
            stop_torrent_hashs = []
            error_cnt = 0
            image = "https://emby.media/notificationicon.png"
            if transfer_history:
                logger.info(f"获取到 {len(transfer_history)} 条转移记录，开始同步删除")
                # 开始删除
                for transferhis in transfer_history:
                    title = transferhis.title
                    if title not in media_name:
                        logger.warn(
                            f"当前转移记录 {transferhis.id} {title} {transferhis.media_id} 与删除媒体 {media_name} 不符，防误删，暂不自动删除"
                        )
                        continue
                    image = transferhis.image or image
                    year = transferhis.year

                    # 0、删除转移记录
                    self._transferhis.delete(transferhis.id)

                    # 1、删除网盘文件
                    self.__delete_p115_files(
                        file_path=transferhis.dest,
                        media_name=media_name,
                    )

                    # 删除种子任务
                    if self._del_source:
                        # 1、直接删除源文件
                        # 当源文件是本地文件且整理方式不是移动才进行源文件删除
                        if (
                            transferhis.src
                            and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT
                            and transferhis.src_storage == "local"
                            and transferhis.mode != "move"
                        ):
                            # 删除源文件
                            if Path(transferhis.src).exists():
                                logger.info(f"源文件 {transferhis.src} 开始删除")
                                Path(transferhis.src).unlink(missing_ok=True)
                                logger.info(f"源文件 {transferhis.src} 已删除")
                                self.__remove_parent_dir(Path(transferhis.src))

                            if transferhis.download_hash:
                                try:
                                    # 2、判断种子是否被删除完
                                    delete_flag, success_flag, handle_torrent_hashs = (
                                        self.handle_torrent(
                                            type=transferhis.type,
                                            src=transferhis.src,
                                            torrent_hash=transferhis.download_hash,
                                        )
                                    )
                                    if not success_flag:
                                        error_cnt += 1
                                    else:
                                        if delete_flag:
                                            del_torrent_hashs += handle_torrent_hashs
                                        else:
                                            stop_torrent_hashs += handle_torrent_hashs
                                except Exception as e:
                                    logger.error("删除种子失败：%s" % str(e))

        else:
            mp_media_path: Path
            if self._p123_library_path:
                _, sub_paths = self.__get_p123_media_path(media_path)
                mp_media_path = media_path.replace(sub_paths[0], sub_paths[1]).replace(
                    "\\", "/"
                )
                media_path = media_path.replace(sub_paths[0], sub_paths[2]).replace(
                    "\\", "/"
                )

            if Path(media_path).suffix:
                # 自动替换媒体文件后缀名称为真实名称
                media_path = str(
                    Path(media_path).parent
                    / str(Path(media_path).stem + "." + media_suffix)
                )
                # 这里做一次大小写转换，避免资源后缀名为全大写情况
                if media_suffix.isupper():
                    media_suffix = media_suffix.lower()
                elif media_suffix.islower():
                    media_suffix = media_suffix.upper()
                media_path_2 = str(
                    Path(media_path).parent
                    / str(Path(media_path).stem + "." + media_suffix)
                )
            else:
                media_path_2 = media_path

            # 兼容重新整理的场景
            if Path(mp_media_path).exists():
                logger.warn(f"转移路径 {media_path} 未被删除或重新生成，跳过处理")
                return

            # 查询转移记录
            msg, transfer_history = self.__get_transfer_his(
                media_type=media_type,
                media_name=media_name,
                media_path=media_path,
                media_source=media_source,
                media_id=media_id,
                season_num=season_num,
                episode_num=episode_num,
            )

            # 如果没有msg使用媒体名称替代
            if not msg:
                msg = media_name

            logger.info(f"正在同步删除 {msg}")

            if not transfer_history:
                msg, transfer_history = self.__get_transfer_his(
                    media_type=media_type,
                    media_name=media_name,
                    media_path=media_path_2,
                    media_source=media_source,
                    media_id=media_id,
                    season_num=season_num,
                    episode_num=episode_num,
                )
                # 如果没有msg使用媒体名称替代
                if not msg:
                    msg = media_name
                if not transfer_history:
                    if self._p123_force_delete_files:
                        logger.warn(f"{media_name} 强制删除网盘媒体文件")
                        self.__delete_p123_files(
                            file_path=media_path,
                            media_name=media_name,
                        )
                    else:
                        logger.warn(
                            f"{media_type} {media_name} 未获取到可删除数据，请检查路径映射是否配置错误，请检查media_id获取是否正确"
                        )
                        return
                else:
                    media_path = media_path_2

            year = None
            del_torrent_hashs = []
            stop_torrent_hashs = []
            error_cnt = 0
            image = "https://emby.media/notificationicon.png"
            if transfer_history:
                logger.info(f"获取到 {len(transfer_history)} 条转移记录，开始同步删除")
                # 开始删除
                for transferhis in transfer_history:
                    title = transferhis.title
                    if title not in media_name:
                        logger.warn(
                            f"当前转移记录 {transferhis.id} {title} {transferhis.media_id} 与删除媒体 {media_name} 不符，防误删，暂不自动删除"
                        )
                        continue
                    image = transferhis.image or image
                    year = transferhis.year

                    # 0、删除转移记录
                    self._transferhis.delete(transferhis.id)

                    # 1、删除网盘文件
                    self.__delete_p123_files(
                        file_path=transferhis.dest,
                        media_name=media_name,
                    )

                    # 删除种子任务
                    if self._del_source:
                        # 1、直接删除源文件
                        # 当源文件是本地文件且整理方式不是移动才进行源文件删除
                        if (
                            transferhis.src
                            and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT
                            and transferhis.src_storage == "local"
                            and transferhis.mode != "move"
                        ):
                            # 删除源文件
                            if Path(transferhis.src).exists():
                                logger.info(f"源文件 {transferhis.src} 开始删除")
                                Path(transferhis.src).unlink(missing_ok=True)
                                logger.info(f"源文件 {transferhis.src} 已删除")
                                self.__remove_parent_dir(Path(transferhis.src))

                            if transferhis.download_hash:
                                try:
                                    # 2、判断种子是否被删除完
                                    delete_flag, success_flag, handle_torrent_hashs = (
                                        self.handle_torrent(
                                            type=transferhis.type,
                                            src=transferhis.src,
                                            torrent_hash=transferhis.download_hash,
                                        )
                                    )
                                    if not success_flag:
                                        error_cnt += 1
                                    else:
                                        if delete_flag:
                                            del_torrent_hashs += handle_torrent_hashs
                                        else:
                                            stop_torrent_hashs += handle_torrent_hashs
                                except Exception as e:
                                    logger.error("删除种子失败：%s" % str(e))

        logger.info(f"同步删除 {msg} 完成！")

        media_type = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV

        # 发送消息
        if self._notify:
            backrop_image = image
            if media_source == MediaSource.TMDB and media_id:
                backrop_image = (
                    self.chain.obtain_specific_image(
                        mediaid=media_id,
                        mtype=media_type,
                        image_type=MediaImageType.Backdrop,
                        season=season_num,
                        episode=episode_num,
                    )
                    or image
                )

            torrent_cnt_msg = ""
            if del_torrent_hashs:
                torrent_cnt_msg += f"删除种子{len(set(del_torrent_hashs))}个\n"
            if stop_torrent_hashs:
                stop_cnt = 0
                # 排除已删除
                for stop_hash in set(stop_torrent_hashs):
                    if stop_hash not in set(del_torrent_hashs):
                        stop_cnt += 1
                if stop_cnt > 0:
                    torrent_cnt_msg += f"暂停种子{stop_cnt}个\n"
            if error_cnt:
                torrent_cnt_msg += f"删种失败{error_cnt}个\n"
            # 发送通知
            self.post_message(
                mtype=NotificationType.Plugin,
                title="媒体库同步删除任务完成",
                image=backrop_image,
                text=f"{msg}\n"
                f"删除记录{len(transfer_history) if transfer_history else '0'}个\n"
                f"{torrent_cnt_msg}"
                f"时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}",
            )

        # 读取历史记录
        history = self.get_data("history") or []

        # 获取poster
        poster_image = image
        if media_source == MediaSource.TMDB and media_id:
            poster_image = (
                self.chain.obtain_specific_image(
                    mediaid=media_id,
                    mtype=media_type,
                    image_type=MediaImageType.Poster,
                )
                or image
            )
        history.append(
            {
                "type": media_type.value,
                "title": media_name,
                "year": year,
                "path": media_path,
                "season": season_num
                if season_num and str(season_num).isdigit()
                else None,
                "episode": episode_num
                if episode_num and str(episode_num).isdigit()
                else None,
                "image": poster_image,
                "del_time": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(time.time())
                ),
                "unique": f"{media_name}:{media_source}:{media_id}:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}",
            }
        )

        # 保存历史
        self.save_data("history", history)

    def __delete_p115_files(
        self,
        file_path: str,
        media_name: str,
    ):
        """
        删除115网盘文件
        """
        try:
            # 获取文件(夹)详细信息
            fileitem = self._storagechain.get_file_item(
                storage="u115", path=Path(file_path)
            )
            if fileitem.type == "dir":
                # 删除整个文件夹
                self._storagechain.delete_file(fileitem)
                logger.info(f"{media_name} 删除网盘文件夹：{file_path}")
            else:
                # 调用 MP 模块删除媒体文件和空媒体目录
                self._storagechain.delete_media_file(fileitem=fileitem)
                logger.info(f"{media_name} 删除网盘媒体文件：{file_path}")
        except Exception as e:
            logger.error(f"{media_name} 删除网盘媒体 {file_path} 失败: {e}")

    def __delete_p123_files(
        self,
        file_path: str,
        media_name: str,
    ):
        """
        删除123云盘文件
        """
        try:
            # 获取文件(夹)详细信息
            fileitem = self._storagechain.get_file_item(
                storage="123云盘", path=Path(file_path)
            )
            if fileitem.type == "dir":
                # 删除整个文件夹
                self._storagechain.delete_file(fileitem)
                logger.info(f"{media_name} 删除网盘文件夹：{file_path}")
            else:
                # 调用 MP 模块删除媒体文件和空媒体目录
                self._storagechain.delete_media_file(fileitem=fileitem)
                logger.info(f"{media_name} 删除网盘媒体文件：{file_path}")
        except Exception as e:
            logger.error(f"{media_name} 删除网盘媒体 {file_path} 失败: {e}")

    def __get_p115_media_suffix(self, file_path: str):
        """
        115网盘 遍历文件夹获取媒体文件后缀
        """
        _, sub_paths = self.__get_p115_media_path(file_path)
        file_path = file_path.replace(sub_paths[0], sub_paths[2]).replace("\\", "/")
        file_dir = Path(file_path).parent
        file_basename = Path(file_path).stem
        file_dir_fileitem = self._storagechain.get_file_item(
            storage="u115", path=Path(file_dir)
        )
        for item in self._storagechain.list_files(file_dir_fileitem):
            if item.basename == file_basename:
                return item.extension
        return None

    def __get_p123_media_suffix(self, file_path: str):
        """
        123云盘 遍历文件夹获取媒体文件后缀
        """
        _, sub_paths = self.__get_p123_media_path(file_path)
        file_path = file_path.replace(sub_paths[0], sub_paths[2]).replace("\\", "/")
        file_dir = Path(file_path).parent
        file_basename = Path(file_path).stem
        file_dir_fileitem = self._storagechain.get_file_item(
            storage="123云盘", path=Path(file_dir)
        )
        for item in self._storagechain.list_files(file_dir_fileitem):
            if item.basename == file_basename:
                return item.extension
        return None

    def __remove_parent_dir(self, file_path: Path):
        """
        删除父目录
        """
        # 删除空目录
        # 判断当前媒体父路径下是否有媒体文件，如有则无需遍历父级
        if not SystemUtils.exits_files(file_path.parent, settings.RMT_MEDIAEXT):
            # 判断父目录是否为空, 为空则删除
            i = 0
            for parent_path in file_path.parents:
                i += 1
                if i > 3:
                    break
                if str(parent_path.parent) != str(file_path.root):
                    # 父目录非根目录，才删除父目录
                    if not SystemUtils.exits_files(parent_path, settings.RMT_MEDIAEXT):
                        # 当前路径下没有媒体文件则删除
                        shutil.rmtree(parent_path)
                        logger.warn(f"本地空目录 {parent_path} 已删除")

    def __get_transfer_his(
        self,
        media_type: str,
        media_name: str,
        media_path: str,
        media_source: Optional[MediaSource],
        media_id: Optional[str],
        season_num: str,
        episode_num: str,
    ):
        """
        查询转移记录
        """
        if not media_source or not media_id:
            return "", []

        # 季数
        if season_num and str(season_num).isdigit():
            season_num = str(season_num).rjust(2, "0")
        else:
            season_num = None
        # 集数
        if episode_num and str(episode_num).isdigit():
            episode_num = str(episode_num).rjust(2, "0")
        else:
            episode_num = None

        # 类型
        mtype = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV
        # 删除电影
        if mtype == MediaType.MOVIE:
            msg = f"电影 {media_name} {media_id}"
            transfer_history: List[TransferHistory] = self._transferhis.get_by(
                media_source=media_source,
                media_id=media_id,
                mtype=mtype.value,
                dest=media_path,
            )
        # 删除电视剧
        elif mtype == MediaType.TV and not season_num and not episode_num:
            msg = f"剧集 {media_name} {media_id}"
            transfer_history: List[TransferHistory] = self._transferhis.get_by(
                media_source=media_source,
                media_id=media_id,
                mtype=mtype.value,
            )
        # 删除季
        elif mtype == MediaType.TV and season_num and not episode_num:
            if not season_num or not str(season_num).isdigit():
                logger.error(f"{media_name} 季同步删除失败，未获取到具体季")
                return
            msg = f"剧集 {media_name} S{season_num} {media_id}"
            transfer_history: List[TransferHistory] = self._transferhis.get_by(
                media_source=media_source,
                media_id=media_id,
                mtype=mtype.value,
                season=f"S{season_num}",
            )
        # 删除集
        elif mtype == MediaType.TV and season_num and episode_num:
            if (
                not season_num
                or not str(season_num).isdigit()
                or not episode_num
                or not str(episode_num).isdigit()
            ):
                logger.error(f"{media_name} 集同步删除失败，未获取到具体集")
                return
            msg = f"剧集 {media_name} S{season_num}E{episode_num} {media_id}"
            transfer_history: List[TransferHistory] = self._transferhis.get_by(
                media_source=media_source,
                media_id=media_id,
                mtype=mtype.value,
                season=f"S{season_num}",
                episode=f"E{episode_num}",
                dest=media_path,
            )
        else:
            return "", []
        return msg, transfer_history

    def __get_series_media_id(self, series_id):
        """
        获取剧集 TMDB ID
        """
        if not self._emby_host or not self._emby_apikey or not self._emby_user:
            return None
        req_url = f"{self._emby_host}emby/Users/{self._emby_user}/Items/{series_id}?api_key={self._emby_apikey}"
        try:
            with RequestUtils().get_res(req_url) as res:
                if res:
                    return res.json().get("ProviderIds", {}).get("Tmdb")
                else:
                    logger.info("获取剧集 TMDB ID 失败，无法连接Emby！")
                    return None
        except Exception as e:
            logger.error("连接Items出错：" + str(e))
            return None

    def handle_torrent(
        self, type: str, src: str, torrent_hash: str
    ) -> Tuple[bool, bool, List[str]]:
        """
        判断种子是否局部删除
        局部删除则暂停种子
        全部删除则删除种子
        """
        download_id = torrent_hash
        download = self._default_downloader
        history_key = "%s-%s" % (download, torrent_hash)
        plugin_id = "TorrentTransfer"
        transfer_history = self.get_data(key=history_key, plugin_id=plugin_id)
        logger.info(f"查询到 {history_key} 转种历史 {transfer_history}")

        handle_torrent_hashs = []
        try:
            # 删除本次种子记录
            self._downloadhis.delete_file_by_fullpath(fullpath=src)

            # 根据种子hash查询所有下载器文件记录
            download_files = self._downloadhis.get_files_by_hash(
                download_hash=torrent_hash
            )
            if not download_files:
                logger.error(
                    f"未查询到种子任务 {torrent_hash} 存在文件记录，未执行下载器文件同步或该种子已被删除"
                )
                return False, False, []

            # 查询未删除数
            no_del_cnt = 0
            for download_file in download_files:
                if (
                    download_file
                    and download_file.state
                    and int(download_file.state) == 1
                ):
                    no_del_cnt += 1

            if no_del_cnt > 0:
                logger.info(
                    f"查询种子任务 {torrent_hash} 存在 {no_del_cnt} 个未删除文件，执行暂停种子操作"
                )
                delete_flag = False
            else:
                logger.info(
                    f"查询种子任务 {torrent_hash} 文件已全部删除，执行删除种子操作"
                )
                delete_flag = True

            # 如果有转种记录，则删除转种后的下载任务
            if transfer_history and isinstance(transfer_history, dict):
                download = transfer_history["to_download"]
                download_id = transfer_history["to_download_id"]
                delete_source = transfer_history["delete_source"]

                # 删除种子
                if delete_flag:
                    # 删除转种记录
                    self.del_data(key=history_key, plugin_id=plugin_id)

                    # 转种后未删除源种时，同步删除源种
                    if not delete_source:
                        logger.info(
                            f"{history_key} 转种时未删除源下载任务，开始删除源下载任务…"
                        )

                        # 删除源种子
                        logger.info(
                            f"删除源下载器下载任务：{self._default_downloader} - {torrent_hash}"
                        )
                        self.chain.remove_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    # 删除转种后任务
                    logger.info(f"删除转种后下载任务：{download} - {download_id}")
                    # 删除转种后下载任务
                    self.chain.remove_torrents(hashs=download_id, downloader=download)
                    handle_torrent_hashs.append(download_id)
                else:
                    # 暂停种子
                    # 转种后未删除源种时，同步暂停源种
                    if not delete_source:
                        logger.info(
                            f"{history_key} 转种时未删除源下载任务，开始暂停源下载任务…"
                        )

                        # 暂停源种子
                        logger.info(
                            f"暂停源下载器下载任务：{self._default_downloader} - {torrent_hash}"
                        )
                        self.chain.stop_torrents(torrent_hash)
                        handle_torrent_hashs.append(torrent_hash)

                    logger.info(f"暂停转种后下载任务：{download} - {download_id}")
                    # 删除转种后下载任务
                    self.chain.stop_torrents(hashs=download_id, downloader=download)
                    handle_torrent_hashs.append(download_id)
            else:
                # 未转种de情况
                if delete_flag:
                    # 删除源种子
                    logger.info(f"删除源下载器下载任务：{download} - {download_id}")
                    self.chain.remove_torrents(download_id)
                else:
                    # 暂停源种子
                    logger.info(f"暂停源下载器下载任务：{download} - {download_id}")
                    self.chain.stop_torrents(download_id)
                handle_torrent_hashs.append(download_id)

            # 处理辅种
            handle_torrent_hashs = self.__del_seed(
                download_id=download_id,
                delete_flag=delete_flag,
                handle_torrent_hashs=handle_torrent_hashs,
            )
            # 处理合集
            if str(type) == "电视剧":
                handle_torrent_hashs = self.__del_collection(
                    src=src,
                    delete_flag=delete_flag,
                    torrent_hash=torrent_hash,
                    download_files=download_files,
                    handle_torrent_hashs=handle_torrent_hashs,
                )
            return delete_flag, True, handle_torrent_hashs
        except Exception as e:
            logger.error(f"删种失败： {str(e)}")
            return False, False, []

    def __del_collection(
        self,
        src: str,
        delete_flag: bool,
        torrent_hash: str,
        download_files: list,
        handle_torrent_hashs: list,
    ):
        """
        处理做种合集
        """
        try:
            src_download_files = self._downloadhis.get_files_by_fullpath(fullpath=src)
            if src_download_files:
                for download_file in src_download_files:
                    # src查询记录 判断download_hash是否不一致
                    if (
                        download_file
                        and download_file.download_hash
                        and str(download_file.download_hash) != str(torrent_hash)
                    ):
                        # 查询新download_hash对应files数量
                        hash_download_files = self._downloadhis.get_files_by_hash(
                            download_hash=download_file.download_hash
                        )
                        # 新download_hash对应files数量 > 删种download_hash对应files数量 = 合集种子
                        if (
                            hash_download_files
                            and len(hash_download_files) > len(download_files)
                            and hash_download_files[0].id > download_files[-1].id
                        ):
                            # 查询未删除数
                            no_del_cnt = 0
                            for hash_download_file in hash_download_files:
                                if (
                                    hash_download_file
                                    and hash_download_file.state
                                    and int(hash_download_file.state) == 1
                                ):
                                    no_del_cnt += 1
                            if no_del_cnt > 0:
                                logger.info(
                                    f"合集种子 {download_file.download_hash} 文件未完全删除，执行暂停种子操作"
                                )
                                delete_flag = False

                            # 删除合集种子
                            if delete_flag:
                                self.chain.remove_torrents(
                                    hashs=download_file.download_hash,
                                    downloader=download_file.downloader,
                                )
                                logger.info(
                                    f"删除合集种子 {download_file.downloader} {download_file.download_hash}"
                                )
                            else:
                                # 暂停合集种子
                                self.chain.stop_torrents(
                                    hashs=download_file.download_hash,
                                    downloader=download_file.downloader,
                                )
                                logger.info(
                                    f"暂停合集种子 {download_file.downloader} {download_file.download_hash}"
                                )
                            # 已处理种子+1
                            handle_torrent_hashs.append(download_file.download_hash)

                            # 处理合集辅种
                            handle_torrent_hashs = self.__del_seed(
                                download_id=download_file.download_hash,
                                delete_flag=delete_flag,
                                handle_torrent_hashs=handle_torrent_hashs,
                            )
        except Exception as e:
            logger.error(f"处理 {torrent_hash} 合集失败")
            print(str(e))

        return handle_torrent_hashs

    def __del_seed(self, download_id, delete_flag, handle_torrent_hashs):
        """
        删除辅种
        """
        # 查询是否有辅种记录
        history_key = download_id
        plugin_id = "IYUUAutoSeed"
        seed_history = self.get_data(key=history_key, plugin_id=plugin_id) or []
        logger.info(f"查询到 {history_key} 辅种历史 {seed_history}")

        # 有辅种记录则处理辅种
        if seed_history and isinstance(seed_history, list):
            for history in seed_history:
                downloader = history.get("downloader")
                torrents = history.get("torrents")
                if not downloader or not torrents:
                    return
                if not isinstance(torrents, list):
                    torrents = [torrents]

                # 删除辅种历史
                for torrent in torrents:
                    handle_torrent_hashs.append(torrent)
                    # 删除辅种
                    if delete_flag:
                        logger.info(f"删除辅种：{downloader} - {torrent}")
                        self.chain.remove_torrents(hashs=torrent, downloader=downloader)
                    # 暂停辅种
                    else:
                        self.chain.stop_torrents(hashs=torrent, downloader=downloader)
                        logger.info(f"辅种：{downloader} - {torrent} 暂停")

                    # 处理辅种的辅种
                    handle_torrent_hashs = self.__del_seed(
                        download_id=torrent,
                        delete_flag=delete_flag,
                        handle_torrent_hashs=handle_torrent_hashs,
                    )

            # 删除辅种历史
            if delete_flag:
                self.del_data(key=history_key, plugin_id=plugin_id)
        return handle_torrent_hashs

    def get_state(self) -> bool:
        """
        返回插件启用状态

        :return: True 表示插件已启用
        """
        return self._enabled

    def stop_service(self) -> None:
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出插件失败：{e}")

    @eventmanager.register(EventType.DownloadFileDeleted)
    def downloadfile_del_sync(self, event: Event) -> None:
        """
        下载文件删除处理事件
        """
        if not event:
            return
        event_data = event.event_data
        src = event_data.get("src")
        if not src:
            return
        # 查询下载hash
        download_hash = self._downloadhis.get_hash_by_fullpath(src)
        if download_hash:
            download_history = self._downloadhis.get_by_hash(download_hash)
            self.handle_torrent(
                type=download_history.type, src=src, torrent_hash=download_hash
            )
        else:
            logger.warn(f"未查询到文件 {src} 对应的下载记录")

    @staticmethod
    def get_tmdbimage_url(path: str, prefix: str = "w500") -> str:
        """
        获取 TMDB 图片地址
        """
        if not path:
            return ""
        tmdb_image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}"
        return tmdb_image_url + f"/t/p/{prefix}{path}"
