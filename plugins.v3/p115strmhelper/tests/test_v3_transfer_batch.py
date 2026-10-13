import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest import TestCase


spec = importlib.util.spec_from_file_location(
    "p115_transfer_batch_contract",
    Path(__file__).resolve().parents[1] / "helper/transfer/batch.py",
)
batch = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = batch
spec.loader.exec_module(batch)


class TestV3TransferBatch(TestCase):
    """
    验证批量合并、租约隔离、逐文件失败和停止期间的结果交还
    """

    def test_batch_groups_keep_storage_instances_separate(self) -> None:
        """
        同组请求合并，其他存储实例和动作各自执行
        """
        calls = []

        def execute(operations):
            calls.append([operation.payload["id"] for operation in operations])
            for operation in operations:
                operation.future.set_result(operation.payload["id"])

        coordinator = batch.BatchCoordinator(execute, delay=0.1, max_size=4)
        barrier = Barrier(4)

        def submit(index):
            barrier.wait(timeout=3)
            key = ("account-a", "copy") if index < 2 else (index, "move")
            return coordinator.submit(key, {"id": index}, lambda: None)

        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(list(workers.map(submit, range(4))), list(range(4)))
        self.assertEqual(sorted(map(sorted, calls)), [[0, 1], [2], [3]])
        self.assertTrue(coordinator.shutdown())

    def test_lost_lease_never_reaches_cloud(self) -> None:
        """
        等待批次期间失去租约的操作不会被发送到网盘
        """
        calls = []
        coordinator = batch.BatchCoordinator(lambda items: calls.extend(items), delay=0)

        def lost():
            raise RuntimeError("lease lost")

        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            coordinator.submit("move", {}, lost)
        self.assertEqual(calls, [])
        self.assertTrue(coordinator.shutdown())

    def test_partial_result_survives_batch_exception(self) -> None:
        """
        一项已经成功时，批次后续异常仅返回给尚未完成的文件
        """
        barrier = Barrier(2)

        def execute(operations):
            operations.sort(key=lambda operation: operation.payload["id"])
            operations[0].future.set_result("confirmed")
            raise OSError("cloud timeout")

        coordinator = batch.BatchCoordinator(execute, delay=0.1, max_size=2)

        def submit(index):
            barrier.wait(timeout=3)
            return coordinator.submit("copy", {"id": index}, lambda: None)

        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(submit, 0)
            second = workers.submit(submit, 1)
            self.assertEqual(first.result(timeout=3), "confirmed")
            with self.assertRaisesRegex(OSError, "cloud timeout"):
                second.result(timeout=3)
        self.assertTrue(coordinator.shutdown())

    def test_shutdown_retains_running_operations(self) -> None:
        """
        停止超时不会提前宣布完成或丢弃原线程等待的结果
        """
        entered, release = Event(), Event()

        def execute(operations):
            entered.set()
            if not release.wait(timeout=3):
                raise AssertionError("测试未释放批次")
            for operation in operations:
                operation.future.set_result(True)

        coordinator = batch.BatchCoordinator(execute, delay=0)
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(coordinator.submit, "move", {}, lambda: None)
            try:
                self.assertTrue(entered.wait(timeout=3))
                self.assertFalse(coordinator.shutdown(timeout=0))
                self.assertFalse(result.done())
                with self.assertRaisesRegex(RuntimeError, "正在停止"):
                    coordinator.submit("copy", {}, lambda: None)
            finally:
                release.set()
            self.assertTrue(result.result(timeout=3))
        self.assertTrue(coordinator.shutdown())
