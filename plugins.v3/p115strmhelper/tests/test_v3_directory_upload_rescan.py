import ast
import sys
from pathlib import Path
from queue import Queue
from re import search as re_search, IGNORECASE
from threading import Event, Lock, Thread, current_thread
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import TestCase
from unittest.mock import MagicMock


def _compile_nodes(
    path: Path, names: List[str], namespace: Dict[str, Any]
) -> None:
    """
    按名称抽取模块顶层节点并注入依赖后执行

    仅用于在无 MoviePilot 运行时的环境下验证纯逻辑组件
    """
    tree = ast.parse(path.read_text())
    wanted = [
        node
        for node in tree.body
        if (
            isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and node.name in names
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        )
    ]
    for node in wanted:
        node.decorator_list = []
    code = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *wanted,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(code), str(path), "exec"), namespace)


class _StubPaths:
    """路径清洗桩：非 Windows 平台保持原样"""

    @staticmethod
    def sanitize_path_parts(rel_path: Path) -> Path:
        return rel_path


class _StubStrmNames:
    """STRM 文件名桩：与插件默认模板一致"""

    @staticmethod
    def get_strm_filename(file_path: Path, *args: Any, **kwargs: Any) -> str:
        if file_path.suffix.lower() == ".iso":
            return f"{file_path.stem}.iso.strm"
        return f"{file_path.stem}.strm"


class _StubConfig:
    """插件配置桩：提供 get_config 与目录上传相关属性"""

    directory_upload_skip_bdmv_stream = True

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def get_config(self, key: str) -> Any:
        return self._data.get(key)


class TestDirectoryUploadRescan(TestCase):
    """
    验证漏传巡检的候选判定、上限与生命周期
    """

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.logger = MagicMock()
        self.config: Dict[str, Any] = {
            "directory_upload_uploadext": "mp4,mkv,iso",
            "directory_upload_path": [
                {"src": "/media/library", "dest_strm": "/media/library"}
            ],
        }
        self.submitted: List[Any] = []

        def submit(client: Any, file_path: str, mon_path: str) -> bool:
            self.submitted.append((file_path, mon_path))
            return True

        self.queue_gate = SimpleNamespace(submit=submit)
        self.namespace: Dict[str, Any] = {
            "logger": self.logger,
            "configer": _StubConfig(self.config),
            "Path": Path,
            "Event": Event,
            "Lock": Lock,
            "Thread": Thread,
            "current_thread": current_thread,
            "List": List,
            "Optional": Any,
            "Tuple": tuple,
            "P115Client": Any,
            "PathUtils": _StubPaths,
            "StrmGenerater": _StubStrmNames,
            "directory_upload_stability_tracker": self.queue_gate,
            "os_walk": __import__("os").walk,
            "re_search": re_search,
            "IGNORECASE": IGNORECASE,
        }
        _compile_nodes(
            self.root / "helper/monitor/__init__.py",
            [
                "_is_directory_upload_ignored_path",
                "_directory_upload_extensions",
                "DirectoryUploadRescan",
                "directory_upload_rescan",
            ],
            self.namespace,
        )
        self.rescan_cls = self.namespace["DirectoryUploadRescan"]
        self.addCleanup(self._stop_rescan)

    def _stop_rescan(self) -> None:
        self.namespace["directory_upload_rescan"].stop(timeout=2)

    def _build_tree(self, tmp: Path) -> Path:
        """
        构造包含各类候选与干扰项的媒体目录
        """
        library = tmp / "library"
        (library / "Show (2026)" / "Season 1").mkdir(parents=True)
        (library / "Show (2026)" / "Season 1" / "ep1.mkv").write_text("v")
        (library / "Show (2026)" / "Season 1" / "ep2.mkv").write_text("v")
        (library / "Show (2026)" / "Season 1" / "ep2.strm").write_text("s")
        (library / "Show (2026)" / "Season 1" / "ep1.srt").write_text("sub")
        (library / "Movie (2020)" / "movie.iso").parent.mkdir(parents=True)
        (library / "Movie (2020)" / "movie.iso").write_text("v")
        (library / "Movie (2020)" / "movie.iso.strm").write_text("s")
        (library / "BDMV" / "STREAM").mkdir(parents=True)
        (library / "BDMV" / "STREAM" / "00000.mkv").write_text("v")
        (library / ".hidden").mkdir(parents=True)
        (library / ".hidden" / "hidden.mkv").write_text("v")
        return library

    def test_collect_missing_only_returns_files_without_strm(self) -> None:
        """
        只收集上传候选文件中缺少对应 STRM 的条目
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            library = self._build_tree(Path(tmpdir))
            rescan = self.rescan_cls()
            missing = rescan._collect_missing([(str(library), str(library))], 50)

        found = {Path(path).name for path, _ in missing}
        self.assertEqual(found, {"ep1.mkv"})
        self.assertEqual({mon for _, mon in missing}, {str(library)})

    def test_collect_missing_respects_limit(self) -> None:
        """
        达到单轮上限即停止收集
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "library"
            (library / "A").mkdir(parents=True)
            for index in range(5):
                (library / "A" / f"ep{index}.mkv").write_text("v")
            rescan = self.rescan_cls()
            missing = rescan._collect_missing([(str(library), str(library))], 2)

        self.assertEqual(len(missing), 2)

    def test_tick_submits_missing_files_to_stability_tracker(self) -> None:
        """
        巡检按同一 STRM 规则推导并提交漏传文件
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            library = self._build_tree(Path(tmpdir))
            rescan = self.rescan_cls()
            rescan._max_submit = lambda: 10
            rescan._tick(None, [(str(library), str(library))])

        self.assertEqual(len(self.submitted), 1)
        self.assertTrue(self.submitted[0][0].endswith("ep1.mkv"))
        self.assertTrue(self.logger.warning.called)

    def test_tick_is_silent_when_nothing_is_missing(self) -> None:
        """
        没有漏传时只记录调试日志
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "library"
            (library / "A").mkdir(parents=True)
            (library / "A" / "ep1.mkv").write_text("v")
            (library / "A" / "ep1.strm").write_text("s")
            rescan = self.rescan_cls()
            rescan._tick(None, [(str(library), str(library))])

        self.assertEqual(self.submitted, [])
        self.assertFalse(self.logger.warning.called)

    def test_start_and_stop_are_idempotent(self) -> None:
        """
        巡检线程可重复启动并正常退出
        """
        rescan = self.namespace["directory_upload_rescan"]
        rescan.FIRST_SCAN_DELAY_SECONDS = 0.05
        entries = [("/media/library", "/media/library")]
        rescan._upload_entries = staticmethod(lambda: entries)
        rescan.start(object(), ["/media/library"])
        thread = rescan._thread
        self.assertIsNotNone(thread)
        rescan.start(object(), ["/media/library"])
        self.assertIs(rescan._thread, thread)
        self.assertTrue(rescan.stop(timeout=5))
        self.assertIsNone(rescan._thread)
        # 重复停止保持幂等
        self.assertTrue(rescan.stop(timeout=1))
        self.assertIsNone(rescan._thread)


class TestWorkerQueueSelfHeal(TestCase):
    """
    验证停止超时后残留的空队列可以自愈
    """

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.root = Path(__file__).resolve().parents[1]
        namespace = {
            "logger": self.logger,
            "Path": Path,
            "Queue": Queue,
            "Lock": Lock,
            "Thread": Thread,
            "current_thread": current_thread,
            "Optional": Any,
            "Any": Any,
        }
        _compile_nodes(self.root / "core/worker_queue.py", ["WorkerQueue"], namespace)
        self.queue_cls = namespace["WorkerQueue"]
        self.queues = []
        self.addCleanup(self._stop_queues)

    def _stop_queues(self) -> None:
        for queue in self.queues:
            queue.stop(timeout=2)

    def _queue(self, process):
        class QueueImpl(self.queue_cls):
            def _worker(self) -> None:
                while True:
                    task = self._queue.get()
                    if task is self._SENTINEL:
                        self._queue.task_done()
                        break
                    try:
                        process(task)
                    finally:
                        self._queue.task_done()

        queue = QueueImpl("test-queue", "测试队列")
        self.queues.append(queue)
        return queue

    def test_enqueue_recovers_from_stale_stopping_empty_queue(self) -> None:
        """
        停止超时留下的已退出 worker 与空队列不再永久拒收任务
        """
        processed = []
        queue = self._queue(processed.append)
        # 模拟 stop() 超时后的残留状态：停止标记仍在，worker 已退出，队列已排空
        queue._queue = Queue()
        queue._worker_thread = SimpleNamespace(is_alive=lambda: False)
        queue._stopping = True

        self.assertTrue(queue._enqueue_task("recovered"))
        self.assertTrue(queue.stop(timeout=5))
        self.assertEqual(processed, ["recovered"])

    def test_enqueue_still_rejects_while_worker_is_draining(self) -> None:
        """
        worker 仍在排空或停止流程未结束时继续拒绝入队，避免重复 worker
        """
        entered, release = Event(), Event()
        processed = []

        def process(value):
            if value == "first":
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("未释放任务")
            processed.append(value)

        queue = self._queue(process)
        queue.start()
        worker = queue._worker_thread
        try:
            self.assertTrue(queue._enqueue_task("first"))
            self.assertTrue(entered.wait(timeout=5))
            self.assertFalse(queue.stop(timeout=0))
            self.assertFalse(queue._enqueue_task("late"))
            self.assertIs(queue._worker_thread, worker)
        finally:
            release.set()
        self.assertTrue(queue.stop(timeout=5))
        self.assertEqual(processed, ["first"])


class TestResolveUploadedPickcode(TestCase):
    """
    验证上传后 pickcode 解析不再被复合文件 ID 打断
    """

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.root = Path(__file__).resolve().parents[1]
        self.lookup_calls: List[str] = []
        self.lookup_result: Any = "3537167417161549225"

        def get_id_to_path(client: Any, path: str, **kwargs: Any) -> Any:
            self.lookup_calls.append(path)
            return self.lookup_result

        namespace: Dict[str, Any] = {
            "logger": self.logger,
            "Path": Path,
            "Optional": Any,
            "Any": Any,
            "P115Client": Any,
            "FileItem": Any,
            "get_id_to_path": get_id_to_path,
            "configer": SimpleNamespace(get_ios_ua_app=lambda app=False: {}),
        }
        _compile_nodes(
            self.root / "helper/monitor/__init__.py",
            ["_resolve_uploaded_pickcode"],
            namespace,
        )
        self.resolve = namespace["_resolve_uploaded_pickcode"]

    def _client(self, pickcode: str = "azogetestpick0001") -> Any:
        return SimpleNamespace(to_pickcode=lambda file_id: pickcode)

    def test_plain_numeric_fileid_is_used_directly(self) -> None:
        """
        纯数字文件 ID 直接转换，不做多余的路径查询
        """
        item = SimpleNamespace(fileid="1234567890123456789")
        self.assertEqual(
            self.resolve(self._client(), item, Path("/x/y.mp4")),
            "azogetestpick0001",
        )
        self.assertEqual(self.lookup_calls, [])

    def test_composite_fileid_falls_back_to_path_lookup(self) -> None:
        """
        CloudDrive2 复合 ID 不当作文件 ID，改用按路径查询
        """
        item = SimpleNamespace(fileid="3537167417161549225/斗破苍穹 - S05E193.mp4")
        self.assertEqual(
            self.resolve(
                self._client(), item, Path("/115open/MoviePilot/媒体库/a.mp4")
            ),
            "azogetestpick0001",
        )
        self.assertEqual(self.lookup_calls, ["/115open/MoviePilot/媒体库/a.mp4"])

    def test_unresolvable_fileid_returns_none(self) -> None:
        """
        无法解析文件 ID 时返回 None 而不是抛异常
        """
        item = SimpleNamespace(fileid="3537167417161549225/名字.mp4")
        self.lookup_result = None
        self.assertIsNone(self.resolve(self._client(), item, Path("/a.mp4")))

    def test_invalid_pickcode_is_rejected(self) -> None:
        """
        非法 pickcode 被拒绝，交由调用方保留本地文件重试
        """
        item = SimpleNamespace(fileid="123")
        self.assertIsNone(self.resolve(self._client(pickcode="short"), item))
