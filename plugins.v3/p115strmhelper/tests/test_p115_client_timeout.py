"""
P115 客户端请求超时测试模块
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch


def get_request() -> Any:
    """
    模拟新版 P115 客户端默认请求函数

    :return Any: urllib3-future 请求函数
    """
    from urllib3_future_request import request

    return request


def _get_httpcore_request() -> Any:
    """
    模拟旧版 P115 客户端默认请求函数

    :return Any: HTTPCore 请求函数
    """
    from httpcore_request import request

    return request


class FakeP115Client:
    """
    假 P115 客户端
    """

    def request(self, **kwargs: Any) -> Any:
        """
        模拟客户端请求入口

        :param kwargs (Any): 请求参数

        :return Any: 请求参数
        """
        return kwargs

    def fs_copy(self, *args: Any, **kwargs: Any) -> Any:
        """
        模拟复制文件

        :param args (Any): 位置参数
        :param kwargs (Any): 关键字参数

        :return Any: 调用参数
        """
        return args, kwargs


def _load_timeout_module() -> Any:
    """
    使用假 P115 客户端加载超时模块

    :return Any: 已加载模块
    """
    p115client = ModuleType("p115client")
    p115client.P115Client = FakeP115Client
    module_path = Path(__file__).resolve().parents[1] / "core" / "p115_client.py"
    spec = importlib.util.spec_from_file_location(
        "p115_client_timeout_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"p115client": p115client}):
        spec.loader.exec_module(module)
    return module


class TestP115ClientTimeout(TestCase):
    """
    测试 P115 客户端请求超时注入
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载待测模块
        """
        cls.module = _load_timeout_module()

    def test_wrapper_injects_backend_timeout_keyword(self) -> None:
        """
        包装器向请求后端注入顶层 timeout 参数
        """
        client = FakeP115Client()
        client.fs_copy = MagicMock(return_value={"state": True})
        wrapped = self.module.create_client_with_timeout(
            client,
            default_timeout={"connect": 10, "read": 20},
        )
        request_timeout = object()

        with (
            patch.object(
                self.module, "_detect_timeout_style", return_value="urllib3_future"
            ),
            patch.object(
                self.module,
                "_build_request_timeout",
                return_value={"timeout": request_timeout, "pool_timeout": 15},
            ),
        ):
            wrapped.fs_copy([1], pid=2)

        client.fs_copy.assert_called_once_with(
            [1], pid=2, timeout=request_timeout, pool_timeout=15
        )

    def test_detects_default_backend_across_p115client_versions(self) -> None:
        """
        根据 P115 客户端默认请求函数识别新旧超时方式
        """
        self.module._DEFAULT_TIMEOUT_STYLE = None
        self.assertEqual(self.module._detect_timeout_style(), "urllib3_future")

        with patch.dict(
            FakeP115Client.request.__globals__, {"get_request": _get_httpcore_request}
        ):
            self.module._DEFAULT_TIMEOUT_STYLE = None
            self.assertEqual(self.module._detect_timeout_style(), "extensions")

        self.module._DEFAULT_TIMEOUT_STYLE = None

    def test_urllib3_future_timeout_includes_pool_and_supported_limits(self) -> None:
        """
        urllib3-future 注入连接池超时和后端支持的请求超时
        """
        timeout_class = MagicMock(return_value=object())
        urllib3_future = ModuleType("urllib3_future")
        urllib3_future.__path__ = []
        urllib3_future_util = ModuleType("urllib3_future.util")
        urllib3_future_util.Timeout = timeout_class

        with patch.dict(
            sys.modules,
            {
                "urllib3_future": urllib3_future,
                "urllib3_future.util": urllib3_future_util,
            },
        ):
            request_timeout = self.module._build_request_timeout(
                {"connect": 10, "pool": 15, "read": 20, "write": 25},
                "urllib3_future",
            )

        timeout_class.assert_called_once_with(connect=10, read=20, total=30)
        self.assertEqual(request_timeout["pool_timeout"], 15)
        self.assertIs(request_timeout["timeout"], timeout_class.return_value)

    def test_urllib3_future_uses_write_when_timeout_supports_it(self) -> None:
        """
        urllib3-future 支持 write 参数时自动注入写入超时
        """

        class FutureTimeout:
            """
            模拟支持写入超时的 Timeout
            """

            def __init__(
                self,
                total: Any = None,
                connect: Any = None,
                read: Any = None,
                write: Any = None,
            ) -> None:
                self.write = write

        urllib3_future = ModuleType("urllib3_future")
        urllib3_future.__path__ = []
        urllib3_future_util = ModuleType("urllib3_future.util")
        urllib3_future_util.Timeout = FutureTimeout

        with patch.dict(
            sys.modules,
            {
                "urllib3_future": urllib3_future,
                "urllib3_future.util": urllib3_future_util,
            },
        ):
            request_timeout = self.module._build_request_timeout(
                {"connect": 10, "pool": 15, "read": 20, "write": 25},
                "urllib3_future",
            )

        self.assertEqual(request_timeout["timeout"].write, 25)

    def test_requests_omits_unsupported_pool_and_write_timeouts(self) -> None:
        """
        Requests 后端仅构建其支持的连接和读取超时
        """
        request_timeout = self.module._build_request_timeout(
            {"connect": 10, "pool": 15, "read": 20, "write": 25},
            "requests",
        )

        self.assertEqual(request_timeout, {"timeout": (10, 20)})

    def test_wrapper_uses_extensions_for_httpx_backend(self) -> None:
        """
        HTTPX 后端使用 extensions timeout 参数
        """

        def httpx_request(**kwargs: Any) -> Any:
            """
            模拟 HTTPX 请求函数

            :param kwargs (Any): 请求参数

            :return Any: 请求参数
            """
            return kwargs

        httpx_request.__module__ = "httpx_request"
        client = FakeP115Client()
        client.fs_copy = MagicMock(return_value={"state": True})
        wrapped = self.module.create_client_with_timeout(
            client,
            default_timeout={
                "connect": 10,
                "pool": 15,
                "read": 20,
                "write": 25,
            },
        )

        wrapped.fs_copy([1], pid=2, request=httpx_request)

        client.fs_copy.assert_called_once_with(
            [1],
            pid=2,
            request=httpx_request,
            extensions={
                "timeout": {
                    "connect": 10,
                    "pool": 15,
                    "read": 20,
                    "write": 25,
                }
            },
        )

    def test_wrapper_preserves_explicit_timeout(self) -> None:
        """
        包装器保留调用方显式传入的 timeout 参数
        """
        client = FakeP115Client()
        client.fs_copy = MagicMock(return_value={"state": True})
        wrapped = self.module.create_client_with_timeout(
            client,
            default_timeout={"connect": 10, "read": 20},
        )

        wrapped.fs_copy([1], pid=2, timeout=5)

        client.fs_copy.assert_called_once_with([1], pid=2, timeout=5)

    def test_explicit_request_timeout_keeps_pool_timeout(self) -> None:
        """
        显式请求超时不影响独立的连接池超时注入
        """
        kwargs = {"timeout": 5}

        with (
            patch.object(
                self.module, "_detect_timeout_style", return_value="urllib3_future"
            ),
            patch.object(
                self.module,
                "_build_request_timeout",
                return_value={"timeout": object(), "pool_timeout": 15},
            ),
        ):
            self.module._inject_timeout(
                kwargs,
                {"connect": 10, "pool": 15, "read": 20},
            )

        self.assertEqual(kwargs, {"timeout": 5, "pool_timeout": 15})
