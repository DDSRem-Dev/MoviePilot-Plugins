from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

import test_v3_backup_lifecycle as backup_fixture
import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3BackupApiLifecycle(TestCase):
    """
    验证禁用时的原备份接口和已受理任务停止反馈
    """

    def setUp(self) -> None:
        """
        加载真实 API、备份服务及同步服务，隔离存储和调度边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.backup = backup_fixture.TestV3BackupLifecycle()
        self.backup.setUp()
        self.addCleanup(self.backup.doCleanups)
        self.service = self.runtime.service
        self.service.backup_service = self.backup.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            configer=self.backup.config,
            backup_helper=self.backup.helper,
            Body=lambda *args, **kwargs: None,
            Query=lambda *args, **kwargs: None,
            ApiResponse=lambda **kwargs: SimpleNamespace(**dict({"code": 0}, **kwargs)),
        )
        root = Path(__file__).resolve().parents[1]
        self.callbacks = {
            name: _method(root / "api.py", name, self.namespace)
            for name in ("trigger_backup_api", "restore_backup_api", "list_backups_api")
        }

    def test_disabled_submissions_preserve_original_behavior(self) -> None:
        """
        禁用状态保留手动提交和重复任务反馈，已占位任务仍阻止停止
        """
        self.service._sync_stopping = True
        self.assertTrue(self.backup.service.stop())
        for name in ("trigger_backup_api", "restore_backup_api"):
            for target_type in ("cloud", "local"):
                with self.subTest(entry=name, target=target_type):
                    self.backup.task.target_type.value = target_type
                    args = ("sample", "/backup") if name == "restore_backup_api" else ("sample",)
                    callback = self.callbacks[name]
                    self.assertEqual(callback(*args).code, 0)
                    duplicate = callback(*args)
                    self.assertEqual(duplicate.code, -1)
                    self.assertIn("正在运行", duplicate.msg)
                    self.assertFalse(self.backup.service.stop())
                    self.assertIs(self.backup.service.client, self.backup.client)
                    self.backup._execute_scheduled()
                    self.assertTrue(self.backup.service.stop())
                    self.assertEqual(self.backup.service._active_executions, 0)
                    self.assertEqual(self.service._sync_operations, {})
                    self.assertTrue(self.service._sync_stopping)

    def test_original_validation_and_schedule_failure_are_preserved(self) -> None:
        """
        原未启用、缺少任务和调度失败文案保持
        """
        self.service._sync_stopping = True
        self.assertTrue(self.backup.service.stop())
        for name, callback in self.callbacks.items():
            args = ("sample", "/backup") if name == "restore_backup_api" else ("sample",)
            self.backup.config.strm_backup_enabled = False
            self.assertEqual(callback(*args).msg, "STRM 备份功能未启用")
            self.backup.config.strm_backup_enabled = True
            missing = ("missing", "/backup") if name == "restore_backup_api" else ("missing",)
            self.assertEqual(callback(*missing).msg, "备份任务不存在: missing")
            empty = ("", "/backup") if name == "restore_backup_api" else ("",)
            self.assertEqual(callback(*empty).msg, "备份任务名称不能为空")
        self.backup.namespace["schedule_plugin_one_shot"].return_value = False
        for name, args, expected in (
            ("trigger_backup_api", ("sample",), "备份任务调度失败，请稍后重试: sample"),
            ("restore_backup_api", ("sample", "/backup"), "恢复任务调度失败，请稍后重试: sample"),
        ):
            response = self.callbacks[name](*args)
            self.assertEqual(response.code, -1)
            self.assertEqual(response.msg, expected)
            self.assertFalse(self.backup.service.is_backup_task_running("sample"))
        self.assertEqual(self.service._sync_operations, {})

    def test_original_list_projection_and_errors_are_preserved(self) -> None:
        """
        停止后列表保留原 JSON 投影，助手异常仍返回原失败文案
        """
        self.service._sync_stopping = True
        for target in ("local", "cloud"):
            with self.subTest(target=target):
                self.backup.task.target_type.value = target
                boundary = getattr(self.backup.helper, f"list_{target}_backups")
                record = MagicMock()
                record.model_dump.return_value = {"filename": "sample.tar.gz", "target_type": target}
                boundary.return_value = [record]
                response = self.callbacks["list_backups_api"]("sample")
                self.assertEqual(response.code, 0)
                self.assertEqual(response.data, [record.model_dump.return_value])
                record.model_dump.assert_called_once_with(mode="json")
                boundary.side_effect = ValueError("synthetic")
                response = self.callbacks["list_backups_api"]("sample")
                self.assertEqual(response.code, -1)
                self.assertEqual(response.msg, "列出备份失败: synthetic")
                boundary.side_effect = None
                self.assertEqual(self.service._sync_operations, {})
                self.assertTrue(self.service._sync_stopping)
