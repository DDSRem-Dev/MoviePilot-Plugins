__all__ = ["SentryManager", "sentry_manager"]


import functools
import inspect
from base64 import b64decode
from typing import Dict, List, Any

import sentry_sdk
from sentry_sdk.hub import Hub
from sentry_sdk.client import Client
from sentry_sdk.transport import HttpTransport
from sentry_sdk.integrations.stdlib import StdlibIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration

from app.log import logger
from version import APP_VERSION

from ..version import VERSION
from ..core.config import configer
from ..utils.exception import (
    PanPathNotFound,
    U115NoCheckInException,
    CanNotFindPathToCid,
    PanDataNotInDb,
    FileItemKeyMiss,
)


class CustomHttpTransport(HttpTransport):
    """
    Sentry 自定义 HTTP 传输层，在 User-Agent 中追加插件版本信息
    """

    def __init__(self, options):
        super().__init__(options)
        original_ua = str(self._auth.client)
        addon_ua = f"P115StrmHelper/{VERSION}"
        if original_ua:
            new_ua = f"{original_ua} {addon_ua}"
        else:
            new_ua = addon_ua
        self._auth.client = new_ua


class NoopSentryHub(Hub):
    """
    一个不执行任何操作的 Sentry Hub，用于禁用状态
    """

    def capture_event(self, event, hint=None, scope=None, **scope_kwargs):
        """
        空实现：捕获并上报事件
        """
        pass

    def capture_exception(self, error=None, **kwargs):
        """
        空实现：捕获并上报异常
        """
        pass

    def capture_message(self, message, **kwargs):
        """
        空实现：捕获并上报消息
        """
        pass

    def configure_scope(self, callback=None, continue_trace=True):
        """
        空实现：配置 Sentry 作用域并返回一个 NoopScope

        :param callback (callable): 可选的作用域配置回调
        :param continue_trace (bool): 是否继续追踪（忽略）

        :return NoopScope: 空实现的作用域上下文管理器
        """

        class NoopScope:
            """
            空实现的作用域上下文管理器
            """

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def __getattr__(self, name):
                return lambda *args, **kwargs: None

        if callback:
            callback(NoopScope())  # noqa
        return NoopScope()

    def add_breadcrumb(self, crumb=None, hint=None, **kwargs):
        """
        空实现：添加面包屑
        """
        pass

    def push_scope(self, callback=None, continue_trace=True):
        """
        空实现：推送作用域并返回 NoopContextManager

        :param callback (callable): 可选的回调
        :param continue_trace (bool): 是否继续追踪（忽略）

        :return NoopContextManager: 空实现的上下文管理器
        """

        class NoopContextManager:
            """
            空实现的上下文管理器
            """

            def __enter__(self):
                pass

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return NoopContextManager()

    def pop_scope(self, *args, **kwargs):
        """
        空实现：弹出作用域
        """
        pass

    def flush(self, timeout=None, callback=None):
        """
        空实现：刷新缓冲区

        :param timeout (float): 超时时间（忽略）
        :param callback (callable): 完成回调（忽略）
        """
        pass

    def __getattr__(self, name):
        """
        空实现：对任意属性返回一个空函数
        """
        return lambda *args, **kwargs: None


class SentryManager:
    """
    Sentry 状态和行为的管理器
    """

    def __init__(self):
        """
        初始化 Sentry 管理器，加载忽略规则和配置
        """
        self.sentry_hub = NoopSentryHub()
        self._patched = False

        self._ignored_rules: List[Dict[str, Any]] = [
            {"type": U115NoCheckInException},
            {"type": PanDataNotInDb, "message": "无法找到路径"},
            {"type": CanNotFindPathToCid, "message": "无法找到路径"},
            {"type": CanNotFindPathToCid, "message": "无法获取目录信息"},
            {"type": PanPathNotFound, "message": "网盘路径不存在"},
            {"type": FileItemKeyMiss},
            {"type": OSError, "message": "File name too long"},
            {"type": OSError, "message": "Read-only file system"},
            {"type": OSError, "message": "Stale file handle"},
            {"type": OSError, "message": "No space left on device"},
            {"type": OSError, "message": "Input/output error"},
            {"type": OSError, "message": "Host is down"},
            {"type": OSError, "message": "Invalid argument"},
            {"type": OSError, "message": "file size changed"},
            {"type": OSError, "message": "文件名、目录名或卷标语法不正确"},
            {"type": PermissionError, "message": "Permission denied"},
            {"type": PermissionError, "message": "Operation not permitted"},
            {"type": FileNotFoundError, "message": "No such file or directory"},
            {"type": NotADirectoryError},
        ]

        self.reload_config()

    def _before_send(self, event, hint):
        """
        Sentry atexit hook
        """
        if "exc_info" in hint and self._ignored_rules:
            _, exc_value, _ = hint["exc_info"]
            error_message = str(exc_value)

            for rule in self._ignored_rules:
                rule_type = rule.get("type")
                rule_message = rule.get("message")

                if not isinstance(exc_value, rule_type):
                    continue

                if rule_message:
                    if rule_message in error_message:
                        return None
                else:
                    return None

        return event

    def reload_config(self):
        """
        根据配置文件动态开启或关闭 Sentry 功能
        """
        is_enabled = configer.get_config("error_info_upload") is not False
        is_real_hub_active = isinstance(self.sentry_hub, Hub) and not isinstance(
            self.sentry_hub, NoopSentryHub
        )

        if is_enabled:
            if is_real_hub_active:
                logger.debug("【Sentry】Sentry is already enabled. No changes made.")
                return

            logger.debug("【Sentry】Enabling Sentry error reporting...")
            self.sentry_hub = Hub(
                Client(
                    dsn=b64decode(
                        "aHR0cHM6Ly9lYjlhNGJkYWMyNDk0MjY4ODYzNTI1Y2VlNTJkMzJmOEBnbGl0Y2h0aXAuZGRzcmVtLmNvbS8y"
                    ).decode("utf-8"),
                    release=f"p115strmhelper@v{VERSION}",
                    default_integrations=False,
                    integrations=[
                        DedupeIntegration(),
                        StdlibIntegration(),
                        ExcepthookIntegration(always_run=True),
                        SqlalchemyIntegration(),
                    ],
                    before_send=self._before_send,
                    transport=CustomHttpTransport,
                )
            )

            with self.sentry_hub.configure_scope() as scope:
                scope.set_tag("moviepilot_version", APP_VERSION)
                logger.debug(f"【Sentry】Set moviepilot_version tag to: {APP_VERSION}")

            if not self._patched:
                self._apply_monkey_patch()
                self._patched = True

        else:
            if not is_real_hub_active:
                logger.debug("【Sentry】Sentry is already disabled. No changes made.")
                return

            logger.debug("【Sentry】Disabling Sentry error reporting...")
            self.sentry_hub = NoopSentryHub()

    def _apply_monkey_patch(self):
        """
        应用猴子补丁，确保只对我们自己的 Hub 上报
        """
        _original_capture_exception = sentry_sdk.capture_exception

        def _patched_capture_exception(*args, **kwargs):
            if Hub.current is self.sentry_hub:
                _original_capture_exception(*args, **kwargs)

        sentry_sdk.capture_exception = _patched_capture_exception

    def capture_plugin_exceptions(self, func):
        """
        函数装饰器，自动捕获函数内部的异常并上报 Sentry

        支持同步和异步函数，被装饰的函数名和来源会被标记到 Sentry 事件中

        :param func (Callable): 要包装的函数
        :return Callable: 包装后的函数
        """
        if getattr(func, "_sentry_captured", False):
            return func

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                """
                包装异步函数，自动捕获并上报异常

                :param args (Tuple): 传递给被装饰函数的位置参数
                :param kwargs (Dict): 传递给被装饰函数的关键字参数
                :return Any: 被装饰函数的返回值
                :raises Exception: 捕获异常后重新抛出
                """
                with self.sentry_hub:
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        with self.sentry_hub.configure_scope() as scope:
                            scope.set_tag("capture_source", "plugin_decorator")
                            scope.set_tag("function_name", func.__name__)
                        self.sentry_hub.capture_exception(e)
                        raise

            async_wrapper._sentry_captured = True  # pylint: disable=W0212,protected-access
            return async_wrapper
        else:

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                """
                包装同步函数，自动捕获并上报异常

                :param args (Tuple): 传递给被装饰函数的位置参数
                :param kwargs (Dict): 传递给被装饰函数的关键字参数
                :return Any: 被装饰函数的返回值
                :raises Exception: 捕获异常后重新抛出
                """
                with self.sentry_hub:
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        with self.sentry_hub.configure_scope() as scope:
                            scope.set_tag("capture_source", "plugin_decorator")
                            scope.set_tag("function_name", func.__name__)
                        self.sentry_hub.capture_exception(e)
                        raise

            wrapper._sentry_captured = True  # pylint: disable=W0212,protected-access
            return wrapper

    def capture_all_class_exceptions(self, cls):
        """
        类装饰器，自动为类中所有公开方法添加 Sentry 异常捕获

        遍历类的公开方法（非下划线开头），为每个方法应用 capture_plugin_exceptions 装饰器，
        同时保留 staticmethod 和 classmethod 的类型

        :param cls (Type): 要包装的类
        :return Type: 包装后的类
        """
        for name, attr in cls.__dict__.items():
            if name.startswith("_"):
                continue

            original_function, is_static, is_class = None, False, False

            if isinstance(attr, staticmethod):
                original_function, is_static = attr.__func__, True
            elif isinstance(attr, classmethod):
                original_function, is_class = attr.__func__, True
            elif inspect.isfunction(attr):
                original_function = attr

            if original_function:
                wrapped_function = self.capture_plugin_exceptions(original_function)

                if is_static:
                    final_method = staticmethod(wrapped_function)
                elif is_class:
                    final_method = classmethod(wrapped_function)
                else:
                    final_method = wrapped_function

                setattr(cls, name, final_method)
        return cls


sentry_manager = SentryManager()
