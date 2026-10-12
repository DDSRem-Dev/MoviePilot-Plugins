from collections import defaultdict
from pathlib import Path
from threading import Event, Lock, Thread, Timer, current_thread
from time import monotonic
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3LifeLifecycle(TestCase):
    """
    使用真实后台线程验证生活事件资源的 V3 关停反馈
    """

    def setUp(self) -> None:
        """
        加载实际生活事件类并隔离网盘、媒体服务与消息发送
        """
        self.root = Path(__file__).resolve().parents[1]
        self.namespace = {
            "Lock": Lock,
            "Thread": Thread,
            "Timer": Timer,
            "current_thread": current_thread,
            "monotonic": monotonic,
            "defaultdict": defaultdict,
            "configer": MagicMock(),
            "logger": MagicMock(),
            "AutomatonUtils": MagicMock(),
            "MediaServerRefresh": MagicMock(),
            "StorageChain": MagicMock(),
        }
        self.cls = _compile(
            self.root / "helper/life/client.py", self.namespace, "MonitorLife"
        )
        self.monitor = self.cls(client=object(), mediainfodownloader=object())
        self.entered = Event()
        self.release = Event()
        self.monitor.once_transfer = MagicMock(side_effect=self._hold)
        self.monitor._send_notification = MagicMock(side_effect=self._hold)
        self.addCleanup(self._cleanup)

    def _hold(self, *args) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放生活事件后台线程")

    def _cleanup(self) -> None:
        self.release.set()
        for thread in self.monitor._background_threads:
            if isinstance(thread, Timer):
                thread.cancel()
        self.monitor.stop(timeout=2)

    def test_manual_transfer_keeps_owner_until_exit(self) -> None:
        """
        整理仍在运行时拒绝关停与新任务，完成后可重试且不改变原路径
        """
        self.assertTrue(self.monitor.start_manual_transfer("  /movies  "))
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.monitor.stop(timeout=0))
        self.assertFalse(self.monitor.start_manual_transfer("/another"))
        self.monitor.once_transfer.assert_called_once_with("/movies")
        self.release.set()
        self.assertTrue(self.monitor.stop(timeout=2))
        self.assertTrue(self.monitor.stop(timeout=0))
        replacement = self.cls(client=object(), mediainfodownloader=object())
        replacement.once_transfer = MagicMock()
        self.assertTrue(replacement.start_manual_transfer("/new"))
        self.assertTrue(replacement.stop(timeout=2))
        replacement.once_transfer.assert_called_once_with("/new")

    def test_pending_notification_finishes_without_cancellation(self) -> None:
        """
        原定通知完成前反馈未关停，不取消已有消息或提前发送
        """
        self.monitor._send_notification = MagicMock()
        timer = Timer(60, self.monitor._send_notification)
        with (
            patch.dict(self.namespace, {"Timer": MagicMock(return_value=timer)}),
            patch.object(timer.finished, "wait", side_effect=self._hold),
        ):
            self.monitor._schedule_notification()
            self.assertTrue(self.entered.wait(timeout=2))
            self.assertFalse(self.monitor.stop(timeout=0))
            self.monitor._send_notification.assert_not_called()
            self.release.set()
            self.assertTrue(self.monitor.stop(timeout=2))
        self.monitor._send_notification.assert_called_once_with()

    def test_replaced_timer_cannot_hide_running_notification(self) -> None:
        """
        定时器已进入回调后再安排通知，关停仍等待旧回调结束
        """
        with patch.dict(
            self.namespace, {"Timer": lambda seconds, callback: Timer(0, callback)}
        ):
            self.monitor._schedule_notification()
        self.assertTrue(self.entered.wait(timeout=2))
        old = self.monitor._monitor_life_notification_timer
        with patch.dict(
            self.namespace, {"Timer": lambda seconds, callback: Timer(0, lambda: None)}
        ):
            self.monitor._schedule_notification()
        self.assertFalse(self.monitor.stop(timeout=0))
        self.assertIn(old, self.monitor._background_threads)
        self.release.set()
        self.assertTrue(self.monitor.stop(timeout=2))

    def test_worker_can_request_stop_without_joining_itself(self) -> None:
        """
        任务内部请求关停返回未完成，避免等待当前线程自身
        """
        results = []
        self.monitor.once_transfer.side_effect = lambda path: results.append(
            self.monitor.stop(timeout=0)
        )
        self.assertTrue(self.monitor.start_manual_transfer("/movies"))
        self.assertTrue(self.monitor.stop(timeout=2))
        self.assertEqual(results, [False])

    def test_thread_start_failure_does_not_leave_phantom_work(self) -> None:
        """
        线程启动失败不留下阻止宿主关停的无效句柄
        """
        thread = MagicMock()
        thread.start.side_effect = RuntimeError("thread unavailable")
        with patch.dict(self.namespace, {"Thread": MagicMock(return_value=thread)}):
            with self.assertRaisesRegex(RuntimeError, "thread unavailable"):
                self.monitor.start_manual_transfer("/movies")
        self.assertEqual(self.monitor._background_threads, set())
        self.assertTrue(self.monitor.stop(timeout=0))

    def test_service_retains_dependencies_until_manual_work_exits(self) -> None:
        """
        服务层将未完成状态传给插件，保留数据库、消费队列与整理补丁
        """
        self.assertTrue(self.monitor.start_manual_transfer("/movies"))
        self.assertTrue(self.entered.wait(timeout=2))
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
        stop = _method(self.root / "service/__init__.py", "stop", namespace)
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[],
            monitor_life_lock=Lock(),
            monitor_life_thread=None,
            monitor_stop_event=None,
            monitorlife=self.monitor,
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=None,
            fuse_manager=None,
            redirect=None,
            transfer_task_manager=None,
            transfer_handler=None,
        )
        service.stop = MethodType(stop, service)
        plugin_namespace = {
            name: MagicMock()
            for name in (
                "ct_db_manager",
                "U115Patcher",
                "P115DiskPatcher",
                "AppVerPatcher",
                "upload_notifier",
            )
        }
        plugin_namespace["servicer"] = service
        stop_plugin = _method(
            self.root / "__init__.py", "stop_service", plugin_namespace
        )
        plugin = type("Plugin", (), {"_rename_media_fields_cache": {}})()
        real_stop = self.monitor.stop
        with patch.object(
            self.monitor, "stop", side_effect=lambda: real_stop(timeout=0)
        ):
            self.assertFalse(stop_plugin(plugin))
        plugin_namespace["ct_db_manager"].close_database.assert_not_called()
        namespace["TransferChainPatcher"].disable.assert_not_called()
        namespace["emby_mediainfo_queue"].stop.assert_not_called()
        self.release.set()
        self.assertTrue(stop_plugin(plugin))
        plugin_namespace["ct_db_manager"].close_database.assert_called_once_with()
        namespace["TransferChainPatcher"].disable.assert_called_once_with()
