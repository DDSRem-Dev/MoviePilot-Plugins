import ast
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Barrier, Event, Lock, Thread, current_thread
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _compile(path: Path, namespace: Dict[str, Any], class_name: str = "") -> Any:
    tree = ast.parse(path.read_text())
    if class_name:
        nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        nodes[0].decorator_list = []
    else:
        nodes = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.ImportFrom) and node.module == "app.sdk.logging"
            )
        ]
    code = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *nodes,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(code), str(path), "exec"), namespace)
    return namespace[class_name] if class_name else namespace["WorkerQueue"]


class TestV3WorkerQueue(TestCase):
    """
    使用三类真实业务 worker 验证停止屏障和并发入队
    """

    def setUp(self) -> None:
        """
        加载队列真实代码并替换云端处理回调
        """
        self.root = Path(__file__).resolve().parents[1]
        self.logger = MagicMock()
        self.base = _compile(
            self.root / "core/worker_queue.py", {"logger": self.logger}
        )
        self.queues = []
        self.restorers = []
        self.addCleanup(self._stop_queues)

    def _stop_queues(self) -> None:
        for queue in self.queues:
            queue.stop(timeout=2)
        for restore in reversed(self.restorers):
            restore()

    def _queue(self, kind: str, process: Any):
        package_name = f"_p115_worker_queue_test_{kind}"
        package = ModuleType(package_name)
        package.__path__ = []
        original = sys.modules.get(package_name)
        sys.modules[package_name] = package

        def restore() -> None:
            if original is None:
                sys.modules.pop(package_name, None)
            else:
                sys.modules[package_name] = original

        self.restorers.append(restore)
        namespace = {
            "__package__": package_name,
            "__name__": package_name + ".implementation",
            "WorkerQueue": self.base,
            "logger": self.logger,
            "Path": Path,
        }
        if kind == "directory":
            package.process_file_change = lambda client, file_path, *args: process(
                file_path
            )
            cls = _compile(
                self.root / "helper/monitor/directory_upload_queue.py",
                namespace,
                "DirectoryUploadQueue",
            )
            queue = cls()
            enqueue = lambda value: queue.enqueue(
                SimpleNamespace(
                    client=None,
                    file_path=value,
                    mon_path="/",
                    stable_ready=False,
                    stable_signature=None,
                )
            )
        elif kind == "webhook":
            package.MediaSyncDelHelper = lambda: SimpleNamespace(
                sync_del_by_webhook=lambda **kwargs: process(kwargs["event_data"])
            )
            cls = _compile(
                self.root / "helper/mediasyncdel/webhook_queue.py",
                namespace,
                "SyncDelWebhookQueue",
            )
            queue = cls()
            enqueue = lambda value: queue.enqueue(
                SimpleNamespace(
                    event_data=value,
                    enabled=True,
                    notify=False,
                    del_source=False,
                    p115_library_path=None,
                    p115_force_delete_files=False,
                )
            )
        else:
            namespace.update(
                configer=SimpleNamespace(native_emby_mediainfo_enabled=True),
                EmbyMediaInfoOperate=lambda **kwargs: SimpleNamespace(
                    get_mediainfo_native=lambda path: process(str(path))
                ),
                EmbyMediainfoTask=SimpleNamespace,
                sleep=lambda delay: None,
            )
            cls = _compile(
                self.root / "helper/mediaserver/emby.py",
                namespace,
                "EmbyMediainfoQueue",
            )
            queue = cls()
            enqueue = lambda value: queue.enqueue("test", value)
        self.queues.append(queue)
        return queue, enqueue

    def test_timeout_retains_worker_and_drains_only_accepted_tasks(self) -> None:
        """
        超时保持原 worker，重复停止只放一个哨兵且不接收迟到任务
        """
        for kind in ("directory", "webhook", "emby"):
            with self.subTest(kind=kind):
                entered, release = Event(), Event()
                processed = []

                def process(value):
                    if value == "first":
                        entered.set()
                        if not release.wait(timeout=5):
                            raise AssertionError("未释放任务")
                    processed.append(value)

                queue, enqueue = self._queue(kind, process)
                queue.start()
                worker, buffer = queue._worker_thread, queue._queue
                try:
                    self.assertTrue(enqueue("first"))
                    self.assertTrue(entered.wait(timeout=5))
                    self.assertTrue(enqueue("second"))
                    self.assertIs(queue.stop(timeout=0), False)
                    self.assertIs(queue.stop(timeout=0), False)
                    self.assertIs(queue._worker_thread, worker)
                    self.assertIs(queue._queue, buffer)
                    self.assertEqual(buffer.qsize(), 2)
                    self.assertFalse(enqueue("late"))
                    with self.assertRaises(RuntimeError):
                        queue.start()
                finally:
                    release.set()
                self.assertIs(queue.stop(timeout=2), True)
                self.assertEqual(processed, ["first", "second"])
                self.assertEqual(buffer.unfinished_tasks, 0)
                self.assertFalse(enqueue("after-stop"))
                queue.start()
                self.assertTrue(enqueue("restarted"))
                self.assertTrue(queue.stop(timeout=2))
                self.assertEqual(processed, ["first", "second", "restarted"])

    def test_concurrent_enqueue_and_stop_have_no_tasks_after_sentinel(self) -> None:
        """
        并发停止与入队保持受理结果和实际处理集合一致
        """
        for kind in ("directory", "webhook", "emby"):
            with self.subTest(kind=kind):
                processed = []
                queue, enqueue = self._queue(kind, processed.append)
                queue.start()
                barrier = Barrier(9)

                def submit(index):
                    barrier.wait(timeout=5)
                    return str(index), enqueue(str(index))

                def stop():
                    barrier.wait(timeout=5)
                    return queue.stop(timeout=2)

                with ThreadPoolExecutor(max_workers=9) as executor:
                    futures = [executor.submit(submit, index) for index in range(8)]
                    stopped = executor.submit(stop)
                    results = [future.result(timeout=5) for future in futures]
                    self.assertTrue(stopped.result(timeout=5))
                self.assertEqual(
                    sorted(processed),
                    sorted(value for value, accepted in results if accepted),
                )
                self.assertFalse(enqueue("late"))

    def test_business_exception_does_not_prevent_drain(self) -> None:
        """
        单项业务异常被原 worker 处理后仍结算并继续排空
        """
        for kind in ("directory", "webhook", "emby"):
            with self.subTest(kind=kind):
                process = MagicMock(
                    side_effect=[RuntimeError("business failure"), None]
                )
                queue, enqueue = self._queue(kind, process)
                queue.start()
                enqueue("first")
                enqueue("second")
                self.assertTrue(queue.stop(timeout=2))
                self.assertEqual(process.call_count, 2)

    def test_self_stop_closes_admission_without_joining_itself(self) -> None:
        """
        业务回调在本线程停止时不自 join 且由后续调用确认退出
        """
        queue = None
        done = Event()
        results = []

        def process(value):
            results.append(queue.stop(timeout=0))
            done.set()

        queue, enqueue = self._queue("webhook", process)
        self.assertTrue(enqueue("lazy"))
        self.assertTrue(done.wait(timeout=5))
        self.assertEqual(results, [False])
        self.assertTrue(queue.stop(timeout=2))

    def test_dead_worker_never_discards_unsettled_queue(self) -> None:
        """
        异常死亡线程留下的未结算任务不会被重新启动覆盖
        """
        queue, _ = self._queue("directory", lambda value: None)
        buffer = Queue()
        buffer.put("pending")
        queue._queue = buffer
        queue._worker_thread = SimpleNamespace(is_alive=lambda: False)
        self.assertFalse(queue.stop(timeout=0))
        self.assertIs(queue._queue, buffer)
        with self.assertRaises(RuntimeError):
            queue.start()
        self.assertEqual(buffer.get_nowait(), "pending")
        buffer.task_done()
        self.assertTrue(queue.stop(timeout=0))

    def test_worker_self_stop_during_external_join_does_not_wait_for_lifecycle_lock(
        self,
    ) -> None:
        """
        外部停止等待 worker 时，业务回调仍能请求停止并及时退出
        """
        for kind in ("directory", "webhook", "emby"):
            with self.subTest(kind=kind):
                joining = Event()
                results = []

                def process(value):
                    if not joining.wait(timeout=5):
                        raise AssertionError("外部停止未开始等待")
                    results.append(queue.stop())

                queue, enqueue = self._queue(kind, process)
                queue.start()
                worker = queue._worker_thread
                join = worker.join

                def external_join(timeout):
                    joining.set()
                    join(timeout=2)

                try:
                    self.assertTrue(enqueue("self-stop"))
                    with patch.object(worker, "join", side_effect=external_join):
                        self.assertTrue(queue.stop())
                    self.assertEqual(results, [False])
                    self.assertFalse(worker.is_alive())
                finally:
                    joining.set()
                    queue.stop(timeout=2)

    def test_webhook_stop_before_first_task_requires_explicit_restart(self) -> None:
        """
        尚未启动的 webhook 队列被停止后不被迟到事件复活
        """
        queue, enqueue = self._queue("webhook", lambda value: None)
        self.assertTrue(queue.stop(timeout=0))
        self.assertFalse(enqueue("late"))
        queue.start()
        self.assertTrue(enqueue("current"))
        self.assertTrue(queue.stop(timeout=2))

    def _tracker(self):
        namespace = {
            "Event": Event,
            "Lock": Lock,
            "Thread": Thread,
            "current_thread": current_thread,
            "OrderedDict": OrderedDict,
            "Path": Path,
            "logger": self.logger,
            "DIRECTORY_STABLE_INTERVAL": 0.001,
            "DIRECTORY_STABLE_CHECKS": 1,
            "DIRECTORY_UNSTABLE_WARN_INTERVAL": 100,
        }
        cls = _compile(
            self.root / "helper/monitor/__init__.py",
            namespace,
            "DirectoryStabilityTracker",
        )
        tracker = cls()
        self.queues.append(tracker)
        return tracker

    def test_stability_tracker_self_stop_during_external_join(self) -> None:
        """
        稳定性跟踪扫描内部停止不与外部 join 互相等待
        """
        tracker = self._tracker()
        entered, joining = Event(), Event()
        results = []

        def tick():
            entered.set()
            if not joining.wait(timeout=5):
                raise AssertionError("外部停止未开始等待")
            results.append(tracker.stop())

        tracker._tick = tick
        tracker.start()
        worker = tracker._thread
        join = worker.join

        def external_join(timeout):
            joining.set()
            join(timeout=2)

        try:
            self.assertTrue(entered.wait(timeout=5))
            with patch.object(worker, "join", side_effect=external_join):
                self.assertTrue(tracker.stop())
            self.assertEqual(results, [False])
            self.assertFalse(worker.is_alive())
        finally:
            joining.set()
            tracker.stop(timeout=2)

    def test_stability_tracker_does_not_replace_stopping_thread_or_clients(
        self,
    ) -> None:
        """
        稳定性跟踪扫描尚未退出时不新建线程或替换已有客户端
        """
        tracker = self._tracker()
        entered, release = Event(), Event()
        old_client = object()
        pending = SimpleNamespace(client=old_client)
        tracker._pending[("file", "root")] = pending

        def tick():
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("未释放扫描")

        tracker._tick = tick
        tracker.start()
        worker = tracker._thread
        try:
            self.assertTrue(entered.wait(timeout=5))
            self.assertFalse(tracker.stop(timeout=0))
            with self.assertRaises(RuntimeError):
                tracker.start(client=object())
            self.assertIs(tracker._thread, worker)
            self.assertIs(pending.client, old_client)
        finally:
            release.set()
        self.assertTrue(tracker.stop(timeout=2))
        new_client = object()
        tracker.start(client=new_client)
        self.assertIs(pending.client, new_client)
        self.assertTrue(tracker.stop(timeout=2))

    def test_enqueue_failure_returns_false_without_stopping_existing_worker(
        self,
    ) -> None:
        """
        入队异常准确返回失败且不替换已运行的 worker
        """
        queue, enqueue = self._queue("directory", lambda value: None)
        queue.start()
        worker = queue._worker_thread
        with patch.object(queue._queue, "put_nowait", side_effect=OSError("failure")):
            self.assertFalse(enqueue("failed"))
        self.assertIs(queue._worker_thread, worker)
        self.assertTrue(queue.stop(timeout=2))

    def test_emby_invalid_task_returns_false_and_keeps_worker(self) -> None:
        """
        Emby 任务模型拒绝参数时准确返回失败且不影响后续任务
        """
        processed = []
        queue, enqueue = self._queue("emby", processed.append)
        queue.start()
        with patch.dict(
            type(queue).enqueue.__globals__,
            {"EmbyMediainfoTask": MagicMock(side_effect=ValueError("invalid task"))},
        ):
            self.assertFalse(enqueue("invalid"))
        self.assertTrue(enqueue("valid"))
        self.assertTrue(queue.stop(timeout=2))
        self.assertEqual(processed, ["valid"])
