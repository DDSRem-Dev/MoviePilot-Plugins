from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import batched
from json import dumps as json_dumps
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter
from types import MethodType, SimpleNamespace
from typing import Any, Dict, Generator, List, Optional, Set, Tuple
from unittest import TestCase
from unittest.mock import MagicMock

import test_v3_sync_lifecycle as sync_fixture
from test_v3_worker_queue import _compile


class TestV3FullWorkerLifecycle(TestCase):
    """
    验证全量提前退出时仍等待子线程，避免 V3 提前释放实例资源
    """

    def setUp(self) -> None:
        """
        使用真实全量线程与服务准入，隔离云端和文件读写
        """
        self.fixture = sync_fixture.TestV3SyncLifecycle()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.release = Event()
        self.entered = Event()
        self.failed = Event()
        self.finished = Event()
        self.children = []
        self.errors = []
        self.producer = None
        self.config = SimpleNamespace(
            full_sync_process_rust=False,
            full_sync_process_num=1,
            full_sync_iter_function="iter_files_with_path_skim",
            full_sync_batch_num=1,
        )
        self.namespace = dict(
            Any=Any, Dict=Dict, List=List, Optional=Optional, Set=Set, Tuple=Tuple,
            Path=Path, Thread=self._thread, ThreadPoolExecutor=ThreadPoolExecutor,
            as_completed=as_completed, dumps=lambda item: json_dumps(item).encode(),
            Queue=Queue, Empty=Empty, batched=batched, perf_counter=perf_counter,
            configer=self.config, logger=MagicMock(), P115Client=object,
            MediaInfoDownloader=object, CBase64=MagicMock(),
            StrmExecHistoryManager=MagicMock(), sentry_manager=MagicMock(),
            get_pid_by_path=MagicMock(return_value=1),
            iter_files_skim=MagicMock(return_value=iter(())),
            ProcessResult=namedtuple(
                "ProcessResult", ["status", "path", "message", "data", "path_entry"]
            ),
        )
        cls = _compile(
            self.fixture.root / "helper/strm/full/__init__.py",
            self.namespace,
            "FullSyncStrmHelper",
        )
        self.helper = object.__new__(cls)
        for name in (
            "total_count", "elapsed_time", "total_db_write_count", "strm_count",
            "mediainfo_count", "strm_fail_count", "mediainfo_fail_count",
            "remove_unless_strm_count", "strm_cleanup_deferred_count",
        ):
            setattr(self.helper, name, 0)
        self.helper.strm_exec_history_kind = None
        self.helper.strm_exec_history_extra = None
        self.helper.strm_fail_dict = {}
        self.helper.mediainfo_fail_dict = []
        self.helper.download_mediainfo_list = []
        self.helper._deferred_cleanup_paths = []
        self.helper.remove_unless_strm = False
        self.helper.client = object()
        self.helper.local_tree = MagicMock()
        self.helper.pan_tree = MagicMock()
        self.helper.databasehelper = MagicMock()
        self.helper.mediainfodownloader = MagicMock()
        self.helper.mediaserver_helper = MagicMock(enabled=False)
        self.helper.write_queue = Queue()
        self.helper.result_queue = Queue()
        self.fixture.namespace["FullSyncStrmHelper"] = lambda **kwargs: self.helper
        self.fixture.namespace["configer"].get_config.side_effect = (
            lambda key: False if key == "notify" else f"{self.temporary.name}#/media"
        )
        self.config.get_ios_ua_app = lambda: {}
        self.config.get_config = lambda key: getattr(self.config, key)
        self.addCleanup(self._cleanup)

    def _thread(self, *args: Any, **kwargs: Any) -> Thread:
        thread = Thread(*args, **kwargs)
        self.children.append(thread)
        return thread

    def _block(self, *args: Any, **kwargs: Any) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("全量线程未获释放")

    def _cleanup(self) -> None:
        self.release.set()
        if self.producer:
            self.producer.join(timeout=2)
        if any(child.is_alive() for child in self.children):
            for _ in range(8):
                self.helper.write_queue.put(None)
        for child in self.children:
            child.join(timeout=2)
        self.assertFalse(any(child.is_alive() for child in self.children))

    def _run(self) -> None:
        try:
            self.fixture.service.full_sync_strm_files()
        except Exception as error:
            self.errors.append(error)
        finally:
            self.finished.set()

    def _assert_waits(self) -> None:
        self.producer = Thread(target=self._run)
        self.producer.start()
        self.assertTrue(self.entered.wait(timeout=2))
        self.assertTrue(self.failed.wait(timeout=2))
        self.assertFalse(self.finished.wait(timeout=0.1))
        self.assertFalse(self.fixture.service._stop_sync_operations(0))
        self.assertEqual(self.fixture.service._sync_operations, {self.producer: 1})
        self.release.set()
        self.producer.join(timeout=2)
        self.assertFalse(self.producer.is_alive())
        self.assertFalse(any(child.is_alive() for child in self.children))
        self.assertEqual(self.errors, [])
        self.assertTrue(self.fixture.service._stop_sync_operations(0))
        self.assertEqual(self.helper.write_queue.unfinished_tasks, 0)
        self.assertEqual(self.helper.result_queue.unfinished_tasks, 0)

    def test_failed_path_lookup_waits_for_local_scan(self) -> None:
        """
        网盘路径解析失败后，本地扫描退出前仍阻止 V3 停止
        """
        self.helper.remove_unless_strm = True
        self.helper.local_tree.scan_directory_to_tree.side_effect = self._block

        def fail(*args: Any) -> None:
            self.failed.set()
            raise RuntimeError("隔离路径解析失败")

        self.namespace["get_pid_by_path"] = fail
        self._assert_waits()

    def test_failed_iteration_waits_for_submitted_writes(self) -> None:
        """
        云端迭代中断后，已提交写入及结果收集退出前仍阻止 V3 停止
        """
        item = {"id": 1, "parent_id": 0, "name": "a.mkv", "path": "/media/a.mkv"}

        def iterate(*args: Any, **kwargs: Any) -> Generator[Dict, None, None]:
            yield item
            self.failed.set()
            raise RuntimeError("隔离迭代失败")

        def submit(owner: Any, *args: Any) -> Any:
            owner.write_queue.put((Path(self.temporary.name) / "a.strm", "url", "a.mkv"))
            return self.namespace["ProcessResult"]("submitted", None, None, None, None)

        self.namespace["iter_files_skim"] = iterate
        self.helper._FullSyncStrmHelper__process_single_item = MethodType(submit, self.helper)
        self.helper._FullSyncStrmHelper__flush_write_buffer = self._block
        self._assert_waits()

    def test_invalid_mapping_joins_idle_workers(self) -> None:
        """
        路径配置异常向上传播时，空闲 IO 和收集线程也必须退出
        """
        self.fixture.namespace["configer"].get_config.return_value = "invalid"
        self.fixture.namespace["configer"].get_config.side_effect = None
        self._run()
        self.assertEqual(len(self.errors), 1)
        self.assertIsInstance(self.errors[0], IndexError)
        self.assertFalse(any(child.is_alive() for child in self.children))
