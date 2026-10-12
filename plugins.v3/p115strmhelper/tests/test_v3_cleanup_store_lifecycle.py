from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3CleanupStoreLifecycle(TestCase):
    """
    验证分享清理管理 API 在 V3 启用和禁用状态保持原行为
    """

    def setUp(self) -> None:
        """
        加载真实 API 与服务类，隔离 KV 读写边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            Query=lambda default=None, **kwargs: default,
            ApiResponse=lambda **kwargs: SimpleNamespace(**dict({"code": 0}, **kwargs)),
            share_strm_pending_queue=MagicMock(),
            share_strm_cleanup_summary_store=MagicMock(),
            share_strm_missing_media_store=MagicMock(),
        )
        self.pending = self.namespace["share_strm_pending_queue"]
        self.summary = self.namespace["share_strm_cleanup_summary_store"]
        self.missing = self.namespace["share_strm_missing_media_store"]
        self.entries = (
            ("share_strm_cleanup_pending_api", (), self.pending.list_pending_summaries, []),
            (
                "share_strm_cleanup_batch_paths_api",
                ("batch-id", 1, 50), self.pending.pending_batch_paths_page,
                (True, ["/isolated/file.strm"], 1),
            ),
            (
                "share_strm_cleanup_cancel_api", (SimpleNamespace(request_id="batch-id"),),
                self.pending.cancel_pending_batch, True,
            ),
            ("share_strm_cleanup_last_summary_api", (), self.summary.get, {"ok": True}),
            ("share_strm_missing_media_list_api", (1, 20), self.missing.page, ([], 0)),
            (
                "share_strm_missing_media_clear_api", (SimpleNamespace(clear_all=False, uid="uid"),),
                self.missing.clear, True,
            ),
            (
                "share_strm_missing_media_clear_api", (SimpleNamespace(clear_all=True),),
                self.missing.clear, True,
            ),
        )
        root = Path(__file__).resolve().parents[1]
        self.callbacks = {
            name: _method(root / "api.py", name, self.namespace)
            for name, _, _, _ in self.entries
        }

    def test_store_management_remains_available_when_stopped(self) -> None:
        """
        六类 API 的七个分支在同步服务停止后仍可管理实例 KV
        """
        for stopping in (False, True):
            self.service._sync_stopping = stopping
            for name, args, boundary, result in self.entries:
                with self.subTest(stopping=stopping, entry=name, args=args):
                    boundary.reset_mock()
                    boundary.return_value = result
                    response = self.callbacks[name](*args)
                    self.assertEqual(response.code, 0)
                    boundary.assert_called_once()
                    self.assertEqual(self.service._sync_operations, {})
                    self.assertEqual(self.service._sync_stopping, stopping)

    def test_original_responses_are_preserved(self) -> None:
        """
        原分页数据、摘要、取消和删除文案保持
        """
        expected = (
            {"code": 0, "data": {"batches": []}},
            {"code": 0, "data": {"paths": ["/isolated/file.strm"], "total": 1, "page": 1, "limit": 50}},
            {"code": 0, "msg": "已取消该批次"},
            {"code": 0, "data": {"summary": {"ok": True}}},
            {"code": 0, "data": {"items": [], "total": 0, "page": 1}},
            {"code": 0, "msg": "已删除"},
            {"code": 0, "msg": "已清空缺失媒体列表"},
        )
        for (name, args, boundary, result), response in zip(self.entries, expected):
            with self.subTest(entry=name, args=args):
                boundary.return_value = result
                self.assertEqual(vars(self.callbacks[name](*args)), response)
                self.assertEqual(self.service._sync_operations, {})

    def test_original_store_exceptions_are_preserved(self) -> None:
        """
        KV 异常继续返回原失败响应
        """
        for name, args, boundary, _ in self.entries:
            with self.subTest(entry=name, args=args):
                boundary.side_effect = ValueError("synthetic")
                response = self.callbacks[name](*args)
                self.assertEqual(response.code, 1)
                self.assertEqual(response.msg, "synthetic")
                self.assertEqual(self.service._sync_operations, {})
                boundary.side_effect = None
