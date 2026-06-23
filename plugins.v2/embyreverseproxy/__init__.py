from threading import Thread
from typing import Any, Dict, List, Tuple

from uvicorn import Config, Server

from app.log import logger
from app.plugins import _PluginBase

from .external_players import EXTERNAL_PLAYERS
from .proxy_app import create_app


PIN_RULES_SEP = " => "


def _parse_pin_rules(raw: str) -> List[Tuple[str, str]]:
    """
    解析顶置路径规则字符串为 (路径前缀, 目标URL) 列表

    :param raw: 多行文本，每行「路径前缀 => 目标URL」（用 " => " 分隔，两侧可含空格）
    :return: 合法规则列表；非法行忽略并打日志
    """
    result: List[Tuple[str, str]] = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if PIN_RULES_SEP not in line:
            logger.warning(
                '顶置规则格式错误，已忽略（需用 " => " 分隔路径前缀与目标URL）: %s',
                line,
            )
            continue
        parts = line.split(PIN_RULES_SEP, 1)
        path_prefix = parts[0].strip()
        target_url = parts[1].strip()
        if not path_prefix or not target_url:
            logger.warning("顶置规则路径或目标为空，已忽略: %s", line)
            continue
        if not target_url.startswith(("http://", "https://")):
            logger.warning(
                "顶置规则目标需以 http:// 或 https:// 开头，已忽略: %s => %s",
                path_prefix,
                target_url,
            )
            continue
        result.append((path_prefix, target_url))
    return result


class EmbyReverseProxy(_PluginBase):
    """
    Emby 302 反向代理
    """

    plugin_name = "Emby 302 反向代理"
    plugin_desc = (
        "Emby 302 反向代理，自动代理 HTTP 链接，跳转最终地址，支持外部播放器调用。"
    )
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/refs/heads/main/icons/Emby_A.png"
    plugin_version = "0.2.4"
    plugin_author = "DDSRem"
    author_url = "https://github.com/DDSRem"
    plugin_config_prefix = "embyreverseproxy_"
    plugin_order = 20
    auth_level = 1

    _enabled = False
    _emby_host = ""
    _host = "0.0.0.0"
    _port = 8099
    _pin_rules: List[Tuple[str, str]] = []
    _pin_rules_raw = ""
    _external_player_url = False
    _external_player_list: List[str] = []
    _server = None
    _thread = None

    def init_plugin(self, config: Dict[str, Any] | None = None) -> None:
        """
        初始化插件：解析配置，启用时在独立线程启动 uvicorn，否则停止服务

        :param config (Dict): 插件配置字典
        """
        if config:
            self._enabled = config.get("enabled", False)
            self._emby_host = (config.get("emby_host") or "").strip()
            self._host = (config.get("host") or "0.0.0.0").strip() or "0.0.0.0"
            try:
                self._port = int(config.get("port") or 8099)
            except (TypeError, ValueError):
                self._port = 8099
            self._pin_rules_raw = (config.get("pin_rules") or "").strip()
            self._pin_rules = _parse_pin_rules(self._pin_rules_raw)
            self._external_player_url = config.get("external_player_url", False)
            self._external_player_list = config.get("external_player_list") or []
            self._update_config()

        self.stop_service()

        if self._enabled and self._emby_host:
            if not self._emby_host.startswith(("http://", "https://")):
                self._emby_host = "http://" + self._emby_host
            app = create_app(
                self._emby_host,
                pin_rules=self._pin_rules,
                external_player_url=self._external_player_url,
                external_player_list=self._external_player_list,
            )
            try:
                uv_config = Config(
                    app=app,
                    host=self._host,
                    port=self._port,
                    log_config=None,
                )
                self._server = Server(uv_config)
                self._thread = Thread(target=self._server.run, daemon=True)
                self._thread.start()
                logger.info(
                    "EmbyReverseProxy 代理已启动: %s:%s -> %s",
                    self._host,
                    self._port,
                    self._emby_host,
                )
            except Exception as e:
                logger.error("EmbyReverseProxy 启动失败: %s", e, exc_info=True)
                self._server = None
                self._thread = None
        elif self._enabled and not self._emby_host:
            logger.warning("EmbyReverseProxy 已启用但未配置 Emby 地址，代理未启动")

    def _update_config(self) -> None:
        """
        将当前配置写回插件配置存储
        """
        self.update_config(
            {
                "enabled": self._enabled,
                "emby_host": self._emby_host,
                "host": self._host,
                "port": self._port,
                "pin_rules": self._pin_rules_raw,
                "external_player_url": self._external_player_url,
                "external_player_list": self._external_player_list,
            }
        )

    def stop_service(self) -> None:
        """
        停止代理服务：设置 server.should_exit 并等待线程结束
        """
        if self._server is not None:
            try:
                self._server.should_exit = True
                if self._thread is not None and self._thread.is_alive():
                    self._thread.join(timeout=5.0)
                logger.info("EmbyReverseProxy 代理已停止")
            except Exception as e:
                logger.error("EmbyReverseProxy 停止异常: %s", e, exc_info=True)
            finally:
                self._server = None
                self._thread = None

    def get_state(self) -> bool:
        """
        返回插件启用状态

        :return bool: True 表示插件已启用
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件远程命令列表，本插件无远程命令

        :return List: 插件远程命令列表
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表，本插件无自定义 API

        :return List: 空列表
        """
        return []

    def get_page(self) -> List[dict]:
        """
        返回插件数据页面配置，本插件无数据页面

        :return List: 插件数据页面配置
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面

        :return Tuple: (页面配置列表, 表单默认值字典)
        """
        player_select_items = [
            {"title": info["name"], "value": key}
            for key, info in EXTERNAL_PLAYERS.items()
        ]
        return [
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
                                    "hint": "开启后将在独立端口运行 Emby 反向代理",
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
                                    "model": "external_player_url",
                                    "label": "外部播放器",
                                    "hint": "在 Emby 客户端中显示「使用外部播放器打开」按钮",
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
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VTextField",
                                "props": {
                                    "model": "emby_host",
                                    "label": "Emby 服务器地址",
                                    "placeholder": "http://192.168.1.100:8096",
                                    "hint": "Emby 服务器根地址，必填",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VTextField",
                                "props": {
                                    "model": "host",
                                    "label": "监听地址",
                                    "placeholder": "0.0.0.0",
                                    "hint": "代理监听地址",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VTextField",
                                "props": {
                                    "model": "port",
                                    "label": "监听端口",
                                    "placeholder": "8099",
                                    "hint": "代理监听端口",
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
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VSelect",
                                "props": {
                                    "model": "external_player_list",
                                    "label": "外部播放器列表",
                                    "items": player_select_items,
                                    "multiple": True,
                                    "chips": True,
                                    "clearable": True,
                                    "hint": "选择要显示的外部播放器，留空则显示全部",
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
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model": "pin_rules",
                                    "label": "顶置路径规则",
                                    "rows": 4,
                                    "placeholder": "每行一条：路径前缀 => 目标URL",
                                    "hint": "高级配置：不理解规则含义请勿配置（建议留空）。每行一条，格式：路径前缀 => 目标 URL；匹配到前缀后将路径替换为目标 URL 并返回 302。示例：/strm/cd2 => http://192.168.31.99:4567/d",
                                    "persistent-hint": True,
                                },
                            }
                        ],
                    },
                ],
            },
        ], {
            "enabled": False,
            "emby_host": "",
            "host": "0.0.0.0",
            "port": 8099,
            "pin_rules": "",
            "external_player_url": False,
            "external_player_list": [],
        }
