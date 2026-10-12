from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from types import MethodType
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3SyncLifecycle(TestCase):
    """
    验证同步生产者退出前保留 V3 实例资源及原待执行全量任务
    """

    def setUp(self) -> None:
        """
        加载真实服务类，隔离扫描、云盘、通知与数据库边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.entered = Event()
        self.release = Event()
        self.threads = []
        self.results = []
        self.errors = []
        self.namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "configer",
                "i18n",
                "post_message",
                "MessageType",
                "BackupService",
                "Cleaner",
                "ShareInteractiveGenStrmQueue",
                "FullSyncStrmHelper",
                "IncrementSyncStrmHelper",
                "ShareStrmHelper",
                "share_strm_cleaner",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
                "create_client",
                "MediaInfoDownloader",
                "MonitorLife",
                "ShareTransferHelper",
                "OfflineDownloadHelper",
                "Redirect",
                "FuseManager",
                "WebdavCore",
                "BAligo",
                "get_pid_by_path",
            )
        }
        self.namespace.update(
            wraps=wraps,
            contextmanager=contextmanager,
            Thread=Thread,
            Condition=Condition,
            Lock=Lock,
            current_thread=current_thread,
            monotonic=monotonic,
            Path=Path,
        )
        self.namespace["configer"].get_config.return_value = "/synthetic"
        self.namespace["configer"].fuse_enabled = False
        full = self.namespace["FullSyncStrmHelper"].return_value
        full.get_generate_total.return_value = (1, 2, 0, 0, 0, 0)
        inc = self.namespace["IncrementSyncStrmHelper"].return_value
        inc.get_generate_total.return_value = (3, 4, 0, 0, 0)
        share = self.namespace["ShareStrmHelper"].return_value
        share.get_generate_total.return_value = (5, 6, 0, 0)
        path = self.root / "service/__init__.py"
        _method(path, "_track_sync_operation", self.namespace)
        self.cls = _compile(path, self.namespace, "ServiceHelper")
        self.service = self.cls()
        self.service.client = object()
        self.service.mediainfodownloader = object()
        self.addCleanup(self._cleanup)

    def _block(self, *args, **kwargs) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放同步生产者")

    def _start(self, callback) -> Thread:
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
        for worker in self.threads:
            worker.join(timeout=2)
        self.service._stop_sync_operations(timeout=2)

    def test_full_sync_keeps_database_and_downstream_until_exit(self) -> None:
        """
        全量扫描未退出时真实插件停止与配置入口保留数据库及下游资源
        """
        full = self.namespace["FullSyncStrmHelper"].return_value
        full.generate_strm_files.side_effect = self._block
        worker = self._start(self.service.full_sync_strm_files)
        self.assertTrue(self.entered.wait(timeout=2))
        namespace = {
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
        namespace["servicer"] = self.service
        stop = _method(self.root / "__init__.py", "stop_service", namespace)
        initialize = _method(self.root / "__init__.py", "init_plugin", namespace)
        plugin = type("Plugin", (), {"_rename_media_fields_cache": {}})()
        plugin.stop_service = MethodType(stop, plugin)
        real_stop = self.service._stop_sync_operations
        with patch.object(
            self.service, "_stop_sync_operations", side_effect=lambda: real_stop(0)
        ):
            self.assertFalse(plugin.stop_service())
            with self.assertRaisesRegex(RuntimeError, "旧插件任务尚未退出"):
                initialize(plugin, {"cookies": "new-account"})
        namespace["ct_db_manager"].close_database.assert_not_called()
        namespace["configer"].update_config.assert_not_called()
        self.namespace["emby_mediainfo_queue"].stop.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
            self.service.full_sync_strm_files()
        self.release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results, [None])
        self.assertTrue(plugin.stop_service())
        namespace["ct_db_manager"].close_database.assert_called_once_with()
        self.assertEqual(self.service._sync_operations, {})
        self.assertFalse(self.service._full_sync_running)

    def test_pending_full_sync_remains_inside_increment_stop_barrier(self) -> None:
        """
        关停期间仍按原优先级执行增量之前接受的待运行全量任务
        """
        inc = self.namespace["IncrementSyncStrmHelper"].return_value
        inc.generate_strm_files.side_effect = self._block
        full = self.namespace["FullSyncStrmHelper"].return_value
        full_entered = Event()
        full_release = Event()
        self.addCleanup(full_release.set)

        def scan(**kwargs) -> None:
            full_entered.set()
            if not full_release.wait(timeout=5):
                raise AssertionError("测试未释放待执行全量")

        full.generate_strm_files.side_effect = scan
        worker = self._start(self.service.increment_sync_strm_files)
        self.assertTrue(self.entered.wait(timeout=2))
        self.service.full_sync_strm_files()
        self.service.full_sync_strm_files()
        self.assertTrue(self.service._full_sync_pending)
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        self.release.set()
        self.assertTrue(full_entered.wait(timeout=2))
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        self.assertFalse(self.service._full_sync_pending)
        full_release.set()
        self.assertTrue(self.service._stop_sync_operations(timeout=2))
        worker.join(timeout=2)
        full.generate_strm_files.assert_called_once()
        inc.generate_strm_files.assert_called_once()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results, [None])
        self.assertEqual(self.namespace["post_message"].call_count, 2)

    def test_database_share_and_cleanup_calls_are_counted(self) -> None:
        """
        数据库生成、分享生成与定时分享清理也保留在途调用和原结果
        """
        operations = (
            (
                "full_sync_database",
                self.namespace["FullSyncStrmHelper"].return_value.generate_database,
            ),
            (
                "share_strm_files",
                self.namespace["ShareStrmHelper"].return_value.generate_strm_files,
            ),
            (
                "share_strm_cleanup_run",
                self.namespace["share_strm_cleaner"].run_full_cleanup,
            ),
        )
        for name, callback in operations:
            with self.subTest(operation=name):
                service = self.cls()
                self.entered.clear()
                self.release.clear()
                callback.side_effect = self._block
                worker = self._start(getattr(service, name))
                self.assertTrue(self.entered.wait(timeout=2))
                self.assertFalse(service._stop_sync_operations(timeout=0))
                with self.assertRaises(RuntimeError):
                    getattr(service, name)()
                self.release.set()
                self.assertTrue(service._stop_sync_operations(timeout=2))
                worker.join(timeout=2)
                self.assertEqual(service._sync_operations, {})
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results, [None, None, None])

    def test_waiting_stop_releases_condition_for_producer_completion(self) -> None:
        """
        外部停止等待时释放计数锁，生产者完成后能够唤醒停止线程
        """
        self.service._run_full_sync = self._block
        worker = self._start(self.service.full_sync_strm_files)
        self.assertTrue(self.entered.wait(timeout=2))
        waiting = Event()
        real_wait = self.service._sync_condition.wait

        def wait(timeout) -> bool:
            waiting.set()
            return real_wait(timeout)

        with patch.object(self.service._sync_condition, "wait", side_effect=wait):
            stopper = self._start(lambda: self.service._stop_sync_operations(timeout=2))
            self.assertTrue(waiting.wait(timeout=2))
            self.assertTrue(stopper.is_alive())
            self.release.set()
            worker.join(timeout=2)
            stopper.join(timeout=2)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(self.errors, [])
        self.assertCountEqual(self.results, [None, True])

    def test_self_stop_and_exception_release_tracking(self) -> None:
        """
        任务自身停止不会等待自身，原异常继续传播且不会泄漏运行标记
        """

        def run() -> None:
            self.assertFalse(self.service.stop())
            raise ValueError("scan failed")

        self.service._run_full_sync = run
        with self.assertRaisesRegex(ValueError, "scan failed"):
            self.service.full_sync_strm_files()
        self.assertFalse(self.service._full_sync_running)
        self.assertEqual(self.service._sync_operations, {})
        self.assertTrue(self.service._stop_sync_operations(timeout=0))

    def test_reinitialize_rejects_running_sync_and_reopens_after_success(self) -> None:
        """
        旧同步未完成时不替换客户端，正常初始化完成后才重新接受任务
        """
        self.service._run_full_sync = self._block
        worker = self._start(self.service.full_sync_strm_files)
        self.assertTrue(self.entered.wait(timeout=2))
        client = self.service.client
        self.assertFalse(self.service.init_service())
        self.assertIs(self.service.client, client)
        self.namespace["create_client"].assert_not_called()
        self.release.set()
        worker.join(timeout=2)
        self.service._init_transfer_enhancement = MagicMock()
        self.namespace["configer"].get_config.side_effect = lambda key: (
            "/synthetic" if key == "plugin_aligo_path" else None
        )
        self.assertTrue(self.service.init_service())
        self.assertFalse(self.service._sync_stopping)
        self.service._run_full_sync = MagicMock()
        self.service.full_sync_strm_files()
        self.service._run_full_sync.assert_called_once()

    def test_failed_initialization_keeps_sync_admission_closed(self) -> None:
        """
        初始化失败时不开放同步入口，也不运行半初始化客户端上的新任务
        """
        self.namespace["create_client"].side_effect = RuntimeError("client failed")
        self.assertFalse(self.service.init_service())
        with self.assertRaises(RuntimeError):
            self.service.increment_sync_strm_files()
        self.assertTrue(self.service._sync_stopping)
        self.assertEqual(self.service._sync_operations, {})

    def test_cleaner_keeps_both_steps_inside_stop_barrier(self) -> None:
        """
        最近接收清理未结束时保留客户端，关停期间继续原回收站清理
        """
        cleaner = self.namespace["Cleaner"].return_value
        cleaner.clear_receive_path.side_effect = self._block
        second_entered, second_release = Event(), Event()
        self.addCleanup(second_release.set)

        def recycle() -> None:
            second_entered.set()
            if not second_release.wait(timeout=5):
                raise AssertionError("测试未释放回收站清理")

        cleaner.clear_recyclebin.side_effect = recycle
        client = self.service.client
        worker = self._start(self.service.main_cleaner)
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        self.assertFalse(self.service.init_service())
        self.assertIs(self.service.client, client)
        self.namespace["create_client"].assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
            self.service.main_cleaner()
        self.namespace["Cleaner"].assert_called_once_with(client=client)
        self.release.set()
        self.assertTrue(second_entered.wait(timeout=2))
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        second_release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results, [None])
        self.assertEqual(self.service._sync_operations, {})
        cleaner.clear_receive_path.assert_called_once_with()
        cleaner.clear_recyclebin.assert_called_once_with()

    def test_cleaner_disabled_steps_preserve_original_return(self) -> None:
        """
        未启用的清理项目保持跳过，原 None 返回不转换为调度结果元组
        """
        self.namespace["configer"].get_config.return_value = False
        self.assertIsNone(self.service.main_cleaner())
        cleaner = self.namespace["Cleaner"].return_value
        cleaner.clear_receive_path.assert_not_called()
        cleaner.clear_recyclebin.assert_not_called()
        self.assertEqual(self.service._sync_operations, {})

    def test_cleaner_constructor_failure_releases_registration(self) -> None:
        """
        清理对象构造失败保持原异常传播，并释放在途登记
        """
        self.namespace["Cleaner"].side_effect = ValueError("cleaner failed")
        with self.assertRaisesRegex(ValueError, "cleaner failed"):
            self.service.main_cleaner()
        self.assertEqual(self.service._sync_operations, {})
        self.assertTrue(self.service._stop_sync_operations(timeout=0))
