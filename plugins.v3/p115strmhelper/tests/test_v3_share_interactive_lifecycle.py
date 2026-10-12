from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread, current_thread
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3ShareInteractiveLifecycle(TestCase):
    """
    使用真实线程验证交互分享任务的 V3 关停和下载器归属
    """

    def setUp(self) -> None:
        """
        加载实际队列并隔离生成、下载和通知副作用
        """
        self.root = Path(__file__).resolve().parents[1]
        self.namespace = {
            "Queue": Queue,
            "Empty": Empty,
            "Lock": Lock,
            "Thread": Thread,
            "current_thread": current_thread,
            "sleep": MagicMock(),
            "logger": MagicMock(),
            "post_message": MagicMock(),
            "i18n": MagicMock(),
        }
        cls = _compile(
            self.root / "helper/strm/share/create.py",
            self.namespace,
            "ShareInteractiveGenStrmQueue",
        )
        self.queue = cls()
        self.downloader = object()
        self.queue.bind_mediainfodownloader(self.downloader)
        self.entered = Event()
        self.release = Event()
        self.queue._run_job = MagicMock(side_effect=self._hold)
        self.addCleanup(self._cleanup)

    def _hold(self, **kwargs) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放分享任务")

    def _cleanup(self) -> None:
        self.release.set()
        self.queue.stop(timeout=2)

    def test_pending_jobs_keep_downloader_and_drain_in_order(self) -> None:
        """
        超时保留原下载器和队列，已接受任务按原顺序结束后才能重绑
        """
        self.queue.enqueue("first", "channel", "source", "user")
        self.assertTrue(self.entered.wait(timeout=2))
        worker = self.queue._worker_thread
        self.queue.enqueue("second")
        self.assertFalse(self.queue.stop(timeout=0))
        self.assertFalse(self.queue.stop(timeout=0))
        self.assertIs(self.queue._worker_thread, worker)
        with self.assertRaises(RuntimeError):
            self.queue.bind_mediainfodownloader(object())
        with self.assertRaises(RuntimeError):
            self.queue.enqueue_and_notify_user("late")
        self.namespace["post_message"].assert_not_called()
        self.assertIs(self.queue.mediainfodownloader, self.downloader)
        self.release.set()
        self.assertTrue(self.queue.stop(timeout=2))
        calls = self.queue._run_job.call_args_list
        self.assertEqual(
            [call.kwargs["share_url"] for call in calls], ["first", "second"]
        )
        self.assertEqual(calls[0].kwargs["userid"], "user")
        self.assertEqual(self.namespace["sleep"].call_count, 2)
        self.namespace["sleep"].assert_called_with(2)
        self.assertEqual(self.queue._task_queue.unfinished_tasks, 0)
        replacement = object()
        self.queue.bind_mediainfodownloader(replacement)
        self.queue.enqueue("new")
        self.assertTrue(self.queue.stop(timeout=2))
        self.assertIs(self.queue.mediainfodownloader, replacement)
        self.assertEqual(self.queue._run_job.call_args.kwargs["share_url"], "new")

    def test_active_worker_rejects_rebinding_before_stop(self) -> None:
        """
        活跃任务只能保持原下载器，不能在尚未请求停止时直接换账号
        """
        self.queue.enqueue("first")
        self.assertTrue(self.entered.wait(timeout=2))
        self.queue.bind_mediainfodownloader(self.downloader)
        with self.assertRaises(RuntimeError):
            self.queue.bind_mediainfodownloader(object())

    def test_idle_wait_is_woken_without_changing_task_delay(self) -> None:
        """
        空闲线程收到停止信号立即退出，不必等原有六十秒空闲超时
        """
        original_get = self.queue._task_queue.get
        idle = Event()

        def get_task(*args, **kwargs):
            if self.queue._run_job.call_count:
                idle.set()
            return original_get(*args, **kwargs)

        self.release.set()
        with patch.object(self.queue._task_queue, "get", side_effect=get_task):
            self.queue.enqueue("first")
            self.assertTrue(idle.wait(timeout=2))
            self.assertTrue(self.queue.stop(timeout=2))
        self.namespace["sleep"].assert_called_once_with(2)

    def test_timeout_racing_stop_does_not_strand_sentinel(self) -> None:
        """
        空闲取任务超时与停止交错时仍结算停止信号
        """
        original_get = self.queue._task_queue.get
        timed_out = Event()
        finish_timeout = Event()
        self.addCleanup(finish_timeout.set)
        attempted_timeout = False

        def get_task(*args, **kwargs):
            nonlocal attempted_timeout
            if self.queue._run_job.call_count and not attempted_timeout:
                attempted_timeout = True
                timed_out.set()
                if not finish_timeout.wait(timeout=5):
                    raise AssertionError("测试未释放空闲超时")
                raise Empty
            return original_get(*args, **kwargs)

        self.release.set()
        with patch.object(self.queue._task_queue, "get", side_effect=get_task):
            self.queue.enqueue("first")
            self.assertTrue(timed_out.wait(timeout=2))
            self.assertFalse(self.queue.stop(timeout=0))
            finish_timeout.set()
            self.assertTrue(self.queue.stop(timeout=2))
        self.assertEqual(self.queue._task_queue.unfinished_tasks, 0)

    def test_worker_stop_does_not_wait_for_external_join(self) -> None:
        """
        外部等待线程退出时，任务内部也能请求停止而不互相等待
        """
        results = []

        def stop_inside(**kwargs) -> None:
            self._hold()
            results.append(self.queue.stop(timeout=0))

        self.queue._run_job.side_effect = stop_inside
        self.queue.enqueue("first")
        self.assertTrue(self.entered.wait(timeout=2))
        worker = self.queue._worker_thread
        original_join = worker.join

        def join_worker(*args, **kwargs):
            self.release.set()
            return original_join(*args, **kwargs)

        with patch.object(worker, "join", side_effect=join_worker):
            self.assertTrue(self.queue.stop(timeout=2))
        self.assertEqual(results, [False])

    def test_business_failure_keeps_original_notification_and_settlement(self) -> None:
        """
        单条任务失败仍按原规则通知并继续处理下一条分享
        """
        self.queue._run_job.side_effect = [ValueError("unavailable"), None]
        self.queue._post_user_message = MagicMock()
        self.queue.enqueue("first", "channel", "source", "user")
        self.queue.enqueue("second")
        self.assertTrue(self.queue.stop(timeout=2))
        self.assertEqual(self.queue._run_job.call_count, 2)
        self.queue._post_user_message.assert_called_once()
        self.assertEqual(
            self.queue._post_user_message.call_args.kwargs["userid"], "user"
        )
        self.assertEqual(self.queue._task_queue.unfinished_tasks, 0)

    def test_service_retains_consumers_and_database_until_share_finishes(self) -> None:
        """
        分享未完成时插件保留下游审核队列、整理补丁和实例数据库
        """
        self.queue.enqueue("first")
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
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[],
            monitor_life_lock=Lock(),
            monitor_life_thread=None,
            monitor_stop_event=None,
            monitorlife=None,
            fuse_manager=None,
            redirect=None,
            transfer_task_manager=None,
            transfer_handler=None,
            share_interactive_gen_strm_queue=self.queue,
            sharetransferhelper=None,
        )
        service.stop = MethodType(
            _method(self.root / "service/__init__.py", "stop", namespace), service
        )
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
        plugin.stop_service = MethodType(stop_plugin, plugin)
        plugin_namespace["configer"] = MagicMock()
        initialize = _method(self.root / "__init__.py", "init_plugin", plugin_namespace)
        real_stop = self.queue.stop
        with patch.object(self.queue, "stop", side_effect=lambda: real_stop(timeout=0)):
            self.assertFalse(stop_plugin(plugin))
            with self.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                initialize(plugin, {"cookies": "replacement"})
        plugin_namespace["configer"].update_config.assert_not_called()
        plugin_namespace["ct_db_manager"].close_database.assert_not_called()
        namespace["share_audit_download_queue"].stop.assert_not_called()
        namespace["TransferChainPatcher"].disable.assert_not_called()
        self.release.set()
        self.assertTrue(stop_plugin(plugin))
        plugin_namespace["ct_db_manager"].close_database.assert_called_once_with()
        namespace["share_audit_download_queue"].stop.assert_called_once_with()
