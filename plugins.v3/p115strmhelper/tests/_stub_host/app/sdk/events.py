"""
``app.sdk.events`` 替身。

真实宿主中 ``Event`` 与 ``eventmanager`` 定义在 ``app.runtime.events``。
替身保持同样的公开语义：

* ``Event(event_type, event_data, priority, correlation_id)``
* ``eventmanager.register(etype, priority)`` 作为装饰器，支持单成员 / 类 / 列表
* ``eventmanager.send_event(etype, data)`` 返回 ``(success, message)``
"""

from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from ..schemas.types import ChainEventType, EventType

__all__ = ["Event", "EventManager", "eventmanager"]

_EVENT_REGISTRATION = Union[EventType, ChainEventType, List[Any], Any]


class Event:
    """事件对象替身。"""

    def __init__(
        self,
        event_type: Any,
        event_data: Optional[Dict] = None,
        priority: Optional[int] = 10,
        correlation_id: Optional[str] = None,
    ) -> None:
        self.event_id = str(uuid4())
        self.event_type = event_type
        self.event_data = event_data or {}
        self.priority = priority
        self.correlation_id = correlation_id or "stub-correlation"

    def __repr__(self) -> str:
        return f"Event(type={self.event_type!r}, data={self.event_data!r})"


class EventManager:
    """事件管理器替身：只记录注册与投递，不做真实派发。"""

    def __init__(self) -> None:
        #: 事件类型 -> 处理器列表
        self.listeners: Dict[Any, List[Callable]] = {}
        #: 投递记录，便于测试断言「插件确实发了某事件」
        self.sent_events: List[Event] = []

    def register(
        self,
        etype: _EVENT_REGISTRATION,
        priority: Optional[int] = 10,
    ) -> Callable[[Callable], Callable]:
        """事件注册装饰器：把被装饰函数登记到给定事件类型上。"""

        def decorator(func: Callable) -> Callable:
            if isinstance(etype, list):
                event_list = list(etype)
            else:
                event_list = [etype]
            for event in event_list:
                self.listeners.setdefault(event, []).append(func)
            return func

        return decorator

    def add_event_listener(
        self, etype: Any, handler: Callable, priority: Optional[int] = 10
    ) -> None:
        self.listeners.setdefault(etype, []).append(handler)

    def send_event(
        self,
        etype: Any,
        data: Optional[Dict] = None,
        priority: Optional[int] = 10,
    ):
        """投递事件。返回 ``(success, message)``，与宿主签名一致。"""
        event = Event(event_type=etype, event_data=data, priority=priority)
        self.sent_events.append(event)
        return True, "stub: event recorded"

    def start(self) -> None:
        """替身不做后台线程。"""

    def stop(self) -> None:
        """替身不做后台线程。"""


eventmanager = EventManager()
