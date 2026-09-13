"""
宿主兼容适配层。

MoviePilot V3 对部分公开符号做了改名与职责归位（通知渠道能力归
``app.schemas.notification``，消息收发归 ``app.schemas.message``），并在
``app/runtime/compat/manifest.py`` 中登记了旧名到新名的惰性别名。别名只在宿主
以完整应用形态启动后才由兼容导入器挂载；插件在单测、离线自检等场景下直接
import 宿主模块时可能拿不到别名。

插件其余代码统一直接 import V3 canonical 名（``Message``/``MessageType``/
``NotificationChannel``），本模块仅作为运行时兜底：当宿主符号再次改名时，只需
在这里追加候选，调用点不必改动。
"""

from typing import Any, Optional

__all__ = [
    "resolve_host_symbol",
    "get_notification_class",
    "get_notification_type_enum",
]

# 通知消息类：(模块, 符号) 候选，按优先级排列
_NOTIFICATION_CLASS_CANDIDATES = (
    ("app.schemas.message", "Message"),
    ("app.schemas", "Notification"),
    ("app.schemas.message", "Notification"),
)

# 通知场景枚举：(模块, 符号) 候选，按优先级排列
_NOTIFICATION_TYPE_CANDIDATES = (
    ("app.schemas.types", "MessageType"),
    ("app.schemas.types", "NotificationType"),
    ("app.schemas", "NotificationType"),
)


def resolve_host_symbol(candidates) -> Optional[Any]:
    """
    按优先级依次尝试从宿主解析符号。

    :param candidates: 形如 ((模块名, 符号名), ...) 的候选序列
    :return: 首个解析成功的对象；全部失败返回 None
    """
    from importlib import import_module

    for module_name, symbol_name in candidates:
        try:
            module = import_module(module_name)
            value = getattr(module, symbol_name, None)
        except Exception:
            continue
        if value is not None:
            return value
    return None


def get_notification_class() -> Optional[Any]:
    """
    获取通知消息类。

    V3 返回 ``app.schemas.message.Message``，V2 及兼容别名返回
    ``app.schemas.Notification``，两者字段兼容。
    """
    return resolve_host_symbol(_NOTIFICATION_CLASS_CANDIDATES)


def get_notification_type_enum() -> Optional[Any]:
    """
    获取通知场景枚举类。

    V3 返回 ``app.schemas.types.MessageType``，V2 及兼容别名返回
    ``app.schemas.types.MessageType``，枚举成员名与取值保持一致。
    """
    return resolve_host_symbol(_NOTIFICATION_TYPE_CANDIDATES)
