from json import JSONDecodeError, loads
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from app.application.configuration import get_configured_system_config
from app.application.plugin.folders import remove_plugin_from_folders
from app.application.scheduling import remove_plugin_job
from app.db import SessionFactory
from app.db.oper.subscribe import SubscribeOper
from app.plugins import _PluginBase
from app.sdk.logging import logger
from app.sdk.plugins import PluginManager
from app.schemas.types import SystemConfigKey

TARGET_PLUGIN_ID = "P115StrgmSub"
FAKE_SITE_ID = -1


class P115SubFixer(_PluginBase):
    """
    115订阅站点修复插件
    """

    plugin_name = "115订阅站点修复"
    plugin_desc = "修复115网盘订阅追更插件导致的订阅站点被篡改问题，并自动卸载该插件"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/cloud.png"
    plugin_version = "3.0.0"
    plugin_author = "DDSRem"
    author_url = "https://github.com/DDSRem"
    plugin_config_prefix = "p115subfixer_"
    plugin_order = 1
    auth_level = 1

    _enabled: bool = False
    _onlyonce: bool = False

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化插件
        """
        if config:
            self._enabled = config.get("enabled", False)
            self._onlyonce = config.get("onlyonce", False)

        if not self._enabled and not self._onlyonce:
            return

        logger.info("115订阅站点修复：开始执行修复流程 ...")

        fixed_count = self._fix_subscribe_sites()
        deleted = self._remove_fake_site()
        uninstalled = self._uninstall_target_plugin()

        logger.info(
            f"115订阅站点修复：修复完成 — "
            f"修复订阅 {fixed_count} 个，"
            f"删除伪站点 {'成功' if deleted else '无需操作'}，"
            f"卸载 {TARGET_PLUGIN_ID} {'成功' if uninstalled else '未安装/已卸载'}"
        )

        self._onlyonce = False
        self._enabled = False
        self.update_config({"enabled": False, "onlyonce": False})

    @staticmethod
    def _normalize_str_sites(sites: str) -> Optional[Any]:
        """
        解析字符串形态的 sites，若含伪造 -1 则返回应写入的新值，否则返回 None

        :param sites: 数据库中的 sites 字符串
        :return: 新 sites（list 或逗号分隔 str），无需修改时返回 None
        """
        raw = (sites or "").strip()
        if not raw:
            return None

        # P115StrgmSub 误判为 str 存储时可能写入 str(-1)，即两个字符 -1；或整段带引号的四个字符
        if raw == '"-1"' or raw == "-1":
            return []

        if raw.startswith("["):
            try:
                parsed = loads(raw)
            except JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                has_fake = any(
                    x == FAKE_SITE_ID or str(x) == str(FAKE_SITE_ID) for x in parsed
                )
                if not has_fake:
                    return None
                return [
                    x
                    for x in parsed
                    if x != FAKE_SITE_ID and str(x) != str(FAKE_SITE_ID)
                ]

        parts = [p.strip() for p in sites.split(",") if p.strip()]
        fake_token = str(FAKE_SITE_ID)
        if fake_token not in parts:
            return None
        new_parts = [p for p in parts if p != fake_token]
        if not new_parts:
            return []
        return ",".join(new_parts)

    @staticmethod
    def _fix_subscribe_sites() -> int:
        """
        修复所有被篡改的订阅站点

        - sites == [-1] → 恢复为 []（使用系统默认）
        - sites 包含 -1 但还有其他值 → 仅移除 -1
        - SQLite 上 P115StrgmSub v1.2.8- 可能写入整段 \"-1\"（四个字符）或 str(-1) 的 \"-1\"，
          逗号拆分无法识别，此处显式处理（与 mrtian2016 v1.2.9 #21 同源问题）

        :return: 被修复的订阅数量
        """
        fixed = 0
        with SessionFactory() as db:
            oper = SubscribeOper(db=db)
            subscribes = oper.list() or []
            for sub in subscribes:
                sites = getattr(sub, "sites", None)
                if sites is None:
                    continue

                if isinstance(sites, list):
                    has_fake = FAKE_SITE_ID in sites or str(FAKE_SITE_ID) in sites
                    if not has_fake:
                        continue
                    new_sites = [
                        s for s in sites if s != FAKE_SITE_ID and s != str(FAKE_SITE_ID)
                    ]
                elif isinstance(sites, str):
                    new_sites = P115SubFixer._normalize_str_sites(sites)
                    if new_sites is None:
                        continue
                else:
                    continue

                oper.update(sub.id, {"sites": new_sites})
                logger.info(
                    f"115订阅站点修复：订阅 [{sub.id}] {sub.name} "
                    f"sites {sites} → {new_sites}"
                )
                fixed += 1

        return fixed

    @staticmethod
    def _remove_fake_site() -> bool:
        """
        删除 site 表中 id=-1 的伪造站点记录

        :return: 是否执行了删除
        """
        with SessionFactory() as db:
            row = db.execute(
                text("SELECT id FROM site WHERE id = :i"),
                {"i": FAKE_SITE_ID},
            ).fetchone()
            if not row:
                logger.info("115订阅站点修复：site 表中无 id=-1 的伪站点，无需清理")
                return False
            db.execute(
                text("DELETE FROM site WHERE id = :i"),
                {"i": FAKE_SITE_ID},
            )
            db.commit()
            logger.info("115订阅站点修复：已删除 site 表中 id=-1 的伪站点记录")
            return True

    @staticmethod
    def _uninstall_target_plugin() -> bool:
        """
        完整卸载 P115StrgmSub 插件（复刻主程序 uninstall_plugin 流程）

        :return: 是否成功卸载
        """
        plugin_manager = PluginManager()
        config_oper = get_configured_system_config()
        install_plugins: List[str] = list(
            config_oper.get(SystemConfigKey.UserInstalledPlugins) or []
        )

        if TARGET_PLUGIN_ID not in install_plugins:
            logger.info(
                f"115订阅站点修复：{TARGET_PLUGIN_ID} 未在已安装列表中，跳过卸载"
            )
            return False

        with plugin_manager.mutation(f"卸载插件 {TARGET_PLUGIN_ID}"):
            install_plugins.remove(TARGET_PLUGIN_ID)
            config_oper.set(SystemConfigKey.UserInstalledPlugins, install_plugins)
            logger.info(
                f"115订阅站点修复：已从 UserInstalledPlugins 中移除 {TARGET_PLUGIN_ID}"
            )

            try:
                remove_plugin_job(TARGET_PLUGIN_ID)
                logger.info(f"115订阅站点修复：已移除 {TARGET_PLUGIN_ID} 的调度器任务")
            except Exception as e:
                logger.warning(f"115订阅站点修复：移除调度器任务时出错（可忽略）：{e}")

            remove_plugin_from_folders(TARGET_PLUGIN_ID)

            try:
                plugin_manager.remove_plugin(TARGET_PLUGIN_ID)
                logger.info(f"115订阅站点修复：已从内存中卸载 {TARGET_PLUGIN_ID}")
            except Exception as e:
                logger.warning(f"115订阅站点修复：从内存卸载时出错（可忽略）：{e}")

        return True

    def get_state(self) -> bool:
        """
        返回插件启用状态

        :return: True 表示插件已启用
        """
        return self._enabled

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面

        :return: (页面配置列表, 表单默认值字典)
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
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "text": (
                                                "本插件用于修复「115网盘订阅追更」插件导致的订阅站点被篡改为 -1 的问题。"
                                                "执行后将：① 恢复所有订阅的站点设置；"
                                                "② 删除数据库中伪造的站点记录；"
                                                "③ 自动卸载「115网盘订阅追更」插件。"
                                                "修复完成后插件会自动禁用。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {"enabled": False, "onlyonce": False}

    def get_page(self) -> Optional[List[dict]]:
        """
        返回插件数据页面配置，本插件无数据页面

        :return: None
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 端点列表，本插件无自定义 API

        :return: None
        """
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        返回插件服务注册列表，本插件无自定义服务

        :return: None
        """
        pass

    def stop_service(self) -> None:
        """
        停止插件服务，本插件无需额外清理
        """
        pass
