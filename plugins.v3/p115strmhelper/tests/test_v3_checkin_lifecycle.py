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


class TestV3CheckinLifecycle(TestCase):
    """
    验证签到入口在 V3 关停前完成原任务与通知
    """

    _family = "hdhive"
    _label = "RE0"

    def setUp(self) -> None:
        """
        加载真实入口及服务类，隔离签到和宿主资源边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "configer",
                "post_message",
                "BackupService",
                "ShareInteractiveGenStrmQueue",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
                "hdhive_checkin_scheduler_tick",
                "run_hdhive_checkin_once",
                "p115_scheduler_tick",
                "run_p115_checkin_once",
            )
        }
        self.namespace.update(
            wraps=wraps,
            contextmanager=contextmanager,
            Condition=Condition,
            Lock=Lock,
            Thread=Thread,
            current_thread=current_thread,
            monotonic=monotonic,
        )
        path = self.root / "service/__init__.py"
        _method(path, "_track_sync_operation", self.namespace)
        self.service = _compile(path, self.namespace, "ServiceHelper")()
        self.service.client = object()
        self.namespace["servicer"] = self.service
        self.scheduler_global = (
            "p115_scheduler_tick"
            if self._family == "p115"
            else "hdhive_checkin_scheduler_tick"
        )
        self.job_global = f"run_{self._family}_checkin_once"
        self.manual = _method(
            self.root / "__init__.py", f"{self._family}_checkin_manual", self.namespace
        )
        self.plugin = SimpleNamespace(_get_event_userid=lambda event: "user")
        self.event = SimpleNamespace(
            event_data={"action": f"{self._family}_checkin_manual", "channel": "test"}
        )

    def test_running_entries_preserve_resources_until_exit(self) -> None:
        """
        定时与手动任务未结束时拒绝停止和重载，完成后释放登记
        """
        entries = (
            (
                getattr(self.service, f"{self._family}_checkin_scheduler_tick"),
                self.namespace[self.scheduler_global],
                None,
            ),
            (
                lambda: self.manual(self.plugin, self.event),
                self.namespace[self.job_global],
                (True, "synthetic"),
            ),
        )
        for callback, boundary, result in entries:
            with self.subTest(callback=callback):
                self.service._sync_stopping = False
                entered, release = Event(), Event()
                errors = []

                def hold(*args, **kwargs):
                    entered.set()
                    if not release.wait(timeout=5):
                        raise AssertionError("测试未释放签到任务")
                    return result

                def run() -> None:
                    try:
                        self.assertIsNone(callback())
                    except Exception as error:
                        errors.append(error)

                boundary.side_effect = hold
                worker = Thread(target=run)
                worker.start()
                try:
                    self.assertTrue(entered.wait(timeout=2))
                    old_client = self.service.client
                    stop = self.service._stop_sync_operations
                    with patch.object(
                        self.service,
                        "_stop_sync_operations",
                        side_effect=lambda: stop(0),
                    ):
                        self.assertFalse(self.service.stop())
                    self.assertFalse(self.service.init_service())
                    self.assertIs(self.service.client, old_client)
                    self.namespace["directory_upload_queue"].stop.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                        callback()
                finally:
                    release.set()
                    worker.join(timeout=2)
                    boundary.side_effect = None
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(self.service._sync_operations, {})
                boundary.assert_called_once()

    def test_manual_failure_notification_remains_tracked(self) -> None:
        """
        原失败文案和通知结束前的在途归属保持
        """
        self.namespace[self.job_global].return_value = (False, "synthetic")
        observations = []
        self.namespace["post_message"].side_effect = lambda **kwargs: observations.append(
            self.service._stop_sync_operations(timeout=0)
        )
        self.assertIsNone(self.manual(self.plugin, self.event))
        self.assertEqual(observations, [False])
        self.namespace["post_message"].assert_called_once_with(
            channel="test",
            source=None,
            title=f"{self._label} 手动签到失败",
            text="\nsynthetic\n",
            userid="user",
        )
        self.assertEqual(self.service._sync_operations, {})

    def test_unrelated_events_skip_stopped_service(self) -> None:
        """
        无效及无关事件保持原跳过行为，不进入已停止服务
        """
        self.service._sync_stopping = True
        for event in (None, SimpleNamespace(event_data={"action": "unrelated"})):
            self.assertIsNone(self.manual(self.plugin, event))
        self.namespace[self.job_global].assert_not_called()
        self.namespace["post_message"].assert_not_called()


class TestV3P115CheckinLifecycle(TestV3CheckinLifecycle):
    """
    验证 115 签到保留原客户端直到任务和通知退出
    """

    _family = "p115"
    _label = "115"
