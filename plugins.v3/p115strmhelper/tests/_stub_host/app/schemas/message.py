"""
消息（通知）模型替身。

V3 中 ``Notification`` 已更名为 ``Message``，模型定义位于
``app.schemas.message``。本替身同时提供新旧两套名字，便于插件在
迁移过渡期的双读。
"""

from typing import Any, Dict, List, Optional

from .models import _Message, _NotificationSwitchConf, ChannelCapabilityManager

__all__ = [
    "Message",
    "Notification",
    "NotificationSwitchConf",
    "ChannelCapabilityManager",
]

Message = _Message

#: 旧名兼容（V2 时代 ``from app.schemas import Notification``）
Notification = _Message

#: 通知开关配置（V3 中由 app.schemas.notification 提供）
NotificationSwitchConf = _NotificationSwitchConf
