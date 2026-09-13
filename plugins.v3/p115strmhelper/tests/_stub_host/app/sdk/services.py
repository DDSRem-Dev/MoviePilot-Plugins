"""
``app.sdk.services`` 替身。

真实宿主从 ``app.application.downloader`` / ``mediaserver`` / ``storage`` 重新
导出。替身对齐 ``ServiceBaseHelper`` 的公开契约：

* ``get_configs(include_disabled=False)``
* ``get_config(name)``
* ``get_services(type_filter=None, name_filters=None)``
* ``get_service(name, type_filter=None)``

替身默认返回空集合（测试环境无已启用服务），可通过 :func:`_register_service`
注入假实例做集成测试。
"""

from typing import Any, Dict, List, Optional

__all__ = [
    "DownloaderHelper",
    "MediaServerHelper",
    "StorageHelper",
]


class _ServiceInfo:
    """宿主 ``app.schemas.system.ServiceInfo`` 子集替身。"""

    def __init__(
        self,
        name: Optional[str] = None,
        instance: Any = None,
        module: Any = None,
        type: Optional[str] = None,
        config: Any = None,
    ) -> None:
        self.name = name
        self.instance = instance
        self.module = module
        self.type = type
        self.config = config

    def __repr__(self) -> str:
        return f"ServiceInfo(name={self.name!r}, type={self.type!r})"


class ServiceBaseHelper:
    """服务配置与运行实例查询替身。"""

    #: 全局登记表：服务类型名 -> {服务名: ServiceInfo}，供测试注入
    _registry: Dict[str, Dict[str, _ServiceInfo]] = {}

    def __init__(self, config_key: Any = None, conf_type: Any = None,
                 module_type: Any = None) -> None:
        self.config_key = config_key
        self.conf_type = conf_type
        self.module_type = module_type

    def get_configs(self, include_disabled: bool = False) -> Dict[str, Any]:
        """替身环境默认无任何服务配置。"""
        return {}

    def get_config(self, name: str) -> Optional[Any]:
        return self.get_configs().get(name) if name else None

    def get_services(
        self,
        type_filter: Optional[str] = None,
        name_filters: Optional[List[str]] = None,
    ) -> Dict[str, _ServiceInfo]:
        names = set(name_filters) if name_filters else None
        return {
            name: info
            for name, info in self._registry.get(str(self.module_type), {}).items()
            if (type_filter is None or info.type == type_filter)
            and (names is None or name in names)
        }

    def get_service(
        self,
        name: str,
        type_filter: Optional[str] = None,
    ) -> Optional[_ServiceInfo]:
        if not name:
            return None
        return self.get_services(type_filter=type_filter, name_filters=[name]).get(name)


class DownloaderHelper(ServiceBaseHelper):
    """下载器帮助类替身。"""

    def is_downloader(
        self,
        service_type: Optional[str] = None,
        service: Optional[_ServiceInfo] = None,
        name: Optional[str] = None,
    ) -> bool:
        service = service or self.get_service(name=name)
        return bool(service and service.type == service_type)


class MediaServerHelper(ServiceBaseHelper):
    """媒体服务器帮助类替身。"""

    def is_media_server(
        self,
        service_type: Optional[str] = None,
        service: Optional[_ServiceInfo] = None,
        name: Optional[str] = None,
    ) -> bool:
        service = service or self.get_service(name=name)
        return bool(service and service.type == service_type)


class StorageHelper:
    """存储配置帮助类替身。"""

    def __init__(self) -> None:
        self._storages: Dict[str, Any] = {}

    def get_storagies(self) -> List[Any]:
        return list(self._storages.values())

    def get_storage(self, storage: str) -> Optional[Any]:
        return self._storages.get(storage)

    def set_storage(self, storage: str, conf: dict) -> None:
        self._storages[storage] = conf

    def add_storage(self, storage: str, name: str, conf: dict) -> None:
        self._storages[storage] = conf


def _register_service(module_type: Any, name: str, info: _ServiceInfo) -> None:
    """测试辅助：登记一个运行中的服务实例。"""
    ServiceBaseHelper._registry.setdefault(str(module_type), {})[name] = info


def _clear_services() -> None:
    """测试辅助：清空服务登记表。"""
    ServiceBaseHelper._registry.clear()
