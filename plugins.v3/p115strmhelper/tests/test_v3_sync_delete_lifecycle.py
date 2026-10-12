from copy import deepcopy
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3SyncDeleteLifecycle(TestCase):
    """
    验证同步删除执行与 Webhook 快照交接保留 V3 实例资源
    """

    def setUp(self) -> None:
        """
        加载真实事件入口和同步服务，隔离删除及任务队列边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            deepcopy=deepcopy,
            MediaSyncDelHelper=MagicMock(),
            SyncDelWebhookTask=SimpleNamespace,
        )
        self.config = self.namespace["configer"]
        self.config.sync_del_enabled = True
        self.config.sync_del_notify = False
        self.config.sync_del_source = True
        self.config.sync_del_p115_library_path = "/library=>/cloud"
        self.config.sync_del_p115_force_delete_files = False
        self.plugin = SimpleNamespace()
        root = Path(__file__).resolve().parents[1]
        for name in ("sync_del_by_webhook", "download_file_del_sync"):
            setattr(
                self.plugin,
                name,
                MethodType(_method(root / "__init__.py", name, self.namespace), self.plugin),
            )
        self.event = SimpleNamespace(event_data={"src": "/isolated/file.mkv"})

    def test_running_delete_and_enqueue_reject_stop_and_reload(self) -> None:
        """
        删除在途或 Webhook 入队未返回时拒绝释放数据库及停止下游队列
        """
        for name, boundary in (
            (
                "download_file_del_sync",
                self.namespace["MediaSyncDelHelper"].return_value.download_file_del_sync,
            ),
            ("sync_del_by_webhook", self.namespace["sync_del_webhook_queue"].enqueue),
        ):
            with self.subTest(entry=name):
                self.service._sync_stopping = False
                self.runtime.entered.clear()
                self.runtime.release.clear()
                boundary.side_effect = self.runtime._block
                callback = getattr(self.plugin, name)
                worker = self.runtime._start(lambda: callback(self.event))
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
                    self.namespace["sync_del_webhook_queue"].stop.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                        callback(self.event)
                    self.assertEqual(boundary.call_count, 1)
                finally:
                    self.runtime.release.set()
                    worker.join(timeout=2)
                    boundary.side_effect = None
                self.assertFalse(worker.is_alive())
                self.assertEqual(self.runtime.errors, [])
                self.assertEqual(self.service._sync_operations, {})

    def test_webhook_snapshot_and_original_return_are_preserved(self) -> None:
        """
        Webhook 保留事件深复制、原配置快照和原 None 返回值
        """
        self.event.event_data = {"Item": {"Path": "/isolated/file.mkv"}}
        queue = self.namespace["sync_del_webhook_queue"]
        queue.enqueue.return_value = True
        self.assertIsNone(self.plugin.sync_del_by_webhook(self.event))
        task = queue.enqueue.call_args.args[0]
        self.assertEqual(task.event_data, self.event.event_data)
        self.assertIsNot(task.event_data, self.event.event_data)
        self.event.event_data["Item"]["Path"] = "/changed"
        self.assertEqual(task.event_data["Item"]["Path"], "/isolated/file.mkv")
        self.assertEqual(
            vars(task),
            {
                "event_data": {"Item": {"Path": "/isolated/file.mkv"}},
                "enabled": True,
                "notify": False,
                "del_source": True,
                "p115_library_path": "/library=>/cloud",
                "p115_force_delete_files": False,
            },
        )
        self.assertEqual(self.service._sync_operations, {})

    def test_original_filters_and_exceptions_are_preserved(self) -> None:
        """
        停用与空事件保持跳过，原助手及入队异常继续传播并释放登记
        """
        self.service._sync_stopping = True
        self.config.sync_del_enabled = False
        for name in ("sync_del_by_webhook", "download_file_del_sync"):
            self.assertIsNone(getattr(self.plugin, name)(self.event))
        self.config.sync_del_enabled = True
        self.assertIsNone(self.plugin.download_file_del_sync(None))
        for event in (None, SimpleNamespace(event_data={})):
            self.assertIsNone(self.plugin.sync_del_by_webhook(event))
        self.namespace["MediaSyncDelHelper"].assert_not_called()
        self.namespace["sync_del_webhook_queue"].enqueue.assert_not_called()
        self.service._sync_stopping = False
        for name, boundary in (
            ("download_file_del_sync", self.namespace["MediaSyncDelHelper"]),
            ("sync_del_by_webhook", self.namespace["sync_del_webhook_queue"].enqueue),
        ):
            with self.subTest(entry=name):
                boundary.side_effect = ValueError("synthetic")
                with self.assertRaisesRegex(ValueError, "synthetic"):
                    getattr(self.plugin, name)(self.event)
                self.assertEqual(self.service._sync_operations, {})
