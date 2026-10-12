import asyncio
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncBaseTransport, AsyncClient, Request, Response

from test_r302_concurrency import _load_r302_module
from test_v3_share_queue_lifecycle import _method


class _Transport(AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests = []
        self.close_loops = []
        self.handler = None
        self.close_error = None

    async def handle_async_request(self, request: Request) -> Response:
        """
        记录真实 HTTPX 请求并使用内存响应替代网络
        """
        self.requests.append(request)
        if self.handler:
            return await self.handler(request)
        return Response(200, json={"ok": True})

    async def aclose(self) -> None:
        """
        记录实际关闭所属循环并注入可控失败
        """
        self.close_loops.append(asyncio.get_running_loop())
        if self.close_error:
            raise self.close_error


class TestV3R302Lifecycle(IsolatedAsyncioTestCase):
    """
    使用真实 HTTPX 连接池验证实例归属和异步关闭反馈
    """

    async def asyncSetUp(self) -> None:
        """
        独立加载 302 模块并替换底层网络传输
        """
        self.module = _load_r302_module()
        self.transports = []
        self.redirects = []
        self.factory = patch.object(self.module, "AsyncClient", self._client)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def _client(self, **kwargs) -> AsyncClient:
        transport = _Transport()
        self.transports.append(transport)
        return AsyncClient(transport=transport, **kwargs)

    def _redirect(self, cookie: str = ""):
        self.module.configer.cookies = cookie
        self.module.configer.cookies_dict = {"UID": cookie} if cookie else {}
        redirect = self.module.Redirect(MagicMock())
        self.redirects.append(redirect)
        return redirect

    async def asyncTearDown(self) -> None:
        """
        收口测试连接池并消费预期的关闭异常
        """
        await asyncio.gather(
            *(redirect.close_http_client() for redirect in self.redirects),
            return_exceptions=True,
        )

    async def test_cookie_snapshots_and_pools_belong_to_each_redirect(self) -> None:
        """
        两个服务对象独立保存 Cookie 和连接池，关闭旧对象不影响新对象
        """
        first = self._redirect("first")
        second = self._redirect("second")
        self.module.configer.cookies_dict = {"UID": "later"}
        await first._request_http("GET", "https://example.invalid/one")
        await second._request_http("GET", "https://example.invalid/two")
        self.assertIsNot(first._http_client, second._http_client)
        self.assertEqual(self.transports[0].requests[0].headers["Cookie"], "UID=first")
        self.assertEqual(self.transports[1].requests[0].headers["Cookie"], "UID=second")
        self.assertFalse(first.close_http_client_sync())
        self.assertTrue(await first.close_http_client())
        self.assertTrue(first.close_http_client_sync())
        with self.assertRaises(RuntimeError):
            await first._request_http("GET", "https://example.invalid/late")
        await second._request_http("POST", "https://example.invalid/next")
        self.assertEqual(len(self.transports[1].requests), 2)
        self.assertEqual(self.transports[1].close_loops, [])

    async def test_close_drains_inflight_request_and_rejects_new_work(self) -> None:
        """
        关闭请求等待已受理 HTTP 完成，重复关闭共用任务且拒绝迟到请求
        """
        redirect = self._redirect()
        redirect.http_client()
        entered, release = asyncio.Event(), asyncio.Event()

        async def response(request):
            entered.set()
            await release.wait()
            return Response(200, text="complete")

        self.transports[0].handler = response
        request = asyncio.create_task(
            redirect._request_http("GET", "https://example.invalid/slow")
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            self.assertFalse(redirect.close_http_client_sync())
            close_future = redirect._http_close_future
            self.assertFalse(redirect.close_http_client_sync())
            self.assertIs(redirect._http_close_future, close_future)
            with self.assertRaises(RuntimeError):
                await redirect._request_http("GET", "https://example.invalid/late")
            self.assertFalse(close_future.done())
            self.assertEqual(self.transports[0].close_loops, [])
        finally:
            release.set()
            result = await request
        self.assertEqual(result.text, "complete")
        self.assertTrue(await redirect.close_http_client())
        self.assertEqual(self.transports[0].close_loops, [asyncio.get_running_loop()])
        self.assertEqual(redirect._http_pending, 0)
        self.assertIsNone(redirect._http_client)

    async def test_cancelled_request_releases_shutdown_wait(self) -> None:
        """
        在途请求取消仍释放计数，关闭等待者取消不撤销连接池关闭任务
        """
        redirect = self._redirect()
        redirect.http_client()
        entered = asyncio.Event()

        async def response(request):
            entered.set()
            await asyncio.Event().wait()

        self.transports[0].handler = response
        request = asyncio.create_task(
            redirect._request_http("GET", "https://example.invalid/cancel")
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            self.assertFalse(redirect.close_http_client_sync())
            close = asyncio.create_task(redirect.close_http_client())
            await asyncio.sleep(0)
            close.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await close
            self.assertFalse(redirect._http_close_future.cancelled())
        finally:
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
        self.assertTrue(await asyncio.wait_for(redirect.close_http_client(), timeout=2))
        self.assertEqual(redirect._http_pending, 0)

    async def test_sync_stop_from_thread_closes_on_owner_loop(self) -> None:
        """
        普通线程同步停止将关闭提交给原事件循环并等待结果
        """
        redirect = self._redirect()
        await redirect._request_http("GET", "https://example.invalid/thread")
        self.assertTrue(await asyncio.to_thread(redirect.close_http_client_sync))
        self.assertEqual(self.transports[0].close_loops, [asyncio.get_running_loop()])

    async def test_close_failure_keeps_handle_and_never_reports_success(self) -> None:
        """
        HTTPX 关闭异常保留原对象和失败结果，不因 is_closed 提前变化冒充成功
        """
        redirect = self._redirect()
        client = redirect.http_client()
        self.transports[0].close_error = OSError("transport close failed")
        with self.assertRaises(OSError):
            await redirect.close_http_client()
        self.assertTrue(client.is_closed)
        self.assertIs(redirect._http_client, client)
        self.assertFalse(redirect.close_http_client_sync())
        self.assertFalse(redirect.close_http_client_sync())
        self.assertEqual(len(self.transports[0].close_loops), 1)
        with self.assertRaises(RuntimeError):
            redirect.http_client()

    async def test_stop_before_first_request_prevents_lazy_revival(self) -> None:
        """
        未创建连接池的对象停止后不被迟到请求复活
        """
        redirect = self._redirect()
        self.assertTrue(redirect.close_http_client_sync())
        with self.assertRaises(RuntimeError):
            redirect.http_client()
        self.assertEqual(self.transports, [])

    async def test_share_search_fallback_uses_managed_requests(self) -> None:
        """
        分享搜索后缀回退的两个实际 GET 请求均走受控连接池
        """
        redirect = self._redirect()
        redirect.http_client()

        async def response(request):
            if "suffix" in request.url.params:
                return Response(200, json={"errno": 20021})
            return Response(
                200,
                json={
                    "state": True,
                    "data": {"count": 1, "list": [{"n": "a.mkv", "fid": 42}]},
                },
            )

        self.transports[0].handler = response
        self.assertEqual(
            await redirect.share_get_id_for_name("share", "receive", "a.mkv"), 42
        )
        self.assertEqual(
            [r.method for r in self.transports[0].requests], ["GET", "GET"]
        )
        self.assertEqual(redirect._http_pending, 0)

    async def test_service_stop_waits_for_pool_close_before_resource_teardown(
        self,
    ) -> None:
        """
        服务关闭在异步连接池尚未关闭时保留资源并允许后续停止重试
        """
        redirect = self._redirect()
        redirect.http_client()
        namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
            )
        }
        stop = _method(
            Path(__file__).resolve().parents[1] / "service/__init__.py",
            "stop",
            namespace,
        )
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[],
            monitor_life_lock=Lock(),
            monitor_life_thread=None,
            monitorlife=None,
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=None,
            monitor_stop_event=None,
            fuse_manager=None,
            redirect=redirect,
            transfer_task_manager=None,
            transfer_handler=None,
        )
        self.assertFalse(stop(service))
        namespace["TransferChainPatcher"].disable.assert_not_called()
        self.assertTrue(await redirect.close_http_client())
        self.assertTrue(stop(service))
        namespace["TransferChainPatcher"].disable.assert_called_once()

    async def test_config_api_keeps_owner_loop_running_during_sync_stop(self) -> None:
        """
        配置保存在线程中等待同步停止，原事件循环能完成连接池关闭
        """
        redirect = self._redirect()
        redirect.http_client()
        config = MagicMock()
        config.validate_updates.return_value = True
        config.update_config.return_value = True
        config.update_plugin_config.return_value = True
        save = _method(
            Path(__file__).resolve().parents[1] / "__init__.py",
            "_save_config_api",
            {
                "configer": config,
                "i18n": MagicMock(),
                "sentry_manager": MagicMock(),
                "to_thread": asyncio.to_thread,
            },
        )
        plugin = SimpleNamespace(
            stop_service=redirect.close_http_client_sync,
            get_config=MagicMock(return_value={}),
            init_plugin=MagicMock(),
        )
        result = await asyncio.wait_for(
            save(plugin, SimpleNamespace(json=AsyncMock(return_value={}))), timeout=2
        )
        self.assertEqual(result["code"], 0)
        self.assertEqual(self.transports[0].close_loops, [asyncio.get_running_loop()])
        plugin.init_plugin.assert_called_once()


class TestV3R302LoopOwnership(TestCase):
    """
    验证停止的原事件循环不会被另一个循环代替
    """

    def test_stopped_owner_loop_retains_pool_until_original_loop_resumes(self) -> None:
        """
        原循环停转时反馈未关闭，恢复原循环后才能释放连接池
        """
        module = _load_r302_module()
        transport = _Transport()
        owner = asyncio.new_event_loop()
        other = asyncio.new_event_loop()
        redirect = module.Redirect(MagicMock())
        try:
            with patch.object(
                module,
                "AsyncClient",
                lambda **kwargs: AsyncClient(transport=transport, **kwargs),
            ):
                owner.run_until_complete(
                    redirect._request_http("GET", "https://example.invalid/owner")
                )
            client = redirect._http_client
            with self.assertRaises(RuntimeError):
                other.run_until_complete(
                    redirect._request_http("GET", "https://example.invalid/other")
                )
            self.assertFalse(redirect.close_http_client_sync())
            self.assertIs(redirect._http_client, client)
            self.assertEqual(transport.close_loops, [])
            self.assertTrue(owner.run_until_complete(redirect.close_http_client()))
            self.assertEqual(transport.close_loops, [owner])
        finally:
            owner.run_until_complete(redirect.close_http_client())
            owner.close()
            other.close()
