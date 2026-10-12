from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3OfflineLifecycle(TestCase):
    """
    验证离线 API、消息及轮询在 V3 关停前完成原提交和整理交接
    """

    def setUp(self) -> None:
        """
        加载真实入口与服务方法，隔离离线请求、通知及存储边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "configer",
                "i18n",
                "post_message",
                "BackupService",
                "ShareInteractiveGenStrmQueue",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
            )
        }
        self.namespace.update(
            wraps=wraps,
            contextmanager=contextmanager,
            Condition=Condition,
            Event=Event,
            Lock=Lock,
            Thread=Thread,
            current_thread=current_thread,
            monotonic=monotonic,
            ApiResponse=lambda **kwargs: SimpleNamespace(**kwargs),
            OfflineTasksData=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        path = self.root / "service/__init__.py"
        _method(path, "_track_sync_operation", self.namespace)
        self.cls = _compile(path, self.namespace, "ServiceHelper")
        self.list_api = _method(self.root / "api.py", "offline_tasks_api", self.namespace)
        self.add_api = _method(
            self.root / "api.py", "add_offline_task_api", self.namespace
        )
        self.message = _method(
            self.root / "__init__.py", "_handle_offline_download", self.namespace
        )
        self.interactive = _method(
            self.root / "interactive/handler.py",
            "handle_offline_download",
            self.namespace,
        )
        self.service = self.cls()
        self.service.client = object()
        self.service.offlinehelper = MagicMock()
        self.namespace["servicer"] = self.service
        self.config = self.namespace["configer"]
        self.config.offline_download_paths = ["/offline"]
        self.config.pan_transfer_paths = "/offline"
        self.config.pan_transfer_enabled = True
        self.plugin = SimpleNamespace(_get_event_userid=lambda event: "user")
        self.session = SimpleNamespace(
            business=SimpleNamespace(offline_download_urls=["magnet:isolated"]),
            message=SimpleNamespace(channel="test", source="isolated", userid="user"),
            view=SimpleNamespace(name="start"),
            go_to=MagicMock(),
        )
        self.release = Event()
        self.workers = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        self.release.set()
        for worker in self.workers:
            worker.join(timeout=2)

    def _entries(self):
        return (
            (
                "poll",
                self.service.offline_status,
                "pull_status_to_task",
                None,
            ),
            (
                "message",
                lambda: self.message(
                    self.plugin, ["magnet:isolated"], {"channel": "test"}, "user"
                ),
                "add_urls_to_transfer",
                (True, 1),
            ),
            (
                "interactive",
                lambda: self.interactive(None, self.session, SimpleNamespace(value=0)),
                "add_urls_to_transfer",
                (True, 1),
            ),
        )

    def test_all_entries_block_stop_and_reinitialization(self) -> None:
        """
        消息提交及轮询入口运行期间保留原客户端与下游队列，拒绝新的调用
        """
        for name, callback, method, result in self._entries():
            with self.subTest(entry=name):
                self.service._sync_stopping = False
                self.release.clear()
                entered = Event()
                errors = []
                helper = self.service.offlinehelper
                helper.reset_mock(side_effect=True)

                def blocked(*args, **kwargs):
                    entered.set()
                    if not self.release.wait(timeout=5):
                        raise AssertionError("测试未释放离线请求")
                    return result

                getattr(helper, method).side_effect = blocked

                def run() -> None:
                    try:
                        callback()
                    except Exception as error:
                        errors.append(error)

                worker = Thread(target=run)
                self.workers.append(worker)
                worker.start()
                self.assertTrue(entered.wait(timeout=2))
                real_stop = self.service._stop_sync_operations
                with patch.object(
                    self.service,
                    "_stop_sync_operations",
                    side_effect=lambda: real_stop(0),
                ):
                    self.assertFalse(self.service.stop())
                self.assertFalse(self.service.init_service())
                self.assertIs(self.service.offlinehelper, helper)
                self.namespace["directory_upload_queue"].stop.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                    callback()
                self.release.set()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(getattr(helper, method).call_count, 1)
                self.assertEqual(self.service._sync_operations, {})

    def test_interactive_path_and_notification_share_one_scope(self) -> None:
        """
        选择非整理目录保持原路径提交，完成通知结束前仍处于在途范围
        """
        self.config.pan_transfer_enabled = False
        helper = self.service.offlinehelper
        helper.add_urls_to_path.return_value = (True, 2)
        observations = []

        def notify(**kwargs) -> None:
            observations.append(self.service._stop_sync_operations(timeout=0))

        self.namespace["post_message"].side_effect = notify
        self.assertIsNone(
            self.interactive(None, self.session, SimpleNamespace(value="0"))
        )
        helper.add_urls_to_path.assert_called_once_with(["magnet:isolated"], "/offline")
        helper.add_urls_to_transfer.assert_not_called()
        self.assertEqual(observations, [False])
        self.assertEqual(self.session.view.name, "close")
        self.assertEqual(self.service._sync_operations, {})

    def test_business_failure_keeps_original_api_response(self) -> None:
        """
        原离线提交失败响应与列表异常传播保持
        """
        self.service.offlinehelper.add_urls_to_transfer.return_value = (False, 0)
        response = self.add_api(SimpleNamespace(links=["magnet:isolated"], path=None))
        self.assertEqual(response.code, -1)
        self.service.offlinehelper.get_cached_data.side_effect = ValueError("offline")
        with self.assertRaisesRegex(ValueError, "offline"):
            self.list_api(SimpleNamespace(page=1, limit=20))
        self.assertEqual(self.service._sync_operations, {})

    def test_stopped_listing_keeps_pagination_and_original_missing_helper(self) -> None:
        """
        停止后的列表保留分页和完整读取，首次未创建助手的原异常不改变
        """
        helper = self.service.offlinehelper
        helper.get_cached_data.return_value = ["first", "second"]
        self.service._sync_stopping = True
        for page, limit, expected in ((1, -1, ["first", "second"]), (2, 1, ["second"])):
            with self.subTest(page=page, limit=limit):
                response = self.list_api(SimpleNamespace(page=page, limit=limit))
                self.assertEqual(response.data.total, 2)
                self.assertEqual(response.data.tasks, expected)
                self.assertTrue(self.service._sync_stopping)
        self.service.offlinehelper = None
        with self.assertRaises(AttributeError):
            self.list_api(SimpleNamespace(page=1, limit=-1))

    def test_stopped_api_preserves_both_submission_paths(self) -> None:
        """
        停止后的原助手仍可接收默认和显式目录的 API 提交
        """
        self.service._sync_stopping = True
        helper = self.service.offlinehelper
        for path, method in ((None, "add_urls_to_transfer"), ("/path", "add_urls_to_path")):
            with self.subTest(path=path):
                helper.reset_mock()
                boundary = getattr(helper, method)
                boundary.return_value = (True, 1)
                response = self.add_api(SimpleNamespace(links=["magnet:isolated"], path=path))
                self.assertIn("1 个新任务已成功添加", response.msg)
                if path:
                    boundary.assert_called_once_with(["magnet:isolated"], path)
                else:
                    boundary.assert_called_once_with(["magnet:isolated"])
                self.assertTrue(self.service._sync_stopping)
