from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3LifeDiagnosticLifecycle(TestCase):
    """
    验证生活事件诊断在同步服务停止后仍返回原报告
    """

    def setUp(self) -> None:
        """
        加载实际 API 和同步服务，隔离网盘诊断方法
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.client = MagicMock()
        self.client.user_my_info.return_value = {"state": True, "data": {"uname": "isolated"}}
        self.service.client = self.client
        self.service.monitorlife = MagicMock(_client=self.client)
        self.service.monitorlife.stop.return_value = True
        self.helper = MagicMock()
        self.helper.test_life_event_status.return_value = (True, ["status"], None)
        self.helper.test_life_event_pull.return_value = (True, ["pull"], [])
        self.helper.test_life_event_pull_from_time.return_value = (True, ["from-time"], [])
        self.namespace = self.runtime.namespace
        self.namespace["configer"].get_config.side_effect = lambda key: {
            "enabled": True, "cookies": "isolated",
        }.get(key)
        self.namespace.update(
            servicer=self.service,
            MonitorLifeTest=self.helper,
            Body=lambda default=None, **kwargs: default,
            ApiResponse=lambda **kwargs: SimpleNamespace(**kwargs),
            LifeEventCheckData=SimpleNamespace,
            LifeEventCheckSummary=SimpleNamespace,
        )
        self.callback = _method(
            Path(__file__).resolve().parents[1] / "api.py",
            "check_life_event_status_api", self.namespace,
        )

    def test_stopped_diagnostics_return_reports_with_or_without_client(self) -> None:
        """
        停止后保留有客户端和未初始化时的原诊断报告
        """
        self.service._sync_stopping = True
        for initialized in (True, False):
            if not initialized:
                self.service.client = None
                self.service.monitorlife = None
            for payload in (None, SimpleNamespace(start_time=123)):
                with self.subTest(initialized=initialized, payload=payload):
                    response = self.callback(payload)
                    self.assertEqual(response.code, 0 if initialized else 1)
                    self.assertEqual(response.data.summary.client_initialized, initialized)
                    if not initialized:
                        self.assertIn("115客户端未初始化", response.data.error_messages)
                        self.assertIn("MonitorLife实例不存在", response.data.error_messages)
                    self.assertTrue(self.service._sync_stopping)

    def test_original_summary_and_optional_pull_are_preserved(self) -> None:
        """
        原诊断文本、摘要字段及可选时间分支保持
        """
        response = self.callback(None)
        self.assertEqual(response.code, 0)
        self.assertEqual(response.msg, "检查完成")
        self.assertTrue(response.data.success)
        self.assertEqual(response.data.error_messages, [])
        self.assertIn("用户名: isolated", response.data.debug_info)
        self.assertEqual(vars(response.data.summary), {
            "plugin_enabled": True, "client_initialized": True,
            "monitorlife_initialized": True, "thread_running": False, "config_valid": False,
        })
        self.helper.test_life_event_pull_from_time.assert_not_called()
        response = self.callback(SimpleNamespace(start_time=123))
        self.helper.test_life_event_pull_from_time.assert_called_once_with(self.client, 123)
        self.assertIn("8. 拉取指定时间内的全部数据", response.data.debug_info)
        self.assertIn("9. 配置完整性检查", response.data.debug_info)

    def test_original_client_error_and_unexpected_exception_are_preserved(self) -> None:
        """
        客户端异常沿用原报告，未捕获异常继续传播
        """
        self.client.user_my_info.side_effect = ValueError("synthetic")
        response = self.callback(None)
        self.assertEqual(response.code, 1)
        self.assertIn("115客户端异常: synthetic", response.data.error_messages)
        self.assertEqual(self.service._sync_operations, {})
        self.helper.test_life_event_pull.side_effect = RuntimeError("helper failure")
        with self.assertRaisesRegex(RuntimeError, "helper failure"):
            self.callback(None)
        self.assertEqual(self.service._sync_operations, {})
