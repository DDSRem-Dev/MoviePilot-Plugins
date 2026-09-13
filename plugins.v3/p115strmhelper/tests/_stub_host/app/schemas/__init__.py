"""
``app.schemas`` 包替身。

真实宿主里这是一个**惰性导出包**：``__getattr__`` 按需从
``app/schemas/exports.py`` 的清单里解析符号。本替身复刻该行为，并额外
登记 V3 改名后的新旧双向别名，用于验证插件是否只依赖稳定接口。

别名来源：``app/runtime/compat/manifest.py`` 的 ``SYMBOL_ALIASES``：

    Notification      -> app.schemas.message.Message
    NotificationType  -> app.schemas.types.MessageType
    MessageChannel    -> app.schemas.types.NotificationChannel
"""

from importlib import import_module
from typing import Any, Dict, Tuple

__all__ = [
    "FileItem",
    "MediaInfo",
    "RefreshMediaItem",
    "ServiceInfo",
    "StorageOperSelectionEventData",
    "TransferInfo",
    "TransferInterceptEventData",
    "TransferOverwriteCheckEventData",
    "TransferRenameBuildEventData",
    "TransferTask",
    "Message",
    "MessageType",
    "Notification",
    "NotificationType",
    "NotificationChannel",
    "MessageChannel",
]

#: 符号名 -> (模块名, 该模块内的属性名)
_SCHEMA_EXPORTS: Dict[str, Tuple[str, str]] = {
    # ---- 核心模型 ----
    "FileItem": ("app.schemas.models", "FileItem"),
    "TransferInfo": ("app.schemas.models", "TransferInfo"),
    "TransferTask": ("app.schemas.models", "TransferTask"),
    "MediaInfo": ("app.schemas.models", "MediaInfo"),
    "RefreshMediaItem": ("app.schemas.models", "RefreshMediaItem"),
    "ServiceInfo": ("app.schemas.models", "ServiceInfo"),
    "TransferRenameBuildEventData": (
        "app.schemas.models",
        "TransferRenameBuildEventData",
    ),
    "StorageOperSelectionEventData": (
        "app.schemas.models",
        "StorageOperSelectionEventData",
    ),
    "TransferInterceptEventData": ("app.schemas.models", "TransferInterceptEventData"),
    "TransferOverwriteCheckEventData": (
        "app.schemas.models",
        "TransferOverwriteCheckEventData",
    ),
    "WebhookEventInfo": ("app.schemas.models", "WebhookEventInfo"),
    # ---- 消息 / 通知（V3 canonical 名）----
    "Message": ("app.schemas.message", "Message"),
    "NotificationSwitchConf": ("app.schemas.notification", "NotificationSwitchConf"),
    "ChannelCapabilityManager": ("app.schemas.message", "ChannelCapabilityManager"),
    # ---- 类型枚举 ----
    "MessageType": ("app.schemas.types", "MessageType"),
    "NotificationChannel": ("app.schemas.types", "NotificationChannel"),
    "MediaType": ("app.schemas.types", "MediaType"),
    "MediaSource": ("app.schemas.types", "MediaSource"),
    "EventType": ("app.schemas.types", "EventType"),
    "ChainEventType": ("app.schemas.types", "ChainEventType"),
    "MediaImageType": ("app.schemas.types", "MediaImageType"),
    "ContentType": ("app.schemas.types", "ContentType"),
    "ModuleType": ("app.schemas.types", "ModuleType"),
    "OtherModulesType": ("app.schemas.types", "OtherModulesType"),
    "StorageAction": ("app.schemas.types", "StorageAction"),
    # ---- 旧名兼容别名（迁移过渡期，宿主 manifest 登记过）----
    "Notification": ("app.schemas.message", "Message"),
    "NotificationType": ("app.schemas.types", "MessageType"),
    "MessageChannel": ("app.schemas.types", "NotificationChannel"),
}


def __getattr__(name: str) -> Any:
    """按需解析 schema 符号，未登记的符号抛出 AttributeError。"""
    target = _SCHEMA_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'app.schemas' has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_SCHEMA_EXPORTS))
