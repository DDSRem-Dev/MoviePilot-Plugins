"""
JobViewAdapter 单元测试。

覆盖正常转发路径与宿主接口变更时的降级路径。宿主对象用测试替身模拟，
不依赖真实 MoviePilot 运行时。

宿主依赖优先复用已安装的 V3 桩（``PYTHONPATH`` 指向 ``v3-stub``）；
桩不可用时才退回最小假模块。**注意**：绝不能把 ``app`` / ``app.sdk``
登记成裸模块——那会让 ``sys.modules`` 里的 ``app.sdk`` 失去 ``__path__``，
导致同一进程内后续测试的 ``import app.sdk.*`` 全部失败。
"""

import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

plugin_root = Path(__file__).resolve().parents[1]


def _stub_available(module_name: str) -> bool:
    """判断指定宿主模块能否从桩中正常导入。"""
    try:
        __import__(module_name)
        return True
    except Exception:  # noqa: BLE001 - 任何导入失败都视为桩不可用
        return False


def _make_module(name: str, **attrs) -> ModuleType:
    """创建并注册假模块。"""
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


_HAS_STUB = _stub_available("app.sdk.logging")

if not _HAS_STUB and "app.sdk.logging" not in sys.modules:
    # 无桩兜底：这里必须伪造完整的包链，否则会污染后续测试
    _make_module("app", __path__=[])
    _make_module("app.sdk", __path__=[])
    _make_module("app.sdk.logging", logger=MagicMock())

class _FakeMetaBase:
    """最小元数据替身。"""

    begin_season = None


class _FakeMPTransferTask:
    """最小宿主任务替身，接收探针构造参数。"""

    def __init__(self, fileitem=None, mediainfo=None, meta=None):
        self.fileitem = fileitem
        self.mediainfo = mediainfo
        self.meta = meta


if _HAS_STUB:
    # 桩已提供完整宿主面，直接用真实桩类型，避免覆盖桩的包结构
    from app.schemas import TransferTask as _MPTransferTask  # noqa: E402
    from app.sdk.media import MetaBase as _MetaBase  # noqa: E402
else:
    # 无桩兜底：只补桩缺失的符号，且不破坏已存在的包
    if "app.schemas" not in sys.modules:
        _make_module("app.schemas", TransferTask=_FakeMPTransferTask)
    if "app.sdk.media" not in sys.modules:
        _make_module("app.sdk.media")
    sys.modules["app.sdk.media"].MetaBase = _FakeMetaBase
    _MPTransferTask = _FakeMPTransferTask
    _MetaBase = _FakeMetaBase

if str(plugin_root) not in sys.path:
    sys.path.insert(0, str(plugin_root))

from utils.transfer_compat import JobViewAdapter, get_jobview  # noqa: E402


class _FakeTransferTask:
    """最小任务替身。"""

    def __init__(self, name: str = "task", state: str = "waiting"):
        self.fileitem = MagicMock()
        self.fileitem.name = name
        self.state = state


class TestJobViewAdapterNormalPath(unittest.TestCase):
    """宿主接口完整时的正常转发。"""

    def _make_jobview(self):
        jobview = MagicMock()
        for name in (
            "add_task",
            "remove_task",
            "running_task",
            "finish_task",
            "fail_task",
            "remove_job",
            "try_remove_job",
            "is_done",
        ):
            setattr(jobview, name, MagicMock(return_value=True))
        return jobview

    def test_verify_passes_with_full_interface(self):
        adapter = JobViewAdapter(self._make_jobview())
        self.assertTrue(adapter.verify())
        self.assertTrue(adapter.is_available())

    def test_public_calls_forward_to_host(self):
        jobview = self._make_jobview()
        adapter = JobViewAdapter(jobview)
        task = _FakeTransferTask()

        adapter.running_task(task)
        jobview.running_task.assert_called_once_with(task)

        adapter.finish_task(task)
        jobview.finish_task.assert_called_once_with(task)

        adapter.remove_job(task)
        jobview.remove_job.assert_called_once_with(task)

        adapter.try_remove_job(task)
        jobview.try_remove_job.assert_called_once_with(task)

    def test_try_remove_job_swallows_exception(self):
        """宿主抛异常不应冒泡，避免打断整理主流程。"""
        jobview = self._make_jobview()
        jobview.try_remove_job.side_effect = RuntimeError("boom")
        adapter = JobViewAdapter(jobview)
        adapter.try_remove_job(_FakeTransferTask())  # 不应抛出

    def test_boolean_queries_return_false_on_failure(self):
        """查询类方法异常时应返回安全默认值。"""
        jobview = self._make_jobview()
        jobview.is_done.side_effect = RuntimeError("boom")
        adapter = JobViewAdapter(jobview)
        self.assertFalse(adapter.is_done(_FakeTransferTask()))

    def test_count_size_default_zero(self):
        jobview = self._make_jobview()
        jobview.count.side_effect = RuntimeError("boom")
        jobview.size.side_effect = RuntimeError("boom")
        adapter = JobViewAdapter(jobview)
        self.assertEqual(adapter.count(MagicMock()), 0)
        self.assertEqual(adapter.size(MagicMock()), 0)

    def test_success_tasks_default_empty_list(self):
        jobview = self._make_jobview()
        jobview.success_tasks.side_effect = RuntimeError("boom")
        adapter = JobViewAdapter(jobview)
        self.assertEqual(adapter.success_tasks(), [])


class TestJobViewAdapterDegradedPath(unittest.TestCase):
    """宿主接口缺失时的降级行为。"""

    def test_verify_fails_on_missing_method(self):
        jobview = MagicMock(spec=["add_task"])
        adapter = JobViewAdapter(jobview)
        self.assertFalse(adapter.verify())
        self.assertFalse(adapter.is_available())

    def test_verify_fails_on_none(self):
        adapter = JobViewAdapter(None)
        self.assertFalse(adapter.verify())

    def test_missing_method_does_not_raise(self):
        jobview = MagicMock(spec=[])
        adapter = JobViewAdapter(jobview)
        adapter.running_task(_FakeTransferTask())  # 不应抛出
        self.assertFalse(adapter.is_done(_FakeTransferTask()))

    def test_describe_job_tasks_none_when_unavailable(self):
        adapter = JobViewAdapter(None)
        self.assertIsNone(adapter.describe_job_tasks(MagicMock()))

    def test_describe_job_tasks_uses_public_get_job_id(self):
        """主路径：走公开 get_job_id。"""
        task = _FakeTransferTask("ep1.mkv", "success")
        job = MagicMock()
        job.tasks = [task]
        jobview = MagicMock()
        jobview.get_job_id = MagicMock(return_value="job-1")
        jobview._job_view = {"job-1": job}
        adapter = JobViewAdapter(jobview)
        self.assertEqual(adapter.describe_job_tasks(MagicMock()), [("ep1.mkv", "success")])

    def test_describe_job_tasks_falls_back_to_private_name(self):
        """回退路径：公开方法不可用时走私有名字改写方法。"""
        task = _FakeTransferTask("ep2.mkv", "failed")
        job = MagicMock()
        job.tasks = [task]
        jobview = MagicMock(spec=["_JobManager__get_media_id", "_job_view"])
        jobview._JobManager__get_media_id = MagicMock(return_value="job-2")
        jobview._job_view = {"job-2": job}
        adapter = JobViewAdapter(jobview)
        self.assertEqual(adapter.describe_job_tasks(MagicMock()), [("ep2.mkv", "failed")])

    def test_describe_job_tasks_none_when_job_absent(self):
        """作业不在容器中时返回 None，调用方据此走降级日志。"""
        jobview = MagicMock()
        jobview.get_job_id = MagicMock(return_value="missing")
        jobview._job_view = {}
        adapter = JobViewAdapter(jobview)
        self.assertIsNone(adapter.describe_job_tasks(MagicMock()))

    def test_describe_job_tasks_none_without_any_strategy(self):
        jobview = MagicMock(spec=["_job_view"])
        jobview._job_view = {}
        adapter = JobViewAdapter(jobview)
        self.assertIsNone(adapter.describe_job_tasks(MagicMock()))


class TestGetJobview(unittest.TestCase):
    """工厂函数行为。"""

    def test_returns_adapter(self):
        chain = MagicMock()
        chain.jobview = MagicMock()
        adapter = get_jobview(chain)
        self.assertIsInstance(adapter, JobViewAdapter)

    def test_returns_none_without_jobview(self):
        chain = MagicMock(spec=[])
        self.assertIsNone(get_jobview(chain))


if __name__ == "__main__":
    unittest.main()
