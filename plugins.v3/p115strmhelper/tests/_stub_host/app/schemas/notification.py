"""
通知相关 schema 替身（V3 中通知开关配置独立成模块）。
"""

from .models import ChannelCapabilityManager, _NotificationSwitchConf

__all__ = ["NotificationSwitchConf", "ChannelCapabilityManager"]

NotificationSwitchConf = _NotificationSwitchConf
