"""
302 跳转并发缓存测试模块
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from threading import Lock as ThreadLock
from time import sleep
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, Optional, Tuple
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock


_PICKCODE = "a1b2c3d4e5f6g7h8i"
_DOWNLOAD_URL = "https://example.com/video.mp4?t=4102444800"


class _Url(str):
    def __new__(cls, value: str, data: Optional[Dict[str, Any]] = None) -> "_Url":
        instance = super().__new__(cls, value)
        instance.data = data or {}
        return instance

    @classmethod
    def of(cls, value: str, data: Dict[str, Any]) -> "_Url":
        return cls(value, data)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self.data[key]
        return super().__getitem__(key)


class _Cache:
    def __init__(self) -> None:
        self.data: Dict[Tuple[str, str], str] = {}
        self.set_calls = 0

    async def get(self, pickcode: str, cache_ua: str) -> Optional[str]:
        return self.data.get((pickcode, cache_ua))

    async def set(
        self, pickcode: str, cache_ua: str, url: str, expires_time: int
    ) -> None:
        self.data[(pickcode, cache_ua)] = url
        self.set_calls += 1

    async def count_by_pick_code(self, pickcode: str) -> int:
        return sum(key[0] == pickcode for key in self.data)

    def clear(self) -> None:
        self.data.clear()
        self.set_calls = 0


class _OpenDownloader:
    def __init__(self) -> None:
        self.calls = 0
        self._calls_lock = ThreadLock()

    def get_download_url(self, pickcode: str, user_agent: str) -> str:
        with self._calls_lock:
            self.calls += 1
        sleep(0.03)
        return _DOWNLOAD_URL


class _CookieHttpClient:
    def __init__(self) -> None:
        self.calls = 0

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(0.03)
        return SimpleNamespace(content=b'{"state":true,"data":"encrypted"}')


class _ShareClientUrl(str):
    def __new__(cls) -> "_ShareClientUrl":
        instance = super().__new__(cls, _DOWNLOAD_URL)
        instance.id = 1
        instance.name = "video.mp4"
        instance.size = 1024
        instance.sha1 = "sha1"
        return instance


class _ShareClient:
    def __init__(self) -> None:
        self.calls = 0

    async def share_download_url(self, *args: Any, **kwargs: Any) -> _ShareClientUrl:
        self.calls += 1
        await asyncio.sleep(0.03)
        return _ShareClientUrl()


class _InvalidReceiveCodeError(Exception):
    def __init__(self) -> None:
        super().__init__("invalid receive code")
        self.message = {"errno": 4100008}


class _RefreshingShareClient(_ShareClient):
    async def share_download_url(
        self, payload: Dict[str, Any], **kwargs: Any
    ) -> _ShareClientUrl:
        self.calls += 1
        await asyncio.sleep(0.03)
        if payload["receive_code"] == "old":
            raise _InvalidReceiveCodeError()
        return _ShareClientUrl()


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []
    return module


def _load_r302_module() -> Any:
    original_modules: Dict[str, Optional[ModuleType]] = {}

    def install(name: str, module: ModuleType) -> None:
        original_modules[name] = sys.modules.get(name)
        sys.modules[name] = module

    for package_name in (
        "app",
        "p115client",
        "p115strmhelper",
        "p115strmhelper.core",
        "p115strmhelper.helper",
        "p115strmhelper.utils",
    ):
        install(package_name, _package(package_name))

    log_module = ModuleType("app.log")
    log_module.logger = MagicMock()
    install("app.log", log_module)

    cipher_module = ModuleType("p115cipher")
    cipher_module.rsa_encrypt = lambda value: b"encrypted"
    cipher_module.rsa_decrypt = lambda value: (
        b'{"url":"https://example.com/video.mp4?t=4102444800"}'
    )
    install("p115cipher", cipher_module)

    p115client_module = sys.modules["p115client"]
    p115client_module.P115Client = MagicMock
    p115client_module.check_response = lambda response: response

    exception_module = ModuleType("p115client.exception")
    exception_module.P115OSError = OSError
    install("p115client.exception", exception_module)

    pickcode_module = ModuleType("p115pickcode")
    pickcode_module.to_id = lambda pickcode: 1
    install("p115pickcode", pickcode_module)

    open_module = ModuleType("p115strmhelper.core.u115_open")
    open_module.U115OpenHelper = MagicMock
    install("p115strmhelper.core.u115_open", open_module)

    config_module = ModuleType("p115strmhelper.core.config")
    config_module.configer = SimpleNamespace(
        cookies="",
        get_config=lambda name: False,
    )
    install("p115strmhelper.core.config", config_module)

    cache_module = ModuleType("p115strmhelper.core.cache")
    cache_module.r302cacher = _Cache()
    install("p115strmhelper.core.cache", cache_module)

    http_module = ModuleType("p115strmhelper.utils.http")
    http_module.check_response = lambda response: response
    install("p115strmhelper.utils.http", http_module)

    url_module = ModuleType("p115strmhelper.utils.url")
    url_module.Url = _Url
    install("p115strmhelper.utils.url", url_module)

    sentry_module = ModuleType("p115strmhelper.utils.sentry")
    sentry_module.sentry_manager = SimpleNamespace(
        capture_all_class_exceptions=lambda cls: cls
    )
    install("p115strmhelper.utils.sentry", sentry_module)

    module_path = (
        Path(__file__).resolve().parents[1] / "helper" / "r302" / "__init__.py"
    )
    module_name = "p115strmhelper.helper.r302"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    install(module_name, module)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


r302_module = _load_r302_module()


class TestR302Concurrency(IsolatedAsyncioTestCase):
    """
    测试 302 跳转下载地址的并发缓存行为
    """

    async def asyncSetUp(self) -> None:
        """
        重置缓存和日志
        """
        r302_module.r302cacher.clear()
        r302_module.logger.reset_mock()

    async def test_open_mode_coalesces_concurrent_cache_misses(self) -> None:
        """
        Open 模式同键并发未命中时只请求一次 115
        """
        redirect = r302_module.Redirect(MagicMock())
        downloader = _OpenDownloader()
        redirect.u115openhelper = downloader

        urls = await asyncio.gather(
            *(redirect.get_downurl_open(_PICKCODE, "Emby") for _ in range(6))
        )

        self.assertEqual(downloader.calls, 1)
        self.assertEqual(r302_module.r302cacher.set_calls, 1)
        self.assertEqual(urls, [_DOWNLOAD_URL] * 6)
        self.assertFalse(redirect._downurl_locks)
        r302_module.logger.info.assert_called_once_with(
            f"【302跳转服务】从 115 获取下载地址成功: {_PICKCODE} video.mp4"
        )

    async def test_cookie_mode_coalesces_concurrent_cache_misses(self) -> None:
        """
        Cookie 模式同键并发未命中时只请求一次 115
        """
        redirect = r302_module.Redirect(MagicMock())
        http_client = _CookieHttpClient()
        redirect.http_client = lambda: http_client

        urls = await asyncio.gather(
            *(redirect.get_downurl_cookie(_PICKCODE, "Emby") for _ in range(6))
        )

        self.assertEqual(http_client.calls, 1)
        self.assertEqual(r302_module.r302cacher.set_calls, 1)
        self.assertEqual(urls, [_DOWNLOAD_URL] * 6)
        self.assertFalse(redirect._downurl_locks)

    async def test_different_user_agents_use_independent_requests(self) -> None:
        """
        不同 User-Agent 保持独立缓存和请求
        """
        redirect = r302_module.Redirect(MagicMock())
        downloader = _OpenDownloader()
        redirect.u115openhelper = downloader

        await asyncio.gather(
            redirect.get_downurl_open(_PICKCODE, "Emby"),
            redirect.get_downurl_open(_PICKCODE, "FFmpeg"),
        )

        self.assertEqual(downloader.calls, 2)
        self.assertEqual(r302_module.r302cacher.set_calls, 2)
        self.assertFalse(redirect._downurl_locks)

    async def test_share_mode_coalesces_concurrent_cache_misses(self) -> None:
        """
        分享模式同键并发未命中时只请求一次 115
        """
        client = _ShareClient()
        redirect = r302_module.Redirect(client)

        urls = await asyncio.gather(
            *(redirect.get_share_downurl("share", "code", 1, "Emby") for _ in range(6))
        )

        self.assertEqual(client.calls, 1)
        self.assertEqual(r302_module.r302cacher.set_calls, 1)
        self.assertEqual(urls, [_DOWNLOAD_URL] * 6)
        self.assertFalse(redirect._downurl_locks)
        r302_module.logger.info.assert_called_once_with(
            "【302跳转服务】从 115 获取分享下载地址成功: share 1 video.mp4"
        )

    async def test_share_receive_code_refresh_coalesces_old_key_waiters(self) -> None:
        """
        分享接收码刷新后复用结果并回填原缓存键
        """
        client = _RefreshingShareClient()
        redirect = r302_module.Redirect(client)
        redirect.get_receive_code = AsyncMock(return_value="new")

        urls = await asyncio.gather(
            *(redirect.get_share_downurl("share", "old", 1, "Emby") for _ in range(6))
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(r302_module.r302cacher.set_calls, 2)
        self.assertEqual(urls, [_DOWNLOAD_URL] * 6)
        self.assertFalse(redirect._downurl_locks)
        redirect.get_receive_code.assert_awaited_once_with("share")

    async def test_cancelled_waiter_releases_lock_reference(self) -> None:
        """
        等待任务取消后清理按键锁引用
        """
        redirect = r302_module.Redirect(MagicMock())
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_lock() -> None:
            async with redirect._acquire_downurl_lock(_PICKCODE, "Emby"):
                entered.set()
                await release.wait()

        holder = asyncio.create_task(hold_lock())
        await entered.wait()
        waiter = asyncio.create_task(
            redirect._acquire_downurl_lock(_PICKCODE, "Emby").__aenter__()
        )
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter

        release.set()
        await holder
        self.assertFalse(redirect._downurl_locks)
