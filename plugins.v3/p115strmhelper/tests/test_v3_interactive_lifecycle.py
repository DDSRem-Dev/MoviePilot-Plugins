from copy import deepcopy
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3InteractiveLifecycle(TestCase):
    """
    验证搜索与按钮回调在 V3 停用前完成原业务及消息处理
    """

    def setUp(self) -> None:
        """
        加载真实入口和同步服务，隔离搜索、浏览器与发送边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            deepcopy=deepcopy,
            Action=SimpleNamespace,
            is_hdhive_search_ready=MagicMock(return_value=True),
            session_manager=MagicMock(),
            strm_cleanup_interaction=MagicMock(),
            decode_action=MagicMock(return_value=("session", object())),
            sleep=MagicMock(),
        )
        self.namespace["strm_cleanup_interaction"].try_handle_message_action.return_value = (
            False
        )
        self.session = MagicMock()
        self.session.view.name = "search_list"
        self.session.get_delete_message_data.return_value = {"message_id": "original"}
        manager = self.namespace["session_manager"]
        manager.get_or_create.return_value = self.session
        manager.get.return_value = self.session
        self.plugin = SimpleNamespace(
            _get_event_userid=lambda event: "42",
            action_handler=MagicMock(),
            view_renderer=MagicMock(),
            post_message=MagicMock(),
        )
        self.plugin.action_handler.process.return_value = []
        setattr(self.plugin, "__send_message", MagicMock())
        setattr(self.plugin, "__delete_message", MagicMock())
        root = Path(__file__).resolve().parents[1]
        for name in ("p115_search", "message_action", "_render_and_send"):
            setattr(
                self.plugin,
                name,
                MethodType(_method(root / "__init__.py", name, self.namespace), self.plugin),
            )
        self.event = SimpleNamespace(
            event_data={
                "action": "p115_search",
                "arg_str": " synthetic ",
                "plugin_id": type(self.plugin).__name__,
                "text": "session|c:rs|v:0",
                "channel": "telegram",
                "userid": "42",
            }
        )

    def _assert_running(self, name: str, boundary: MagicMock) -> None:
        self.service._sync_stopping = False
        self.runtime.entered.clear()
        self.runtime.release.clear()
        callback = getattr(self.plugin, name)
        boundary.reset_mock()
        boundary.side_effect = self.runtime._block
        worker = self.runtime._start(lambda: callback(self.event))
        try:
            self.assertTrue(self.runtime.entered.wait(timeout=2))
            old_client = self.service.client
            stop = self.service._stop_sync_operations
            with patch.object(
                self.service, "_stop_sync_operations", side_effect=lambda: stop(0)
            ):
                self.assertFalse(self.service.stop())
            self.assertFalse(self.service.init_service())
            self.assertIs(self.service.client, old_client)
            self.namespace["directory_upload_queue"].stop.assert_not_called()
            if name == "p115_search":
                with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                    callback(self.event)
            else:
                self.assertIsNone(callback(self.event))
            self.assertEqual(boundary.call_count, 1)
        finally:
            self.runtime.release.set()
            worker.join(timeout=2)
            boundary.side_effect = None
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.runtime.errors, [])
        self.assertEqual(self.service._sync_operations, {})

    def test_search_processing_render_and_send_keep_resources(self) -> None:
        """
        搜索处理、资源获取及结果发送期间拒绝释放或重绑服务
        """
        for boundary in (
            self.plugin.action_handler.process,
            self.plugin.view_renderer.render,
            getattr(self.plugin, "__send_message"),
        ):
            with self.subTest(boundary=boundary):
                self._assert_running("p115_search", boundary)

    def test_button_processing_render_and_final_delete_keep_resources(self) -> None:
        """
        按钮业务、资源视图与结束会话后的延迟删除均保留在途归属
        """
        self.session.view.name = "close"
        for boundary in (
            self.plugin.action_handler.process,
            self.plugin.view_renderer.render,
            self.namespace["sleep"],
            getattr(self.plugin, "__delete_message"),
        ):
            with self.subTest(boundary=boundary):
                self._assert_running("message_action", boundary)
        self.namespace["session_manager"].end.assert_called_with(self.session.session_id)
        getattr(self.plugin, "__delete_message").assert_called_with(message_id="original")
        self.namespace["sleep"].assert_called_with(5)

    def test_search_validation_and_expired_session_notifications_are_tracked(self) -> None:
        """
        原配置错误与过期会话提示在发送完成后才释放登记
        """
        self.namespace["configer"].tg_search_channels = []
        self.namespace["is_hdhive_search_ready"].return_value = False
        self._assert_running("p115_search", self.namespace["post_message"])
        self.namespace["session_manager"].get.return_value = None
        self._assert_running("message_action", self.plugin.post_message)
        self.plugin.post_message.assert_called_once_with(
            channel="telegram",
            source=None,
            userid="42",
            original_message_id=None,
            original_chat_id=None,
            title="⚠️ 会话已过期",
            text="操作已超时。\n请重新发起 `/sh` 命令。",
        )

    def test_original_errors_release_scope_and_keep_handling(self) -> None:
        """
        原搜索及按钮异常继续由原日志分支处理，并结算在途登记
        """
        self.plugin.action_handler.process.side_effect = ValueError("synthetic")
        for name, log in (("p115_search", "error"), ("message_action", "debug")):
            with self.subTest(entry=name):
                self.assertIsNone(getattr(self.plugin, name)(self.event))
                getattr(self.namespace["logger"], log).assert_called_once()
                self.assertEqual(self.service._sync_operations, {})
        self.plugin.view_renderer.render.assert_not_called()

    def test_foreign_events_skip_stopped_service(self) -> None:
        """
        空搜索事件、其他动作和其他插件按钮保持原跳过行为
        """
        self.service._sync_stopping = True
        for event in (None, SimpleNamespace(event_data={"action": "other"})):
            self.assertIsNone(self.plugin.p115_search(event))
        for key in ("plugin_id", "__mp_target_plugin_id"):
            self.assertIsNone(
                self.plugin.message_action(SimpleNamespace(event_data={key: "foreign"}))
            )
        self.plugin.action_handler.process.assert_not_called()
        self.namespace["logger"].debug.assert_not_called()
        self.namespace["strm_cleanup_interaction"].try_handle_message_action.assert_not_called()
