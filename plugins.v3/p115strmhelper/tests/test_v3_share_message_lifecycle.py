from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3ShareMessageLifecycle(TestCase):
    """
    验证分享消息解析、分流与队列交接在 V3 停止前保留实例归属
    """

    def setUp(self) -> None:
        """
        加载真实消息入口及同步服务，隔离页面解析和云盘任务边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            ShareLinkResolver=MagicMock(),
            session_manager=MagicMock(),
            Action=SimpleNamespace,
        )
        self.service.sharetransferhelper = MagicMock()
        self.service.share_interactive_gen_strm_queue = MagicMock()
        self.config = self.namespace["configer"]
        self.config.enabled = True
        self.config.share_recieve_paths = ["/share"]
        self.resolver = self.namespace["ShareLinkResolver"]
        self.url = "https://115.com/s/synthetic?password=abcd"
        self.resolver.extract_share_url_from_text.return_value = self.url
        self.resolver.extract_all_u115_share_urls_from_text.return_value = [self.url]
        self.namespace["ShareInteractiveGenStrmQueue"].validate_prerequisites.return_value = (
            None
        )
        self.plugin = SimpleNamespace(
            _get_event_userid=lambda event: "42",
            _share_link_capabilities=MagicMock(return_value=(True, False, None)),
            _render_and_send=MagicMock(),
            action_handler=MagicMock(),
        )
        self.plugin.action_handler.process.return_value = []
        setattr(self.plugin, "__send_message", MagicMock())
        self.root = Path(__file__).resolve().parents[1]
        for name in ("user_add_share", "p115_add_share", "p115_share_strm"):
            setattr(
                self.plugin,
                name,
                MethodType(_method(self.root / "__init__.py", name, self.namespace), self.plugin),
            )

    def _event(self, action: str):
        return SimpleNamespace(
            event_data={
                "action": action,
                "arg_str": self.url,
                "text": self.url,
                "channel": "telegram",
                "source": "isolated",
                "userid": "42",
            }
        )

    def _assert_running(self, name: str, boundary: MagicMock, result=None) -> None:
        self.service._sync_stopping = False
        self.runtime.entered.clear()
        self.runtime.release.clear()
        boundary.reset_mock()

        def hold(*args, **kwargs):
            self.runtime._block()
            return result

        boundary.side_effect = hold
        callback = getattr(self.plugin, name)
        worker = self.runtime._start(lambda: callback(self._event(name)))
        try:
            self.assertTrue(self.runtime.entered.wait(timeout=2))
            client = self.service.client
            stop = self.service._stop_sync_operations
            with patch.object(
                self.service, "_stop_sync_operations", side_effect=lambda: stop(0)
            ):
                self.assertFalse(self.service.stop())
            self.assertFalse(self.service.init_service())
            self.assertIs(self.service.client, client)
            self.service.sharetransferhelper.stop.assert_not_called()
            self.service.share_interactive_gen_strm_queue.stop.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                callback(self._event(name))
            self.assertEqual(boundary.call_count, 1)
        finally:
            self.runtime.release.set()
            worker.join(timeout=2)
            boundary.side_effect = None
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.runtime.errors, [])
        self.assertEqual(self.service._sync_operations, {})

    def test_link_resolution_is_inside_all_three_entry_scopes(self) -> None:
        """
        三个入口解析外部分享页面时不能提前关闭队列或切换配置
        """
        for name, boundary, result in (
            ("user_add_share", self.resolver.extract_share_url_from_text, self.url),
            ("p115_add_share", self.resolver.extract_share_url_from_text, self.url),
            (
                "p115_share_strm",
                self.resolver.extract_all_u115_share_urls_from_text,
                [self.url],
            ),
        ):
            with self.subTest(entry=name):
                self._assert_running(name, boundary, result)

    def test_user_share_branches_remain_tracked_until_handoff(self) -> None:
        """
        双选、仅 STRM、目录选择和直接转存分支覆盖完整交接范围
        """
        queue = self.service.share_interactive_gen_strm_queue
        for capabilities, paths, boundary in (
            ((True, True, self.url), ["/share"], self.plugin._render_and_send),
            ((False, True, self.url), [], queue.enqueue_and_notify_user),
            ((True, False, None), ["/a", "/b"], self.plugin._render_and_send),
            ((True, False, None), ["/share"], self.service.sharetransferhelper.add_share),
            ((False, False, None), [], self.service.sharetransferhelper.add_share),
        ):
            with self.subTest(capabilities=capabilities, paths=paths):
                self.plugin._share_link_capabilities.return_value = capabilities
                self.config.share_recieve_paths = paths
                self._assert_running("user_add_share", boundary)

    def test_remote_batch_keeps_all_links_and_final_notification(self) -> None:
        """
        停止等待时原批量请求继续交接全部链接，最终通知后释放登记
        """
        queue = self.service.share_interactive_gen_strm_queue
        urls = [self.url, "https://115.com/s/second?password=abcd"]
        self.resolver.extract_all_u115_share_urls_from_text.return_value = urls
        observations = []

        def enqueue(**kwargs) -> int:
            observations.append(self.service._stop_sync_operations(timeout=0))
            return len(observations)

        queue.enqueue.side_effect = enqueue
        self._assert_running("p115_share_strm", self.namespace["post_message"])
        self.assertEqual(observations, [False, False])
        self.assertEqual([c.kwargs["share_url"] for c in queue.enqueue.call_args_list], urls)
        self.namespace["i18n"].translate.assert_any_call(
            "p115_share_strm_multi_queued", count=2, pending=2
        )

    def test_remote_menu_and_validation_notification_remain_tracked(self) -> None:
        """
        远程转存目录菜单及原错误提示在完成后才退出作用域
        """
        self.config.share_recieve_paths = ["/a", "/b"]
        self._assert_running("p115_add_share", self.plugin._render_and_send)
        self.resolver.extract_all_u115_share_urls_from_text.return_value = []
        self._assert_running("p115_share_strm", self.namespace["post_message"])
        self.namespace["i18n"].translate.assert_any_call("p115_share_strm_not_u115_error")

    def test_filters_and_resolver_failure_keep_original_behavior(self) -> None:
        """
        无关命令保持跳过，页面解析异常继续上抛并释放登记
        """
        self.service._sync_stopping = True
        for name in ("p115_add_share", "p115_share_strm"):
            callback = getattr(self.plugin, name)
            self.assertIsNone(callback(None))
            self.assertIsNone(callback(self._event("unrelated")))
        self.config.enabled = False
        self.assertIsNone(self.plugin.user_add_share(self._event("user_add_share")))
        self.config.enabled = True
        self.assertIsNone(self.plugin.user_add_share(SimpleNamespace(event_data={"text": ""})))
        self.resolver.extract_share_url_from_text.assert_not_called()
        self.service._sync_stopping = False
        self.resolver.extract_share_url_from_text.side_effect = ValueError("synthetic")
        with self.assertRaisesRegex(ValueError, "synthetic"):
            self.plugin.user_add_share(self._event("user_add_share"))
        self.assertEqual(self.service._sync_operations, {})
