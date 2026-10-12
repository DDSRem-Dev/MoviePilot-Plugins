from functools import wraps
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3BackupLifecycle(TestCase):
    """
    验证备份与恢复的运行槽在 V3 关停时保留已受理任务和客户端归属
    """

    def setUp(self) -> None:
        """
        使用实际服务方法和线程，隔离宿主调度、归档及云端边界
        """
        self.root = Path(__file__).resolve().parents[1]
        self.entered = Event()
        self.release = Event()
        self.watcher_release = Event()
        self.threads = []
        self.errors = []
        self.task = SimpleNamespace(
            name="sample", target_type=SimpleNamespace(value="cloud"), source_paths=[]
        )
        self.config = SimpleNamespace(
            strm_backup_enabled=True,
            strm_backup_items=[self.task],
            plugin_id="P115StrmHelperCloneA",
        )
        self.helper = MagicMock()
        self.helper.execute_backup.return_value = SimpleNamespace(
            status="success", filename="sample.tar.gz", file_size=1
        )
        self.helper.restore_from_cloud.return_value = (True, None)
        self.helper.restore_from_local.return_value = (True, None)
        self.namespace = {
            "wraps": wraps,
            "Lock": Lock,
            "Thread": self._thread,
            "sleep": MagicMock(side_effect=self._watcher_wait),
            "configer": self.config,
            "backup_helper": self.helper,
            "BackupStrmHelper": SimpleNamespace(_safe_task_name=lambda name: name),
            "schedule_plugin_one_shot": MagicMock(return_value=True),
            "list_scheduler_jobs": MagicMock(return_value=[]),
            "logger": MagicMock(),
        }
        _method(
            self.root / "service/backup/__init__.py",
            "_track_backup_execution",
            self.namespace,
        )
        self.cls = _compile(
            self.root / "service/backup/__init__.py", self.namespace, "BackupService"
        )
        self.client = object()
        self.service = self.cls(self.client)
        self.addCleanup(self._cleanup)

    def _thread(self, **kwargs) -> Thread:
        worker = Thread(**kwargs)
        self.threads.append(worker)
        return worker

    def _watcher_wait(self, seconds) -> None:
        if not self.watcher_release.wait(timeout=5):
            raise AssertionError("测试未释放运行槽守护线程")

    def _block(self, *args, **kwargs):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放备份操作")
        return self.helper.execute_backup.return_value

    def _start(self, callback) -> Thread:
        def run() -> None:
            try:
                callback()
            except Exception as error:
                self.errors.append(error)

        worker = self._thread(target=run)
        worker.start()
        return worker

    def _cleanup(self) -> None:
        self.release.set()
        self.watcher_release.set()
        for worker in self.threads:
            worker.join(timeout=2)

    def _execute_scheduled(self) -> None:
        submission = self.namespace["schedule_plugin_one_shot"].call_args.kwargs
        return submission["func"](**submission["func_kwargs"])

    def test_running_backup_blocks_stop_and_keeps_client(self) -> None:
        """
        正在执行的备份保留原客户端，关停拒绝新调用且不取消原任务
        """
        self.helper.execute_backup.side_effect = self._block
        worker = self._start(lambda: self.service.run_backup_task("sample"))
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.service.stop())
        self.assertFalse(self.service.stop())
        self.assertTrue(self.service.is_backup_task_running("sample"))
        with self.assertRaisesRegex(RuntimeError, "备份服务已停止"):
            self.service.run_restore_task("another", "backup.tar.gz")
        self.assertIs(self.service.client, self.client)
        self.release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.errors, [])
        self.helper.execute_backup.assert_called_once_with(
            self.task, client=self.client
        )
        self.assertTrue(self.service.stop())

    def test_reserved_backup_and_restore_execute_after_stop_request(self) -> None:
        """
        已占位但尚未执行的备份和恢复继续执行，完成前不允许重载
        """
        for kind in ("backup", "restore"):
            with self.subTest(kind=kind):
                self.service = self.cls(self.client)
                if kind == "backup":
                    accepted = self.service.start_backup_task(self.task)
                else:
                    accepted = self.service.start_restore_task("sample", "/backup")
                self.assertTrue(accepted)
                self.assertFalse(self.service.stop())
                self.assertEqual(self.service._reserved_task_started, set())
                self.assertIsNone(self._execute_scheduled())
                self.assertTrue(self.service.stop())
                self.assertFalse(self.service.is_backup_task_running("sample"))
                with self.assertRaisesRegex(RuntimeError, "不属于当前运行槽"):
                    self._execute_scheduled()
        self.helper.execute_backup.assert_called_once_with(
            self.task, client=self.client
        )
        self.helper.restore_from_cloud.assert_called_once_with(
            cloud_path="/backup", source_paths=[], client=self.client
        )
        self.assertTrue(
            all(call.args == (10,) for call in self.namespace["sleep"].call_args_list)
        )

    def test_running_restore_releases_slot_even_on_exception(self) -> None:
        """
        云端恢复异常继续传播，既有 finally 释放槽位使后续停止成功
        """

        def restore(**kwargs):
            self._block()
            raise ValueError("restore failed")

        self.helper.restore_from_cloud.side_effect = restore
        worker = self._start(lambda: self.service.run_restore_task("sample", "/backup"))
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertFalse(self.service.stop())
        self.release.set()
        worker.join(timeout=2)
        self.assertEqual(len(self.errors), 1)
        self.assertIsInstance(self.errors[0], ValueError)
        self.assertTrue(self.service.stop())
        self.assertEqual(self.service._reserved_task_started, set())

    def test_orphaned_pending_task_uses_original_scheduler_check(self) -> None:
        """
        仅由原守护流程确认任务已被宿主移除后释放占位，不在停止时清空
        """
        self.assertTrue(self.service.start_backup_task(self.task))
        self.assertFalse(self.service.stop())
        self.watcher_release.set()
        for worker in self.threads:
            worker.join(timeout=2)
        self.namespace["list_scheduler_jobs"].assert_called_once_with()
        self.assertTrue(self.service.stop())
        self.helper.execute_backup.assert_not_called()

    def test_scheduler_query_failure_keeps_pending_ownership(self) -> None:
        """
        宿主查询失败保持原槽位，恢复回调仍可完成并释放归属
        """
        self.namespace["list_scheduler_jobs"].side_effect = RuntimeError("unavailable")
        self.assertTrue(self.service.start_restore_task("sample", "/backup"))
        self.watcher_release.set()
        for worker in self.threads:
            worker.join(timeout=2)
        self.assertFalse(self.service.stop())
        self.assertIsNone(self._execute_scheduled())
        self.assertTrue(self.service.stop())

    def test_execution_remains_tracked_if_original_watcher_releases_slot(self) -> None:
        """
        原守护查询与回调启动交错时，即使槽位已释放也不提前释放执行资源
        """
        self.helper.execute_backup.side_effect = self._block

        def query():
            self._start(self._execute_scheduled)
            self.assertTrue(self.entered.wait(timeout=2))
            return []

        self.namespace["list_scheduler_jobs"].side_effect = query
        self.assertTrue(self.service.start_backup_task(self.task))
        watcher = self.threads[0]
        self.watcher_release.set()
        watcher.join(timeout=2)
        self.assertFalse(watcher.is_alive())
        self.assertFalse(self.service.is_backup_task_running("sample"))
        self.assertFalse(self.service.stop())
        self.release.set()
        for worker in self.threads:
            worker.join(timeout=2)
        self.assertEqual(self.errors, [])
        self.assertTrue(self.service.stop())

    def test_rejected_submission_releases_slot_and_preserves_api_failure(
        self,
    ) -> None:
        """
        原注册失败释放占位，禁用后的实际 API 保持调度失败文案
        """
        self.namespace["schedule_plugin_one_shot"].return_value = False
        self.assertFalse(self.service.start_backup_task(self.task))
        self.assertTrue(self.service.stop())
        namespace = dict(
            configer=self.config,
            servicer=SimpleNamespace(backup_service=self.service),
            logger=MagicMock(),
            Body=lambda *args, **kwargs: None,
            ApiResponse=lambda **kwargs: SimpleNamespace(**kwargs),
        )
        trigger = _method(self.root / "api.py", "trigger_backup_api", namespace)
        restore = _method(self.root / "api.py", "restore_backup_api", namespace)
        for response in (trigger("sample"), restore("sample", "/backup")):
            self.assertEqual(response.code, -1)
            self.assertIn("任务调度失败", response.msg)

    def test_self_stop_is_nonblocking_and_replacement_is_independent(self) -> None:
        """
        任务自身停止立即反馈未结束，新服务与原手动提交独立
        """
        self.helper.execute_backup.side_effect = lambda *args, **kwargs: (
            self.assertFalse(self.service.stop()),
            self.helper.execute_backup.return_value,
        )[1]
        self.service.run_backup_task("sample")
        self.assertTrue(self.service.stop())
        replacement = self.cls(object())
        self.assertFalse(replacement._stopping)
        self.assertEqual(replacement._backup_running_tasks, set())
        self.assertTrue(self.service.start_backup_task(self.task))
        self.assertFalse(self.service.stop())
        self._execute_scheduled()
        self.assertTrue(self.service.stop())
        self.assertEqual(replacement._backup_running_tasks, set())
