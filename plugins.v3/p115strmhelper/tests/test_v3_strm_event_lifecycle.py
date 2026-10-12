from pathlib import Path
from threading import Event
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3StrmEventLifecycle(TestCase):
    """
    验证事件入口的在途范围覆盖生成和通知并保留原事件筛选
    """

    def setUp(self) -> None:
        """
        加载真实入口和同步服务，隔离扫描、整理和消息发送边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.root = Path(__file__).resolve().parents[1]
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            PathUtils=MagicMock(),
            TransferStrmHelper=MagicMock(),
        )
        self.paths = [object()]
        self.namespace["PathUtils"].get_p115_strm_path.return_value = (True, self.paths)
        self.plugin = SimpleNamespace()
        self.plugin._get_event_userid = _method(
            self.root / "__init__.py", "_get_event_userid", self.namespace
        )
        self.callbacks = {}
        for name in ("generate_strm", "p115_full_sync", "p115_inc_sync", "p115_strm"):
            self.callbacks[name] = MethodType(
                _method(self.root / "__init__.py", name, self.namespace), self.plugin
            )

    def _event(self, action: str):
        return SimpleNamespace(
            event_type="transfer-complete",
            event_data={
                "action": action,
                "arg_str": "/cloud/sub",
                "channel": "telegram",
                "source": "isolated",
                "userid": 42,
            },
        )

    def test_start_notification_is_inside_full_and_increment_admission(self) -> None:
        """
        开始通知期间也保留归属，停止后的原请求仍可进入已受理的同步调用
        """
        for name, runner in (
            ("p115_full_sync", "_run_full_sync"),
            ("p115_inc_sync", "_run_increment_sync"),
        ):
            with self.subTest(action=name):
                self.service._sync_stopping = False
                self.runtime.entered.clear()
                self.runtime.release.clear()
                execute = MagicMock()
                setattr(self.service, runner, execute)
                self.namespace["post_message"].side_effect = self.runtime._block
                worker = self.runtime._start(
                    lambda: self.callbacks[name](self._event(name))
                )
                self.assertTrue(self.runtime.entered.wait(timeout=2))
                self.assertFalse(self.service._stop_sync_operations(timeout=0))
                execute.assert_not_called()
                self.runtime.release.set()
                worker.join(timeout=2)
                self.assertEqual(self.runtime.errors, [])
                execute.assert_called_once()
                self.assertTrue(self.service._stop_sync_operations(timeout=0))

    def test_partial_full_sync_keeps_paths_history_and_final_notification(self) -> None:
        """
        局部全量保留原路径与历史标记，完成通知结束前仍不释放资源
        """
        entered, release = Event(), Event()
        self.addCleanup(release.set)
        messages = []

        def notify(**kwargs) -> None:
            messages.append(kwargs)
            if len(messages) == 2:
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("测试未释放完成通知")

        self.namespace["post_message"].side_effect = notify
        worker = self.runtime._start(
            lambda: self.callbacks["p115_strm"](self._event("p115_strm"))
        )
        self.assertTrue(entered.wait(timeout=2))
        self.assertFalse(self.service._stop_sync_operations(timeout=0))
        helper = self.namespace["FullSyncStrmHelper"].return_value
        helper.generate_strm_files.assert_called_once_with(
            full_sync_strm_paths=self.paths
        )
        self.assertEqual(helper.strm_exec_history_kind, "full_partial")
        self.assertEqual(helper.strm_exec_history_extra, {"arg_str": "/cloud/sub"})
        self.assertEqual(messages[1]["userid"], "42")
        self.assertEqual(messages[1]["source"], "isolated")
        self.assertTrue(messages[1]["text"].startswith("\n📂 网盘路径：/cloud/sub\n"))
        release.set()
        worker.join(timeout=2)
        self.assertEqual(self.runtime.errors, [])
        self.assertTrue(self.service._stop_sync_operations(timeout=0))

    def test_transfer_exception_propagates_and_releases_registration(self) -> None:
        """
        整理完成异常继续上抛供严格投递重试，不被生命周期登记吞掉
        """
        helper = self.namespace["TransferStrmHelper"].return_value
        helper.do_generate.side_effect = ValueError("original failure")
        event = self._event("transfer")
        with self.assertRaisesRegex(ValueError, "original failure"):
            self.callbacks["generate_strm"](event)
        helper.do_generate.assert_called_once_with(
            client=self.service.client,
            item=event.event_data,
            event_type=event.event_type,
            mediainfodownloader=self.service.mediainfodownloader,
        )
        self.assertEqual(self.service._sync_operations, {})

    def test_unrelated_actions_and_disabled_transfer_keep_original_skip(self) -> None:
        """
        非目标动作和停用的整理监控仍直接跳过，不因关停增加额外错误
        """
        self.assertTrue(self.service._stop_sync_operations(timeout=0))
        for name in ("p115_full_sync", "p115_inc_sync", "p115_strm"):
            self.assertIsNone(self.callbacks[name](self._event("unrelated")))
        self.namespace["configer"].enabled = False
        self.assertIsNone(self.callbacks["generate_strm"](self._event("transfer")))
        self.namespace["post_message"].assert_not_called()
        self.namespace["TransferStrmHelper"].assert_not_called()
