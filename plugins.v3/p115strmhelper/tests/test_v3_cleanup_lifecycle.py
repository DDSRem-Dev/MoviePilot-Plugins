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


class TestV3CleanupLifecycle(TestCase):
    """
    验证分享清理扫描的 V3 停止反馈及确认执行的原有可用性
    """

    def setUp(self) -> None:
        """
        使用真实 API、服务方法与线程，替换批次持久化及删除边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.entered = Event()
        self.release = Event()
        self.threads = []
        self.namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "configer",
                "BackupService",
                "ShareInteractiveGenStrmQueue",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
                "share_strm_pending_queue",
                "share_strm_cleaner",
            )
        }
        self.namespace.update(
            contextmanager=contextmanager,
            wraps=wraps,
            Condition=Condition,
            Lock=Lock,
            Thread=self._thread,
            current_thread=current_thread,
            monotonic=monotonic,
            ApiResponse=lambda **kwargs: SimpleNamespace(**dict({"code": 0}, **kwargs)),
        )
        path = self.root / "service/__init__.py"
        _method(path, "_track_sync_operation", self.namespace)
        self.service = _compile(path, self.namespace, "ServiceHelper")()
        self.namespace["servicer"] = self.service
        self.scan = _method(
            self.root / "api.py", "share_strm_cleanup_scan_api", self.namespace
        )
        self.execute = _method(
            self.root / "api.py", "share_strm_cleanup_execute_api", self.namespace
        )
        self.batch = {"request_id": "batch", "paths": ["/synthetic/movie.strm"]}
        self.queue = self.namespace["share_strm_pending_queue"]
        self.queue.claim_pending_batch.return_value = (self.batch, None)
        self.cleaner = self.namespace["share_strm_cleaner"]
        self.cleaner.execute_claimed_batch.side_effect = self._block
        self.cleaner.run_full_cleanup.side_effect = self._block
        self.addCleanup(self._cleanup)

    def _thread(self, **kwargs) -> Thread:
        worker = Thread(**kwargs)
        self.threads.append(worker)
        return worker

    def _block(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放清理后台任务")
        return 1, None

    def _cleanup(self) -> None:
        self.release.set()
        for worker in self.threads:
            worker.join(timeout=2)

    def _stop_service_without_wait(self) -> bool:
        stop = self.service._stop_sync_operations
        with patch.object(
            self.service, "_stop_sync_operations", side_effect=lambda: stop(0)
        ):
            return self.service.stop()

    def test_scan_retains_resources_until_background_completion(self) -> None:
        """
        扫描 API 保持原成功响应，后台任务退出前服务不关闭下游资源
        """
        response = self.scan()
        self.assertEqual(response.code, 0)
        self.assertTrue(self.entered.wait(timeout=2))
        worker = self.threads[0]
        self.assertEqual(worker.name, "share-strm-cleanup-scan")
        self.assertTrue(worker.daemon)
        self.assertFalse(self._stop_service_without_wait())
        self.namespace["emby_mediainfo_queue"].stop.assert_not_called()
        self.namespace["TransferChainPatcher"].disable.assert_not_called()
        self.release.set()
        worker.join(timeout=2)
        self.assertTrue(self.service.stop())
        self.cleaner.run_full_cleanup.assert_called_once_with()

    def test_stopped_service_preserves_confirmed_batch_execution(self) -> None:
        """
        停止服务后仍按原规则领取批次并启动后台确认清理
        """
        self.assertTrue(self.service.stop())
        response = self.execute(SimpleNamespace(request_id=" batch "))
        self.assertEqual(response.code, 0)
        self.assertEqual(response.data, {"request_id": "batch"})
        self.assertTrue(self.entered.wait(timeout=2))
        self.queue.claim_pending_batch.assert_called_once_with("batch")
        self.cleaner.execute_claimed_batch.assert_called_once_with(self.batch)
        worker = self.threads[0]
        self.assertEqual(worker.name, "share-strm-cleanup-exec")
        self.assertTrue(worker.daemon)
        self.release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(self.service._sync_stopping)

    def test_stopped_scan_keeps_existing_rejection(self) -> None:
        """
        扫描保留停止拒绝，确认执行不由此测试推断
        """
        self.assertTrue(self.service.stop())
        response = self.scan()
        self.assertEqual(response.code, 1)
        self.assertIn("同步服务已停止", response.msg)
        self.cleaner.run_full_cleanup.assert_not_called()
        self.assertEqual(self.threads, [])

    def test_invalid_claim_preserves_original_errors(self) -> None:
        """
        原批次错误响应与领取异常保持，不启动后台清理
        """
        for error in ("batch_not_found", "invalid_batch", "custom"):
            with self.subTest(error=error):
                self.queue.claim_pending_batch.return_value = (None, error)
                response = self.execute(SimpleNamespace(request_id="batch"))
                self.assertEqual(response.code, 1)
                self.assertEqual(self.service._sync_operations, {})
        self.queue.claim_pending_batch.side_effect = ValueError("claim failed")
        self.assertEqual(self.execute(SimpleNamespace(request_id="batch")).code, 1)
        self.assertEqual(self.service._sync_operations, {})
        self.assertEqual(self.threads, [])

    def test_thread_start_failure_preserves_original_response(self) -> None:
        """
        确认清理的原线程启动失败仍报告失败，不执行删除
        """
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("thread failed")
        with patch.dict(self.namespace, Thread=MagicMock(return_value=worker)):
            response = self.execute(SimpleNamespace(request_id="batch"))
        self.assertEqual(response.code, 1)
        self.assertIn("thread failed", response.msg)
        self.assertEqual(self.service._sync_operations, {})
        self.cleaner.execute_claimed_batch.assert_not_called()

    def test_background_failure_keeps_original_logging_and_releases_tracking(
        self,
    ) -> None:
        """
        原后台异常记录路径保持，失败结束后停止能够收敛
        """
        self.cleaner.run_full_cleanup.side_effect = ValueError("scan failed")
        self.assertEqual(self.scan().code, 0)
        self.threads[0].join(timeout=2)
        self.namespace["logger"].error.assert_called_once()
        self.assertIn("scan failed", self.namespace["logger"].error.call_args.args[0])
        self.assertTrue(self.service.stop())

    def test_thread_is_registered_before_its_target_enters(self) -> None:
        """
        已启动但尚未进入回调的线程也阻止停止，不存在启动交接空窗
        """

        def factory(**kwargs):
            original = kwargs["target"]

            def delayed() -> None:
                self._block()
                original()

            kwargs["target"] = delayed
            return self._thread(**kwargs)

        callback = MagicMock()
        with patch.dict(self.namespace, Thread=factory):
            self.service.start_background_sync(callback, "delayed-cleanup")
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        callback.assert_not_called()
        self.release.set()
        self.threads[0].join(timeout=2)
        callback.assert_called_once_with()
        self.assertTrue(self.service.stop())

    def test_background_nested_operation_can_stop_without_waiting_itself(self) -> None:
        """
        已登记后台线程允许同线程嵌套操作，自身停止立即反馈未完成
        """
        results = []

        def callback() -> None:
            with self.service.sync_operation():
                results.append(self.service.stop())

        self.service.start_background_sync(callback, "nested-cleanup")
        self.threads[0].join(timeout=2)
        self.assertEqual(results, [False])
        self.assertTrue(self.service.stop())
