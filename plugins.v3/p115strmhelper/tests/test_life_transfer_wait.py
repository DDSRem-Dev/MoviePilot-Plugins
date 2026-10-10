"""
生活事件整理等待测试模块
"""

import importlib.util
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _load_transfer_wait_module() -> Any:
    """
    加载整理等待模块

    :return Any: 已加载模块
    """
    module_path = (
        Path(__file__).resolve().parents[1] / "helper" / "life" / "transfer_wait.py"
    )
    spec = importlib.util.spec_from_file_location(
        "life_transfer_wait_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLifeTransferWait(TestCase):
    """
    测试生活事件整理等待上限
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载待测模块
        """
        cls.module = _load_transfer_wait_module()

    def test_timeout_resumes_monitoring_with_pending_tasks(self) -> None:
        """
        同一队列持续无变化达到上限后记录残留任务并恢复监控
        """
        tasks = ["task-1"]
        get_queue_tasks = MagicMock(return_value=tasks)
        log = MagicMock()

        with (
            patch.object(self.module, "time", side_effect=[0, 60]),
            patch.object(self.module, "sleep"),
        ):
            stopped = self.module.wait_for_transfer_complete(
                get_queue_tasks=get_queue_tasks,
                stall_timeout_minutes=1,
                stop_event=None,
                log=log,
            )

        self.assertFalse(stopped)
        log.warning.assert_called_once_with(
            "【监控生活事件】MoviePilot 整理队列已连续 %s 分钟无变化，"
            "仍有 %s 个任务未结束，将恢复生活事件监控: %s",
            1,
            1,
            tasks,
        )

    def test_queue_change_resets_timeout(self) -> None:
        """
        队列任务或状态变化时重置无变化计时
        """
        get_queue_tasks = MagicMock(
            side_effect=[
                [{"id": "task-1", "status": "running"}],
                [{"id": "task-1", "status": "finished"}],
                [],
            ]
        )
        log = MagicMock()

        with (
            patch.object(self.module, "time", side_effect=[0, 70]),
            patch.object(self.module, "sleep"),
        ):
            stopped = self.module.wait_for_transfer_complete(
                get_queue_tasks=get_queue_tasks,
                stall_timeout_minutes=1,
                stop_event=None,
                log=log,
            )

        self.assertFalse(stopped)
        log.warning.assert_not_called()

    def test_stop_event_interrupts_waiting(self) -> None:
        """
        停止事件立即中断等待
        """
        stop_event = MagicMock()
        stop_event.wait.return_value = True

        with patch.object(self.module, "time", return_value=0):
            stopped = self.module.wait_for_transfer_complete(
                get_queue_tasks=MagicMock(return_value=["task-1"]),
                stall_timeout_minutes=60,
                stop_event=stop_event,
                log=MagicMock(),
            )

        self.assertTrue(stopped)
        stop_event.wait.assert_called_once_with(timeout=20)
