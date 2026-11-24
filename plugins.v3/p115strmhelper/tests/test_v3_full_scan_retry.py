from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest import TestCase
from unittest.mock import MagicMock


_spec = spec_from_file_location(
    "_full_scan_retry",
    Path(__file__).resolve().parents[1] / "helper/strm/full/scan.py",
)
_scan = module_from_spec(_spec)
_spec.loader.exec_module(_scan)
FullScanIterator = _scan.FullScanIterator
DirectoryScanError = _scan.DirectoryScanError

_upstream = {"__name__": "p115client.tool.iterdir"}
exec("def get_ancestors(cache, pid):\n    return cache[pid]\n", _upstream)


def _missing_directory() -> None:
    _upstream["get_ancestors"]({}, 2909903070567595380)


def _item(file_id: int) -> Dict[str, Any]:
    return {
        "id": file_id,
        "parent_id": 1,
        "name": f"{file_id}.mkv",
        "path": f"/media/{file_id}.mkv",
    }


class TestV3FullScanRetry(TestCase):
    """
    验证目录缓存恢复、批次交付与重试边界
    """

    def test_retry_preserves_partial_batch_and_deduplicates_delivered_files(
        self,
    ) -> None:
        """
        重试补齐失败批次，已交付文件不重复，旧后台缓存不会污染重试
        """
        caches = []
        closed = []

        def iterate(client: Any, **kwargs: Any) -> Iterator[Dict]:
            cache = kwargs["id_to_dirnode"]
            caches.append(cache)
            attempt = len(caches)
            try:
                if attempt == 2:
                    self.assertEqual(cache, {})
                    self.assertIsNot(cache, caches[0])
                    caches[0][99] = ("旧扫描迟到的目录", 0)
                    self.assertNotIn(99, cache)
                cache[1] = ("media", 0)
                yield _item(1)
                yield _item(2)
                yield _item(3)
                if attempt == 1:
                    _missing_directory()
                yield _item(4)
            finally:
                closed.append(attempt)

        warn = MagicMock()
        scanner = FullScanIterator(object(), iterate, {"cid": 1}, 2, "/media", warn)
        batches = list(scanner)
        self.assertEqual(
            [[item["id"] for item in batch] for batch in batches], [[1, 2], [3, 4]]
        )
        self.assertTrue(scanner.retried)
        self.assertEqual(closed, [1, 2])
        warn.assert_called_once()
        self.assertIn("重试（1/1）", warn.call_args.args[0])

    def test_second_missing_directory_reports_actionable_error(self) -> None:
        """
        持续缺失只尝试两次并保留原始异常
        """
        iterate = MagicMock(side_effect=lambda *args, **kwargs: _missing_directory())
        scanner = FullScanIterator(object(), iterate, {}, 2, "/媒体库", MagicMock())
        with self.assertRaises(DirectoryScanError) as caught:
            list(scanner)
        self.assertEqual(iterate.call_count, 2)
        self.assertIsInstance(caught.exception.__cause__, KeyError)
        for text in (
            "/媒体库",
            "重试 1 次",
            "2909903070567595380",
            "115 网页端",
            "不会清理",
        ):
            self.assertIn(text, str(caught.exception))

    def test_unrelated_errors_do_not_retry(self) -> None:
        """
        网络故障、字段缺失与其他来源的数字键异常原样报错
        """
        for error in (TimeoutError("超时"), KeyError("name"), KeyError(123)):
            with self.subTest(error=repr(error)):
                iterate = MagicMock(side_effect=error)
                warn = MagicMock()
                scanner = FullScanIterator(object(), iterate, {}, 1, "/media", warn)
                with self.assertRaises(type(error)) as caught:
                    list(scanner)
                self.assertIs(caught.exception, error)
                iterate.assert_called_once()
                warn.assert_not_called()

    def test_retry_network_failure_is_reported_without_a_third_attempt(self) -> None:
        """
        重试遇到不同错误时显示真实原因并停止
        """
        attempts = []

        def iterate(client: Any, **kwargs: Any) -> Iterator[Dict]:
            attempts.append(kwargs)
            if len(attempts) == 1:
                _missing_directory()
            raise TimeoutError("读取超时")

        scanner = FullScanIterator(object(), iterate, {}, 1, "/media", MagicMock())
        with self.assertRaisesRegex(DirectoryScanError, "TimeoutError：读取超时"):
            list(scanner)
        self.assertEqual(len(attempts), 2)

    def test_normal_scan_passes_parameters_and_isolates_cache(self) -> None:
        """
        正常扫描保留参数，末尾不足一批也正常交付
        """
        shared = {9: ("其他任务", 0)}
        kwargs = {
            "cid": 1,
            "with_path": True,
            "with_ancestors": True,
            "id_to_dirnode": shared,
        }
        iterate = MagicMock(return_value=iter([_item(1)]))
        scanner = FullScanIterator(object(), iterate, kwargs, 2, "/media", MagicMock())
        self.assertEqual(list(scanner), [(_item(1),)])
        self.assertFalse(scanner.retried)
        self.assertEqual(shared, {9: ("其他任务", 0)})
        self.assertEqual(iterate.call_args.kwargs, dict(kwargs, id_to_dirnode={}))

    def test_failed_scan_does_not_delete_or_report_success(self) -> None:
        """
        真实全量流程失败后保留文件，通知与历史显示扫描未完成
        """
        from test_v3_full_worker_lifecycle import TestV3FullWorkerLifecycle

        fixture = TestV3FullWorkerLifecycle()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        def iterate(*args: Any, **kwargs: Any) -> Iterator[Dict]:
            yield _item(1)
            _missing_directory()

        fixture.namespace["iter_files_skim"] = MagicMock(side_effect=iterate)
        helper = fixture.helper
        helper.remove_unless_strm = True
        helper._FullSyncStrmHelper__process_single_item = MagicMock(return_value=None)
        helper._FullSyncStrmHelper__apply_remove_unless_strm_path = MagicMock()
        helper._FullSyncStrmHelper__process_db_item = MagicMock(
            return_value=(set(), {"1"})
        )
        fixture.fixture.namespace["configer"].get_config.side_effect = lambda key: (
            True if key == "notify" else f"{fixture.temporary.name}#/media"
        )
        fixture.fixture.service.full_sync_strm_files()
        self.assertEqual(fixture.namespace["iter_files_skim"].call_count, 2)
        helper._FullSyncStrmHelper__process_single_item.assert_called_once()
        helper._FullSyncStrmHelper__apply_remove_unless_strm_path.assert_not_called()
        history = fixture.namespace[
            "StrmExecHistoryManager"
        ].append_run.call_args.kwargs
        self.assertFalse(history["success"])
        self.assertIn("清理目录缓存并重试 1 次后", history["error"])
        notification = fixture.fixture.namespace["post_message"].call_args.kwargs
        self.assertIn("未完成", notification["title"])
        self.assertIn("115 网页端", notification["text"])

    def test_recovered_strm_scan_skips_cleanup_and_processes_remaining_files(
        self,
    ) -> None:
        """
        恢复成功继续处理剩余文件，跳过混合扫描结果的删除操作
        """
        from test_v3_full_worker_lifecycle import TestV3FullWorkerLifecycle

        fixture = TestV3FullWorkerLifecycle()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        attempts = []

        def iterate(*args: Any, **kwargs: Any) -> Iterator[Dict]:
            attempts.append(kwargs)
            yield _item(1)
            if len(attempts) == 1:
                _missing_directory()
            yield _item(2)

        fixture.namespace["iter_files_skim"] = iterate
        helper = fixture.helper
        helper.remove_unless_strm = True
        helper._FullSyncStrmHelper__process_single_item = MagicMock(return_value=None)
        helper._FullSyncStrmHelper__apply_remove_unless_strm_path = MagicMock()
        helper._FullSyncStrmHelper__process_db_item = MagicMock(
            return_value=(set(), {"1", "2"})
        )
        helper.mediainfodownloader.batch_auto_downloader.return_value = (0, 0, {})
        self.assertTrue(helper.generate_strm_files(f"{fixture.temporary.name}#/media"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(helper.total_count, 2)
        self.assertEqual(helper._FullSyncStrmHelper__process_single_item.call_count, 2)
        helper._FullSyncStrmHelper__apply_remove_unless_strm_path.assert_not_called()
        helper.local_tree.compare_trees.assert_not_called()
        self.assertIsNone(helper.scan_error)

    def test_database_cleanup_requires_an_uninterrupted_scan(self) -> None:
        """
        数据库扫描恢复或失败都不删除幽灵记录，正常扫描仍会清理
        """
        from test_v3_full_worker_lifecycle import TestV3FullWorkerLifecycle

        for mode in ("normal", "recovered", "failed"):
            with self.subTest(mode=mode):
                fixture = TestV3FullWorkerLifecycle()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                attempts = []

                def iterate(*args: Any, **kwargs: Any) -> Iterator[Dict]:
                    attempts.append(kwargs)
                    yield _item(1)
                    if mode == "failed" or mode == "recovered" and len(attempts) == 1:
                        _missing_directory()

                fixture.namespace["iter_files_skim"] = iterate
                helper = fixture.helper
                helper._FullSyncStrmHelper__process_db_item = MagicMock(
                    return_value=(set(), {"1"})
                )
                result = helper.generate_database(f"{fixture.temporary.name}#/media")
                helper._FullSyncStrmHelper__process_db_item.assert_called_once()
                if mode == "normal":
                    helper.databasehelper.remove_ghost_records.assert_called_once()
                else:
                    helper.databasehelper.remove_ghost_records.assert_not_called()
                if mode == "failed":
                    self.assertFalse(result)
