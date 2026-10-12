from functools import wraps
from pathlib import Path
from queue import Empty, Queue
from re import match
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3ShareTransferLifecycle(TestCase):
    """
    验证后台分享与直接转存请求的 V3 实例关停合同
    """

    def setUp(self) -> None:
        """
        保留实际分享处理和线程，仅隔离云盘、识别与通知边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.entered = Event()
        self.release = Event()
        self.threads = []
        self.results = []
        self.errors = []
        self.config = SimpleNamespace(
            share_recieve_paths=["/dest"],
            pan_transfer_unrecognized_path="/unknown",
            get_ios_ua_app=lambda **kwargs: {},
            get_config=lambda key: "mkv" if key == "user_rmt_mediaext" else "srt",
        )
        self.client = MagicMock()
        self.client.share_snap.return_value = {
            "state": True,
            "data": {"shareinfo": {"file_size": 123}},
        }
        self.client.share_receive.return_value = {"state": True}
        self.namespace = {
            "wraps": wraps,
            "Queue": Queue,
            "Empty": Empty,
            "Lock": Lock,
            "Condition": Condition,
            "Thread": Thread,
            "current_thread": current_thread,
            "monotonic": monotonic,
            "match": match,
            "sleep": MagicMock(),
            "logger": MagicMock(),
            "configer": self.config,
            "i18n": MagicMock(),
            "StringUtils": MagicMock(),
            "Ali2115Helper": MagicMock(),
            "ALIYUN_SHARE_URL_MATCH": r"https://www\.alipan\.com/s/.*",
            "share_extract_payload": lambda url: {
                "share_code": url,
                "receive_code": "pass",
            },
            "share_iterdir": MagicMock(return_value=[{"id": 42, "name": "movie.mkv"}]),
            "get_pid_by_path": MagicMock(side_effect=self._resolve_directory),
        }
        path = self.root / "helper/share/__init__.py"
        _method(path, "_track_share_operation", self.namespace)
        self.cls = _compile(path, self.namespace, "ShareTransferHelper")
        self.helper = self.cls(self.client, object())
        self.helper.add_share_recognize_mediainfo = MagicMock(return_value=None)
        self.helper.post_share_info = MagicMock()
        self.helper.send_notify = MagicMock()
        self.addCleanup(self._cleanup)

    def _resolve_directory(self, **kwargs) -> int:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放分享转存")
        return 9

    def _start_call(self, callback) -> Thread:
        def run() -> None:
            try:
                self.results.append(callback())
            except Exception as error:
                self.errors.append(error)

        worker = Thread(target=run)
        self.threads.append(worker)
        worker.start()
        return worker

    def _cleanup(self) -> None:
        self.release.set()
        self.helper.stop(timeout=2)
        for thread in self.threads:
            thread.join(timeout=2)

    def test_queue_drains_accepted_transfers_before_resource_release(self) -> None:
        """
        停止后的既有队列仍完成转存，新入队失败且原客户端继续归属旧实例
        """
        self.helper.add_share("first", "channel", "user", source="source")
        self.assertTrue(self.entered.wait(timeout=2))
        worker = self.helper._add_share_worker_thread
        self.helper.add_share("second", None, None)
        self.assertFalse(self.helper.stop(timeout=0))
        self.assertFalse(self.helper.stop(timeout=0))
        self.assertIs(self.helper._add_share_worker_thread, worker)
        self.assertIs(self.helper.client, self.client)
        with self.assertRaises(RuntimeError):
            self.helper.add_share("late", None, None)
        with self.assertRaises(RuntimeError):
            self.helper.add_share_115("late-api")
        self.release.set()
        self.assertTrue(self.helper.stop(timeout=2))
        self.assertFalse(worker.is_alive())
        payloads = [call.args[0] for call in self.client.share_receive.call_args_list]
        self.assertEqual([item["share_code"] for item in payloads], ["first", "second"])
        self.assertTrue(
            all(item["cid"] == 9 and item["file_id"] == "42" for item in payloads)
        )
        self.assertEqual(self.helper._add_share_queue.unfinished_tasks, 0)
        self.assertEqual(self.helper._active_operations, {})
        self.assertEqual(
            [call.args[0] for call in self.namespace["sleep"].call_args_list],
            [2, 3, 2, 3],
        )
        replacement = self.cls(object(), None)
        self.assertFalse(replacement._stopping)
        self.assertTrue(replacement.stop(timeout=0))

    def test_direct_115_call_is_waited_and_keeps_original_result(self) -> None:
        """
        没有队列线程的 HTTP 直接转存也阻止提前关停，并保留成功元组
        """
        thread = self._start_call(
            lambda: self.helper.add_share_115("direct", notify=False)
        )
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertIsNone(self.helper._add_share_worker_thread)
        self.assertFalse(self.helper.stop(timeout=0))
        self.release.set()
        self.assertTrue(self.helper.stop(timeout=2))
        thread.join(timeout=2)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results, [(True, None, "/dest", 9)])
        self.helper.send_notify.assert_not_called()
        self.assertEqual(self.helper._active_operations, {})

    def test_direct_aliyun_operation_is_also_waited(self) -> None:
        """
        阿里分享下游秒传完成前保持客户端和配置归属
        """
        ali = self.namespace["Ali2115Helper"].return_value
        ali.extract_share_code_from_url.return_value = "ali-code"
        ali.share_recognize_mediainfo.return_value = None
        ali.share_upload.return_value = (True, "", 1, 0)
        thread = self._start_call(
            lambda: self.helper.add_share_aliyunpan("https://www.alipan.com/s/ali-code")
        )
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.helper.stop(timeout=0))
        self.release.set()
        self.assertTrue(self.helper.stop(timeout=2))
        thread.join(timeout=2)
        self.assertEqual(self.errors, [])
        ali.share_upload.assert_called_once()
        self.assertEqual(
            ali.share_upload.call_args.kwargs["rmt_mediaext"], [".mkv", ".srt"]
        )

    def test_failed_direct_call_releases_operation_without_changing_exception(
        self,
    ) -> None:
        """
        直接转存异常传播保持原样，失败后不遗留关停计数
        """
        self.release.set()
        self.client.share_receive.side_effect = ValueError("remote failure")
        with self.assertRaisesRegex(ValueError, "remote failure"):
            self.helper.add_share_115("direct")
        self.assertEqual(self.helper._active_operations, {})
        self.assertTrue(self.helper.stop(timeout=0))

    def test_worker_and_direct_caller_can_request_stop_without_self_wait(self) -> None:
        """
        后台任务与直接请求内部停止都返回未完成而不等待自身
        """
        results = []
        self.release.set()
        self.namespace["get_pid_by_path"].side_effect = lambda **kwargs: (
            results.append(self.helper.stop(timeout=0)) or 9
        )
        self.helper.add_share("queued", None, None)
        self.assertTrue(self.helper.stop(timeout=2))
        self.assertEqual(results, [False])
        self.helper = self.cls(self.client, None)
        self.helper.add_share_recognize_mediainfo = MagicMock(return_value=None)
        self.helper.post_share_info = MagicMock()
        self.helper.send_notify = MagicMock()
        self.helper.add_share_115("direct")
        self.assertTrue(self.helper.stop(timeout=0))
        self.assertEqual(results, [False, False])

    def test_service_retains_database_and_config_while_direct_transfer_runs(
        self,
    ) -> None:
        """
        直接请求未完成时服务不释放数据库或发布新配置
        """
        thread = self._start_call(lambda: self.helper.add_share_115("direct"))
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
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=self.helper,
        )
        service.stop = MethodType(
            _method(self.root / "service/__init__.py", "stop", namespace), service
        )
        plugin_namespace = {
            name: MagicMock()
            for name in (
                "ct_db_manager",
                "configer",
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
        initialize = _method(self.root / "__init__.py", "init_plugin", plugin_namespace)
        plugin = type("Plugin", (), {"_rename_media_fields_cache": {}})()
        plugin.stop_service = MethodType(stop_plugin, plugin)
        real_stop = self.helper.stop
        with patch.object(
            self.helper, "stop", side_effect=lambda: real_stop(timeout=0)
        ):
            self.assertFalse(plugin.stop_service())
            with self.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                initialize(plugin, {"cookies": "new-account"})
        plugin_namespace["ct_db_manager"].close_database.assert_not_called()
        plugin_namespace["configer"].update_config.assert_not_called()
        namespace["share_audit_download_queue"].stop.assert_not_called()
        self.release.set()
        self.assertTrue(plugin.stop_service())
        thread.join(timeout=2)
        self.assertEqual(self.errors, [])
        plugin_namespace["ct_db_manager"].close_database.assert_called_once_with()
