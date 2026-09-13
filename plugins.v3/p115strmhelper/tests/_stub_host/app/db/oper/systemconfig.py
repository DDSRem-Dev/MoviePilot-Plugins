"""
``app.db.oper.systemconfig`` 替身。

真实宿主是单例（``metaclass=Singleton``）并维护配置快照。替身保留单例语义与
``set`` 写入，读取走进程内字典。
"""

from typing import Any, Dict, Optional, Union

from ...foundation.singleton import Singleton

__all__ = ["SystemConfigOper"]


class SystemConfigOper(metaclass=Singleton):
    """系统配置管理替身。"""

    def __init__(self) -> None:
        self._values: Dict[str, Any] = {}

    def load_snapshot(self, db: Optional[Any] = None) -> None:
        """装载配置快照。替身无操作。"""

    def set(self, key: Union[str, Any], value: Any) -> Optional[bool]:
        """写入单个配置项。"""
        self._values[str(getattr(key, "value", key))] = value
        return True

    def get(self, key: Union[str, Any], default: Any = None) -> Any:
        return self._values.get(str(getattr(key, "value", key)), default)

    def update_atomically(self, key: Any, updater: Any, *args: Any, **kwargs: Any):
        """原子更新替身：直接调用 updater 并落库。"""
        value = updater(self.get(key), *args, **kwargs) if callable(updater) else updater
        self.set(key, value)
        return value

    def truncate(self) -> None:
        self._values.clear()
