import os
import platform
import shutil
import tarfile
import tempfile
from collections.abc import MutableMapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any, Dict, Generator, List, Tuple

import psutil
import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter

from app.core.config import settings
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase


class MediaWarp(_PluginBase):
    """
    Emby/Jellyfin 中间件：优化 Strm 播放、自定义前端样式、允许访问客户端控制、脚本注入
    """

    # 插件名称
    plugin_name = "MediaWarp"
    # 插件描述
    plugin_desc = "EmbyServer/Jellyfin 中间件：优化播放 Strm 文件、自定义前端样式、自定义允许访问客户端、嵌入脚本。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/refs/heads/main/icons/cloud.png"
    # 插件版本
    plugin_version = "1.0.8"
    # 插件作者
    plugin_author = "DDSRem"
    # 作者主页
    author_url = "https://github.com/DDSRem"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediawarp_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    _mediaserver_helper = None
    _mediaserver = None
    _mediaservers = None
    _emby_server = None
    _emby_host = None
    _emby_apikey = None
    # 私有属性
    _scheduler = None
    process = None
    _enabled = False
    _port = None
    _media_strm_path = None
    _crx = False
    _actor_plus = False
    _fanart_show = False
    _external_player_url = False
    _danmaku = False
    _video_together = False
    _srt2ass = False

    def __init__(self):
        """
        初始化
        """
        super().__init__()
        # 类名小写
        class_name = self.__class__.__name__.lower()
        # 二级制文件路径
        self.__mediawarp_path = settings.PLUGIN_DATA_PATH / class_name / "MediaWarp"
        # 配置文件路径
        self.__config_path = settings.PLUGIN_DATA_PATH / class_name / "config"
        # 日志路径
        self.__logs_dir = settings.PLUGIN_DATA_PATH / class_name / "logs"
        # 配置文件名
        self.__config_filename = "config.yaml"
        # 二级制文件版本
        self.__mediawarp_version = "0.1.12"
        self.__mediawarp_version_path = (
            settings.PLUGIN_DATA_PATH / class_name / "version.txt"
        )

    def init_plugin(self, config: dict = None):
        """
        初始化插件：读取配置，获取媒体服务器信息，启动代理服务

        :param config: 插件配置字典，包含 enabled、port、mediaservers 等
        """
        self._mediaserver_helper = MediaServerHelper()
        self._mediaserver = None

        if config:
            self._enabled = config.get("enabled")
            self._port = config.get("port")
            self._media_strm_path = config.get("media_strm_path")
            self._mediaservers = config.get("mediaservers") or []
            self._crx = config.get("crx")
            self._actor_plus = config.get("actor_plus")
            self._fanart_show = config.get("fanart_show")
            self._external_player_url = config.get("external_player_url")
            self._danmaku = config.get("danmaku")
            self._video_together = config.get("video_together")
            self._srt2ass = config.get("srt2ass")

            # 获取媒体服务器
            if self._mediaservers:
                self._mediaserver = [self._mediaservers[0]]

        # 获取媒体服务信息
        if self._mediaserver:
            emby_servers = self._mediaserver_helper.get_services(
                name_filters=self._mediaserver
            )

            for _, emby_server in emby_servers.items():
                self._emby_server = emby_server.type
                self._emby_apikey = emby_server.config.config.get("apikey")
                self._emby_host = emby_server.config.config.get("host")
                if self._emby_host.endswith("/"):
                    self._emby_host = self._emby_host.rstrip("/")
                if not self._emby_host.startswith("http"):
                    self._emby_host = "http://" + self._emby_host

        self.stop_service()

        if self._enabled:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("MediaWarp 服务启动中...")
            self._scheduler.add_job(
                func=self.__run_service,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                + timedelta(seconds=2),
                name="MediaWarp启动服务",
            )

            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __update_config(self):
        self.update_config(
            {
                "enabled": self._enabled,
                "port": self._port,
                "media_strm_path": self._media_strm_path,
                "mediaservers": self._mediaservers,
                "crx": self._crx,
                "actor_plus": self._actor_plus,
                "fanart_show": self._fanart_show,
                "external_player_url": self._external_player_url,
                "danmaku": self._danmaku,
                "video_together": self._video_together,
                "srt2ass": self._srt2ass,
            }
        )

    def get_state(self) -> bool:
        """
        返回插件启用状态

        :return: True 表示插件已启用
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件远程命令列表，本插件无远程命令

        :return: None
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表，本插件无自定义 API

        :return: None
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """

        web_ui = [
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
                                    "model": "crx",
                                    "label": "CRX美化",
                                    "hint": "crx 美化",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "model": "actor_plus",
                                    "label": "头像过滤",
                                    "hint": "过滤没有头像的演员和制作人员",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "model": "fanart_show",
                                    "label": "显示同人图",
                                    "hint": "显示同人图（fanart 图）",
                                    "persistent-hint": True,
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
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "model": "external_player_url",
                                    "label": "外置播放器",
                                    "hint": "是否开启外置播放器（仅 Emby）",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "model": "danmaku",
                                    "label": "Web弹幕",
                                    "hint": "Web 弹幕",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VSwitch",
                                "props": {
                                    "model": "video_together",
                                    "label": "共同观影",
                                    "hint": "共同观影",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                ],
            },
        ]

        subtitle = [
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
                                    "model": "srt2ass",
                                    "label": "SRT转ASS",
                                    "hint": "SRT 字幕转 ASS 字幕",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
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
                                            },
                                            {
                                                "component": "VCol",
                                                "props": {"cols": 12, "md": 4},
                                                "content": [
                                                    {
                                                        "component": "VTextField",
                                                        "props": {
                                                            "model": "port",
                                                            "label": "端口",
                                                            "hint": "反代后媒体服务器访问端口",
                                                            "persistent-hint": True,
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
                                                                for config in (
                                                                    self._mediaserver_helper.get_configs().values()
                                                                )
                                                                if config.type == "emby"
                                                                or config.type
                                                                == "jellyfin"
                                                            ],
                                                            "hint": "同时只能选择一个",
                                                            "persistent-hint": True,
                                                        },
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                            {
                                "component": "VRow",
                                "content": [
                                    {
                                        "component": "VCol",
                                        "props": {"cols": 12},
                                        "content": [
                                            {
                                                "component": "VTextarea",
                                                "props": {
                                                    "model": "media_strm_path",
                                                    "label": "Emby STRM 媒体库路径",
                                                    "rows": 5,
                                                    "placeholder": "一行一个",
                                                },
                                            },
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
                                        "text": "注意：",
                                    },
                                    {
                                        "component": "div",
                                        "text": "如果 MoviePilot 容器为 bridge 模式需要手动映射配置的端口",
                                    },
                                    {
                                        "component": "div",
                                        "text": "更多配置可以前往 MoviePilot 配置目录找到此插件的配置目录进行详细配置文件配置",
                                    },
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
                                        "text": "目前支持 115网盘STRM助手，123云盘STRM助手，CloudMediaSync，OneStrm",
                                    },
                                    {
                                        "component": "div",
                                        "text": "Symedia，q115-strm 等软件生成的STRM文件",
                                    },
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
                                        "text": "感谢项目作者：https://github.com/Akimio521/MediaWarp",
                                    },
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
                                "props": {"value": "web-ui"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "icon": "mdi-file-move-outline",
                                            "start": True,
                                            "color": "#1976D2",
                                        },
                                    },
                                    {"component": "span", "text": "Web页面配置"},
                                ],
                            },
                            {
                                "component": "VTab",
                                "props": {"value": "subtitle"},
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "icon": "mdi-sync",
                                            "start": True,
                                            "color": "#4CAF50",
                                        },
                                    },
                                    {"component": "span", "text": "字体相关设置"},
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
                                "props": {"value": "web-ui"},
                                "content": [
                                    {
                                        "component": "VCardText",
                                        "content": web_ui,
                                    }
                                ],
                            },
                            {
                                "component": "VWindowItem",
                                "props": {"value": "subtitle"},
                                "content": [
                                    {"component": "VCardText", "content": subtitle}
                                ],
                            },
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "port": "",
            "media_strm_path": "",
            "mediaservers": [],
            "crx": False,
            "actor_plus": False,
            "fanart_show": False,
            "external_player_url": False,
            "danmaku": False,
            "video_together": False,
            "srt2ass": False,
            "tab": "web-ui",
        }

    def get_page(self) -> List[dict]:
        """
        返回插件数据页面配置，本插件无数据页面

        :return: None
        """
        pass

    def __run_service(self) -> None:
        """
        运行服务并记录调度任务中的启动异常
        """
        try:
            self.__start_service()
        except Exception:
            logger.error(
                "MediaWarp 服务启动失败，请检查配置文件、文件权限和磁盘空间",
                exc_info=True,
            )

    def __start_service(self) -> None:
        """
        准备配置并启动服务
        """
        if not Path(self.__mediawarp_path).exists():
            logger.info("尝试自动下载二级制文件中...")
            self.__download_and_extract()
            if not Path(self.__mediawarp_path).exists():
                logger.error("下载失败，MediaWarp 二级制文件不存在，无法启动插件")
                logger.info(
                    f"请将 MediaWarp 二级制文件放入 {settings.PLUGIN_DATA_PATH / self.__class__.__name__.lower()} 文件夹内"
                )
                self.__update_config()
                return

        if os.path.exists(self.__mediawarp_version_path):
            with open(self.__mediawarp_version_path, "r", encoding="utf-8") as f:
                version = f.read().strip()
            if version != self.__mediawarp_version:
                logger.info("尝试自动更新二级制文件中...")
                self.__download_and_extract()

        changes = {
            "Port": self._port,
            "Logger.AccessLogger.File": True,
            "Logger.AccessLogger.Console": False,
            "MediaServer.Type": "Jellyfin"
            if self._emby_server == "jellyfin"
            else "Emby",
            "MediaServer.ADDR": self._emby_host,
            "MediaServer.AUTH": self._emby_apikey,
            "Web.Index": bool(
                Path(self.__config_path / "static" / "index.html").exists()
            ),
            "Web.Crx": bool(self._crx),
            "Web.ActorPlus": bool(self._actor_plus),
            "Web.FanartShow": bool(self._fanart_show),
            "Web.Danmaku": bool(self._danmaku),
            "Web.ExternalPlayerUrl": bool(self._external_player_url),
            "Web.VideoTogether": bool(self._video_together),
            "HTTPStrm.Enable": True,
            "HTTPStrm.FinalURL": True,
            "HTTPStrm.PrefixList": (self._media_strm_path or "").split("\n"),
            "Subtitle.SRT2ASS": bool(self._srt2ass),
        }
        self.__modify_config(Path(self.__config_path / self.__config_filename), changes)

        Path(self.__config_path).mkdir(parents=True, exist_ok=True)
        Path(self.__logs_dir).mkdir(parents=True, exist_ok=True)

        self.process = psutil.Popen([self.__mediawarp_path])

        if self.process.is_running():
            logger.info("MediaWarp 服务成功启动！")
        else:
            logger.error("MediaWarp 进程启动后已退出，请检查 MediaWarp 日志和配置")

    @staticmethod
    @contextmanager
    def __atomic_write(
        target: Path, binary: bool = False
    ) -> Generator[IO[Any], None, None]:
        """
        写入同目录临时文件，落盘成功后原子替换目标文件

        :param target (Path): 目标文件路径
        :param binary (bool): 是否以二进制模式写入

        :yields IO: 临时文件对象
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb" if binary else "w",
            encoding=None if binary else "utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            try:
                if target.exists():
                    shutil.copymode(target, temp_path)
                yield file
                file.flush()
                os.fsync(file.fileno())
                file.close()
                os.replace(temp_path, target)
            finally:
                temp_path.unlink(missing_ok=True)

    def __atomic_copy(self, source: Path, target: Path) -> None:
        """
        原子复制文件并保留源文件的权限和时间戳
        """
        with (
            source.open("rb") as source_file,
            self.__atomic_write(target, binary=True) as target_file,
        ):
            shutil.copyfileobj(source_file, target_file)
            target_file.flush()
            shutil.copystat(source, target_file.name)

    def __modify_config(self, config_path: Path, modifications: Dict[str, Any]) -> None:
        """
        修改配置文件

        空文件或缺失文件按插件设置重建，解析或结构错误保留原文件并报错

        :param config_path (Path): 配置文件路径
        :param modifications (Dict): 要修改的配置项字典
        """
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        def represent_bool(self, data):
            """
            将 Python bool 序列化为 YAML 大写 True/False 字符串

            :param data: 布尔值
            :return: YAML 标量节点
            """
            if data:
                return self.represent_scalar("tag:yaml.org,2002:bool", "True")
            else:
                return self.represent_scalar("tag:yaml.org,2002:bool", "False")

        RoundTripRepresenter.add_representer(bool, represent_bool)

        config = None
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as file:
                config = yaml.load(file)
        if config is None:
            logger.warning("MediaWarp 配置文件为空或不存在，将按插件设置重建")
            config = {}
        if not isinstance(config, MutableMapping):
            raise TypeError("MediaWarp 配置文件根节点必须是映射")

        for key, value in modifications.items():
            keys = key.split(".")
            current = config
            for k in keys[:-1]:
                if current.get(k) is None:
                    current[k] = {}
                current = current[k]
                if not isinstance(current, MutableMapping):
                    raise TypeError(f"MediaWarp 配置项 {key} 的父节点必须是映射")
            current[keys[-1]] = value

        with self.__atomic_write(config_path) as file:
            yaml.dump(config, file)

    def __get_download_url(self):
        """
        获取下载链接
        """
        base_url = (
            "https://github.com/DDSRem-Dev/MediaWarp/releases/"
            "download/v{version}/MediaWarp_{version}_{os}_{arch}.tar.gz"
        )

        machine = platform.machine().lower()
        if machine == "arm64" or machine == "aarch64":
            arch = "arm64"
        else:
            arch = "amd64"

        system = platform.system().lower()
        if system == "darwin":
            os_name = "darwin"
        else:
            os_name = "linux"

        return base_url.format(arch=arch, version=self.__mediawarp_version, os=os_name)

    def __download_and_extract(self):
        """
        下载并解压
        """
        url = self.__get_download_url()
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, "MediaWarp.tar.gz")

        try:
            Path(self.__config_path).mkdir(parents=True, exist_ok=True)

            logger.info(f"正在下载: {url}")
            response = requests.get(url, stream=True, proxies=settings.PROXY)
            response.raise_for_status()

            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("正在解压文件...")
            with tarfile.open(temp_file, "r:gz") as tar:
                mediawarp_member = [
                    m for m in tar.getmembers() if m.name.endswith("MediaWarp")
                ]
                if mediawarp_member:
                    tar.extract(member=mediawarp_member[0], path=temp_dir)
                    extracted_path = Path(temp_dir) / mediawarp_member[0].name
                    extracted_path.chmod(0o755)
                    self.__atomic_copy(extracted_path, Path(self.__mediawarp_path))
                else:
                    raise ValueError("下载的压缩包中缺少 MediaWarp 二进制文件")

                config_target = Path(self.__config_path / self.__config_filename)
                if not config_target.exists():
                    config_example_member = [
                        m
                        for m in tar.getmembers()
                        if m.name.endswith("config.yaml.example")
                    ]
                    if config_example_member:
                        tar.extract(member=config_example_member[0], path=temp_dir)
                        extracted_config = (
                            Path(temp_dir) / config_example_member[0].name
                        )
                        self.__atomic_copy(extracted_config, config_target)
                        logger.info(f"示例配置文件已保存到 {config_target}")

            with self.__atomic_write(self.__mediawarp_version_path) as f:
                f.write(self.__mediawarp_version)
            logger.info(f"安装完成！MediaWarp 已安装到 {self.__mediawarp_path}")
        except Exception as e:
            logger.error(f"MediaWarp 安装失败: {e}", exc_info=True)
        finally:
            shutil.rmtree(temp_dir)

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
            if self.process:
                if self.process.is_running():
                    self.process.terminate()
        except Exception as e:
            logger.error(f"退出插件失败：{e}")
