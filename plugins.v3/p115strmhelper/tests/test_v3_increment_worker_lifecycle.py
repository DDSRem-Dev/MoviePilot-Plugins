from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Any
from unittest import TestCase
from unittest.mock import Mock

import test_v3_sync_lifecycle as sync_fixture
from test_increment_mapping import _load_helper


class TestV3IncrementWorkerLifecycle(TestCase):
    """
    验证增量失败和重试不会脱离 V3 在途保护留下本地扫描线程
    """

    def setUp(self) -> None:
        """
        使用真实增量入口和扫描线程，隔离目录树与云端边界
        """
        self.fixture = sync_fixture.TestV3SyncLifecycle()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        cls, self.namespace = _load_helper(Path(self.temporary.name), "txt")
        self.namespace["Thread"] = self._thread
        self.namespace["StrmExecHistoryManager"] = Mock()
        self.helper = cls(Mock(), Mock())
        self.helper.auto_download_mediainfo = False
        self.helper.mediainfodownloader.batch_auto_downloader.return_value = (0, 0, [])
        self.release = Event()
        self.entered = Event()
        self.failed = Event()
        self.finished = Event()
        self.children = []
        self.errors = []
        self.producer = None
        self.helper.local_tree.scan_directory_to_tree = Mock(side_effect=self._scan)
        self.fixture.namespace["IncrementSyncStrmHelper"] = lambda **kwargs: self.helper
        self.fixture.namespace["configer"].get_config.side_effect = (
            lambda key: False if key == "notify" else f"{self.temporary.name}#/media"
        )
        self.addCleanup(self._cleanup)

    def _thread(self, *args: Any, **kwargs: Any) -> Thread:
        thread = Thread(*args, **kwargs)
        self.children.append(thread)
        return thread

    def _scan(self, *args: Any, **kwargs: Any) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("增量本地扫描未获释放")

    def _cleanup(self) -> None:
        self.release.set()
        if self.producer:
            self.producer.join(timeout=2)
        for child in self.children:
            child.join(timeout=2)
        self.assertFalse(any(child.is_alive() for child in self.children))
        self.helper.__del__()

    def _run(self) -> None:
        try:
            self.fixture.service.increment_sync_strm_files()
        except Exception as error:
            self.errors.append(error)
        finally:
            self.finished.set()

    def _verify_failure(self, retry: bool, pending_full: bool = False) -> None:
        calls = []

        def fail(*args: Any, **kwargs: Any) -> None:
            self.assertTrue(self.entered.wait(timeout=2))
            calls.append(1)
            self.failed.set()
            raise RuntimeError("隔离目录树错误") if retry else ValueError("隔离普通错误")

        self.helper._IncrementSyncStrmHelper__generate_pan_tree = fail
        self.producer = Thread(target=self._run)
        self.producer.start()
        self.assertTrue(self.failed.wait(timeout=2))
        self.assertFalse(self.finished.wait(timeout=0.1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.children), 1)
        if pending_full:
            self.fixture.service.full_sync_strm_files()
            self.assertTrue(self.fixture.service._full_sync_pending)
            self.fixture.service._run_full_sync = Mock(
                side_effect=lambda: self.assertFalse(
                    any(child.is_alive() for child in self.children)
                )
            )
        self.assertFalse(self.fixture.service._stop_sync_operations(0))
        self.assertEqual(self.fixture.service._sync_operations, {self.producer: 1})
        self.release.set()
        self.producer.join(timeout=2)
        self.assertFalse(self.producer.is_alive())
        self.assertFalse(any(child.is_alive() for child in self.children))
        self.assertEqual(self.errors, [])
        self.assertEqual(len(calls), 3 if retry else 1)
        self.assertEqual(len(self.children), len(calls))
        self.assertTrue(self.fixture.service._stop_sync_operations(0))
        if pending_full:
            self.fixture.service._run_full_sync.assert_called_once_with()
            self.assertFalse(self.fixture.service._full_sync_pending)

    def test_failure_waits_for_local_scan(self) -> None:
        """
        普通异常返回前等待本地扫描，保留 V3 同步登记
        """
        self._verify_failure(retry=False)

    def test_retry_waits_before_starting_next_scan(self) -> None:
        """
        原三轮目录树重试前逐轮等待本地扫描，避免遗留在途线程
        """
        self._verify_failure(retry=True)

    def test_pending_full_waits_for_failed_increment_scan(self) -> None:
        """
        增量失败的扫描退出后才交接已登记的全量任务
        """
        self._verify_failure(retry=False, pending_full=True)
