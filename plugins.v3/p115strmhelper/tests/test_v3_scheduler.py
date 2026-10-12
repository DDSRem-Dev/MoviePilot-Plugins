from importlib import import_module
from pathlib import Path
from sys import modules
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch


class TestV3OneShotScheduler(TestCase):
    """
    验证一次性任务使用 V3 调度合同和实际实例 ID
    """

    def setUp(self) -> None:
        """
        隔离宿主 SDK 并加载真实调度函数
        """
        root = Path(__file__).resolve().parents[1]
        prefix = "_p115_v3_scheduler_test"
        replacements = {}
        for name, path in (
            (prefix, root),
            (f"{prefix}.service", root / "service"),
            (f"{prefix}.core", root / "core"),
            ("app", None),
            ("app.sdk", None),
        ):
            module = ModuleType(name)
            module.__path__ = [str(path)] if path else []
            replacements[name] = module
        self.submit = MagicMock(return_value=True)
        self.owner = object()
        for name, attributes in (
            (
                f"{prefix}.core.config",
                {"configer": SimpleNamespace(plugin_id="CloneA", plugin_instance=self.owner)},
            ),
            ("app.sdk.logging", {"logger": MagicMock()}),
            ("app.sdk.scheduler", {"add_plugin_once_job": self.submit}),
        ):
            module = ModuleType(name)
            module.__dict__.update(attributes)
            replacements[name] = module
        patcher = patch.dict(modules, replacements)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.schedule = import_module(
            f"{prefix}.service.one_shot"
        ).schedule_plugin_one_shot

    def test_preserves_callback_arguments_and_instance_identity(self) -> None:
        """
        传入局部任务 ID，由宿主生成实例命名空间并维护执行状态
        """
        callback = MagicMock()
        self.assertTrue(
            self.schedule("backup", "备份", callback, {"task_name": "电影"}, 7)
        )
        bound_callback = self.submit.call_args.kwargs["func"]
        self.submit.assert_called_once_with(
            plugin_id="CloneA",
            job_id="backup",
            func=bound_callback,
            name="备份",
            delay_seconds=7,
            func_kwargs={"task_name": "电影"},
        )
        callback.assert_not_called()
        self.assertIs(bound_callback.__self__, self.owner)
        bound_callback(task_name="电影")
        callback.assert_called_once_with(task_name="电影")

    def test_explicit_owner_and_immediate_execution(self) -> None:
        """
        显式实例及零延迟均按原值交给宿主
        """
        self.assertTrue(
            self.schedule("sync", "同步", lambda: None, delay_sec=0, pid="B")
        )
        self.assertEqual(self.submit.call_args.kwargs["plugin_id"], "B")
        self.assertEqual(self.submit.call_args.kwargs["delay_seconds"], 0)

    def test_rejected_and_failed_registration_return_false(self) -> None:
        """
        宿主停机或初始化异常时向调用方返回失败以释放业务运行槽
        """
        self.submit.return_value = False
        self.assertFalse(self.schedule("backup", "备份", lambda: None))
        self.submit.side_effect = RuntimeError("宿主调度器未初始化")
        self.assertFalse(self.schedule("backup", "备份", lambda: None))
