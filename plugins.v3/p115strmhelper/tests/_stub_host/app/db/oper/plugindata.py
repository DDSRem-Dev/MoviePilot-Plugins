"""
``app.db.oper.plugindata`` 替身。

真实宿主把插件数据写入 ``PluginData`` 表。替身用进程内字典模拟，
让配置读写逻辑在测试中可完整跑通。
"""

from typing import Any, Dict, Optional

__all__ = ["PluginDataOper"]


class PluginDataOper:
    """插件数据管理替身。"""

    #: plugin_id -> {key: value}
    _store: Dict[str, Dict[str, Any]] = {}

    def save(self, plugin_id: str, key: str, value: Any):
        """保存插件数据。"""
        self._store.setdefault(plugin_id, {})[key] = value
        return True

    async def async_save(self, plugin_id: str, key: str, value: Any) -> None:
        self.save(plugin_id, key, value)

    def get_data(self, plugin_id: str, key: Optional[str] = None) -> Any:
        """读取插件数据；``key`` 为空时返回该插件的全部数据。"""
        data = self._store.get(plugin_id, {})
        if key is None:
            return dict(data)
        return data.get(key)

    async def async_get_data(self, plugin_id: str, key: Optional[str] = None) -> Any:
        return self.get_data(plugin_id, key)

    def get_data_all(self, plugin_id: str) -> Any:
        return dict(self._store.get(plugin_id, {}))

    async def async_get_data_all(self, plugin_id: str) -> Any:
        return self.get_data_all(plugin_id)

    def del_data(self, plugin_id: str, key: Optional[str] = None) -> Any:
        """删除插件数据。"""
        if key is None:
            self._store.pop(plugin_id, None)
            return True
        return self._store.get(plugin_id, {}).pop(key, None)

    def stage_delete(self, plugin_id: str) -> None:
        self._store.pop(plugin_id, None)

    def truncate(self) -> None:
        self._store.clear()
