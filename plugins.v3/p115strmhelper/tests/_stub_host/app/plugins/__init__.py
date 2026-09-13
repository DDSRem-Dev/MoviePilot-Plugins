"""
``app.plugins`` 包替身：插件基类。

真实 ``_PluginBase`` 提供插件元数据、配置读写与数据持久化。替身按插件实际
访问到的成员提供等价面，并让子类可以只用 ``plugin_name`` 等类属性。
"""

from typing import Any, Dict, List, Optional

__all__ = ["_PluginBase", "PluginBase"]

from ..db.oper.plugindata import PluginDataOper


class _PluginBase:
    """插件基类替身。"""

    #: 子类通常覆盖这些类属性
    plugin_name: str = ""
    plugin_desc: str = ""
    plugin_icon: str = ""
    plugin_version: str = ""
    plugin_author: str = ""
    author_url: str = ""
    plugin_config_prefix: str = ""
    plugin_order: int = 0
    auth_level: int = 0
    restart: bool = False

    def __init__(self) -> None:
        self._plugindata = PluginDataOper()
        self._config: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 身份
    # ------------------------------------------------------------------
    @property
    def plugin_id(self) -> str:
        """插件唯一标识：与宿主一致，取类名。"""
        return self.__class__.__name__

    # ------------------------------------------------------------------
    # 生命周期钩子（宿主会在对应时机调用）
    # ------------------------------------------------------------------
    def init_plugin(self, config: Optional[dict] = None) -> None:
        """初始化插件。"""
        if config:
            self._config.update(config)

    def get_state(self) -> bool:
        """返回插件启用状态。"""
        return bool(self._config.get("enabled"))

    def stop_service(self) -> None:
        """停止插件服务。"""

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def get_config(self, key: str = None, default: Any = None) -> Any:
        """读取插件配置。"""
        if key is None:
            return dict(self._config)
        return self._config.get(key, default)

    def update_config(self, config: dict) -> None:
        """更新插件配置。"""
        self._config.update(config or {})

    def save_data(self, key: str, value: Any) -> None:
        """持久化插件数据。"""
        self._plugindata.save(self.plugin_id, key, value)

    def get_data(self, key: str = None) -> Any:
        """读取插件数据。"""
        return self._plugindata.get_data(self.plugin_id, key)

    def del_data(self, key: str = None) -> Any:
        return self._plugindata.del_data(self.plugin_id, key)

    # ------------------------------------------------------------------
    # 插件注册表（宿主 API 会用到）
    # ------------------------------------------------------------------
    def get_form(self) -> Optional[List[dict]]:
        """返回插件配置表单定义。"""
        return None

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页定义。"""
        return None

    def get_api(self) -> Optional[List[dict]]:
        """返回插件 API 定义。"""
        return None

    def get_service(self) -> Optional[List[dict]]:
        """返回插件后台服务定义。"""
        return None


#: 部分插件历史代码使用别名
PluginBase = _PluginBase
