import runpy
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

import test_v3_transfer_strm as transfer_fixture
from test_v3_share_queue_lifecycle import _method


SIZES = (
    (3199750636, 3199057349),
    (1095216660, 1099528789),
    (1879048192, 1873923911),
    (951949722, 951951920),
)


class TestV3TransferSize(TestCase):
    """
    验证显示大小事件、精确快照及历史误判的定向恢复
    """

    def setUp(self) -> None:
        """
        复用真实领域对象、临时 SQLite 与文件发布流程
        """
        self.case = transfer_fixture.TestV3TransferStrm()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.store = self.case.processor.TransferPostprocessStore()

    def _item(self, recorded: int, actual: int, name: str = "Example.S01E01.mkv"):
        item = self.case._item(name)
        target = item["transferinfo"].target_item
        target.size = recorded
        self.case.remote_files[(target.storage, target.path)] = target.model_copy(
            update={"size": actual}
        )
        key = self.case.processor.event_key(
            item, self.case.types.EventType.TransferComplete
        )
        return item, key

    def _legacy(self, recorded: int = SIZES[0][0], actual: int = SIZES[0][1]):
        item, key = self._item(recorded, actual)
        with patch.object(
            self.case.helper, "_prepare_file", side_effect=OSError("disk")
        ):
            with self.assertRaises(OSError):
                self.case._run(item)
        plan = self.store.load(key)["plan"]
        plan["identity"].pop("size_source", None)
        plan["identity"]["size"] = recorded
        plan["target"]["size"] = recorded
        for operation in plan["operations"]:
            operation["identity"].pop("size_source", None)
            operation["identity"]["size"] = recorded
        self.store.save(key, plan, "superseded")
        return item, key

    def _retry(self, key: str) -> str:
        return self.case.helper.retry_postprocess(
            key, self.case.client, self.case.downloader
        )

    def test_display_sizes_use_precise_snapshot_and_preserve_event(self) -> None:
        """
        四组实际误差均生成 STRM，索引与归属记录精确大小且不修改原事件
        """
        for index, (recorded, actual) in enumerate(SIZES):
            with self.subTest(size=recorded):
                item, key = self._item(recorded, actual, f"Example.S01E0{index}.mkv")
                frozen = self.case.durable.snapshot_transfer_result(item)
                self.case.outbox[self.case.types.EventType.TransferComplete.value](
                    SimpleNamespace(payload=frozen)
                )
                record = self.store.load(key)
                self.assertEqual(record["state"], "done")
                plan = record["plan"]
                output = Path(plan["operations"][0]["path"])
                self.assertEqual(output.read_text(), "https://example.invalid/video")
                self.assertEqual(plan["identity"]["size"], actual)
                self.assertEqual(plan["target"]["size"], actual)
                self.assertEqual(self.store.owner(output)["identity"]["size"], actual)
                self.assertEqual(item["transferinfo"].target_item.size, recorded)
                self.case._run(item)
        self.assertEqual(self.case.scrape.call_count, len(SIZES))

    def test_identity_conflicts_stop_before_normalizing_size(self) -> None:
        """
        文件 ID 或 pickcode 任一冲突时不接受同路径的新文件
        """
        for field, value in (("fileid", "202"), ("pickcode", "b" * 17)):
            with self.subTest(field=field):
                item, key = self._item(*SIZES[0], name=f"{field}.mkv")
                target = item["transferinfo"].target_item
                setattr(
                    self.case.remote_files[(target.storage, target.path)], field, value
                )
                self.case._run(item)
                self.assertEqual(self.store.load(key)["state"], "superseded")
        self.case.scrape.assert_not_called()

    def test_missing_precise_size_is_retryable(self) -> None:
        """
        回源缺少大小保留待处理状态，恢复精确数据后可完成
        """
        item, key = self._item(SIZES[0][0], None)
        with self.assertRaisesRegex(RuntimeError, "精确大小"):
            self.case._run(item)
        self.assertEqual(self.store.load(key)["state"], "pending")
        target = item["transferinfo"].target_item
        self.case.remote_files[(target.storage, target.path)].size = SIZES[0][1]
        self.case._run(item)
        self.assertEqual(self.store.load(key)["state"], "done")

    def test_size_change_during_preparation_does_not_publish(self) -> None:
        """
        暂存文件准备期间云端大小变化仍阻止发布
        """
        item, key = self._item(*SIZES[0])
        target = item["transferinfo"].target_item
        prepare = self.case.helper._prepare_file

        def change(plan, staged, downloader):
            prepare(plan, staged, downloader)
            self.case.remote_files[(target.storage, target.path)].size += 1

        with patch.object(self.case.helper, "_prepare_file", side_effect=change):
            self.case._run(item)
        record = self.store.load(key)
        self.assertEqual(record["state"], "superseded")
        self.assertFalse(Path(record["plan"]["operations"][0]["path"]).exists())
        with self.assertRaises(ValueError):
            self._retry(key)

    def test_legacy_recovery_executes_and_duplicate_is_idempotent(self) -> None:
        """
        旧终态普通重投仍跳过，显式恢复会生成文件并仅执行一次效果
        """
        item, key = self._legacy()
        self.case._run(item)
        self.assertEqual(self.store.load(key)["state"], "superseded")
        self.assertEqual(self._retry(key), "done")
        self.assertEqual(self._retry(key), "done")
        plan = self.store.load(key)["plan"]
        self.assertTrue(Path(plan["operations"][0]["path"]).exists())
        self.assertEqual(plan["identity"]["size"], SIZES[0][1])
        self.case.scrape.assert_called_once()

    def test_legacy_recovery_failure_resumes_only_remaining_effect(self) -> None:
        """
        恢复后的刮削失败保留文件检查点，下次重试不重新生成文件
        """
        _, key = self._legacy()
        self.case.scrape.side_effect = RuntimeError("scrape")
        with self.assertRaisesRegex(RuntimeError, "scrape"):
            self._retry(key)
        self.assertEqual(self.store.load(key)["state"], "pending")
        self.case.scrape.side_effect = None
        with patch.object(
            self.case.helper, "_prepare_file", side_effect=AssertionError
        ):
            self.assertEqual(self._retry(key), "done")

    def test_legacy_recovery_refuses_unrelated_size_difference(self) -> None:
        """
        不能用大小容差复活普通的真实大小变化记录
        """
        _, key = self._legacy(3199057348, 3199057349)
        before = self.store.load(key)
        with self.assertRaises(ValueError):
            self._retry(key)
        self.assertEqual(self.store.load(key), before)

    def test_legacy_recovery_preserves_new_local_file(self) -> None:
        """
        人工补齐或新事件写入的本地文件不会被旧记录覆盖
        """
        _, key = self._legacy()
        before = self.store.load(key)
        output = Path(before["plan"]["operations"][0]["path"])
        output.write_text("newer")
        with self.assertRaises(ValueError):
            self._retry(key)
        self.assertEqual(output.read_text(), "newer")
        self.assertEqual(self.store.load(key), before)

    def test_legacy_recovery_cloud_failure_keeps_terminal_record(self) -> None:
        """
        恢复核验的查询异常不会提前解除终态
        """
        _, key = self._legacy()
        before = self.store.load(key)
        self.case.storage.get_file_item_strict.side_effect = RuntimeError("offline")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            self._retry(key)
        self.assertEqual(self.store.load(key), before)

    def test_legacy_recovery_rejects_replaced_or_missing_cloud_file(self) -> None:
        """
        旧终态恢复不能写入已删除或被其他文件替换的目标
        """
        item, key = self._legacy()
        target = item["transferinfo"].target_item
        cloud_key = (target.storage, target.path)
        current = self.case.remote_files[cloud_key]
        before = self.store.load(key)
        for replacement in (None, current.model_copy(update={"fileid": "202"})):
            with self.subTest(replacement=replacement):
                self.case.remote_files[cloud_key] = replacement
                with self.assertRaises(ValueError):
                    self._retry(key)
                self.assertEqual(self.store.load(key), before)

    def test_concurrent_legacy_recovery_runs_once(self) -> None:
        """
        并发恢复在媒体库锁内重读状态，副作用只执行一次
        """
        _, key = self._legacy()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(self._retry, key) for _ in range(2)]
            self.assertEqual(
                [task.result(timeout=10) for task in tasks], ["done", "done"]
            )
        self.case.scrape.assert_called_once()

    def test_http_status_and_retry_validate_keys_and_complete_plan(self) -> None:
        """
        真实路由解析拒绝非法事件键，状态查询与重试使用当前实例数据库
        """
        _, key = self._legacy()
        root = Path(__file__).resolve().parents[1]
        service = SimpleNamespace(
            client=self.case.client,
            mediainfodownloader=self.case.downloader,
            sync_operation=nullcontext,
            webdav_core=None,
        )
        namespace = {
            "servicer": service,
            "TransferStrmHelper": self.case.module.TransferStrmHelper,
            "TransferPostprocessStore": self.case.processor.TransferPostprocessStore,
            "TransferPostprocessRetryPayload": runpy.run_path(
                str(root / "schemas/strm_api.py")
            )["TransferPostprocessRetryPayload"],
            "ApiResponse": runpy.run_path(str(root / "schemas/api.py"))["ApiResponse"],
            "Query": Query,
            "logger": self.case.logger,
        }
        api = MagicMock()
        for name in (
            "transfer_postprocess_list_api",
            "transfer_postprocess_status_api",
            "transfer_postprocess_retry_api",
        ):
            setattr(api, name, _method(root / "api.py", name, namespace))
        routes = _method(root / "__init__.py", "get_api", namespace)(
            MagicMock(api=api, mcp_manager=None)
        )
        app = FastAPI()
        for route in routes:
            if not route["path"].startswith("/transfer_postprocess_"):
                continue
            self.assertEqual(route["auth"], "bear")
            self.assertFalse(route.get("allow_anonymous", False))
            app.add_api_route(
                route["path"], route["endpoint"], methods=route["methods"]
            )
        with TestClient(app) as client:
            list_url = "/transfer_postprocess_list"
            for params in ({"state": "invalid"}, {"page": 0}, {"page_size": 101}):
                self.assertEqual(client.get(list_url, params=params).status_code, 422)
            listing = client.get(list_url).json()["data"]
            self.assertEqual(listing["total"], 1)
            self.assertEqual(listing["items"][0]["key"], key)
            self.assertNotIn("plan", listing["items"][0])
            status_url = "/transfer_postprocess_status"
            retry_url = "/transfer_postprocess_retry"
            self.assertEqual(
                client.get(status_url, params={"key": "invalid"}).status_code, 422
            )
            self.assertEqual(
                client.post(retry_url, json={"key": "invalid"}).status_code, 422
            )
            self.assertEqual(
                client.post(retry_url, json={"key": "0" * 64}).json()["code"], -1
            )
            before = client.get(status_url, params={"key": key}).json()
            self.assertEqual(before["data"]["state"], "superseded")
            self.assertEqual(
                client.post(retry_url, json={"key": key}).json()["data"]["state"],
                "done",
            )
            after = client.get(status_url, params={"key": key}).json()
            self.assertEqual(after["data"]["size"], SIZES[0][1])
            self.assertEqual(client.get(list_url).json()["data"]["total"], 0)
            completed = client.get(list_url, params={"state": "done"}).json()["data"]
            self.assertEqual(completed["items"][0]["key"], key)

    def test_retry_api_runs_recovery_inside_service_lifetime(self) -> None:
        """
        API 实际执行持久计划，校验请求并保留服务关停保护
        """
        _, key = self._legacy()
        service = SimpleNamespace(
            client=self.case.client,
            mediainfodownloader=self.case.downloader,
            sync_operation=MagicMock(side_effect=nullcontext),
        )
        callback = _method(
            Path(__file__).resolve().parents[1] / "api.py",
            "transfer_postprocess_retry_api",
            {
                "servicer": service,
                "TransferStrmHelper": self.case.module.TransferStrmHelper,
                "ApiResponse": lambda **kwargs: SimpleNamespace(**kwargs),
                "logger": self.case.logger,
            },
        )
        response = callback(SimpleNamespace(key=key))
        self.assertEqual(response.code, 0)
        self.assertEqual(response.data["state"], "done")
        service.sync_operation.assert_called_once()
        service.sync_operation.side_effect = RuntimeError("stopped")
        self.assertEqual(callback(SimpleNamespace(key=key)).code, -1)


class TestV3UploadSize(TestCase):
    """
    验证真实秒传分支只返回精确字节数
    """

    def test_instant_upload_prefers_bytes_and_falls_back_to_source(self) -> None:
        """
        接口有精确值时使用该值，缺失时使用上传源大小
        """
        for size_byte in (3199057349, "3199057349", None):
            with self.subTest(size_byte=size_byte):
                helper = MagicMock()
                helper._request_api.side_effect = [
                    {"state": True, "data": {"status": 2, "file_id": "101"}},
                    {
                        "file_id": "101",
                        "file_category": "1",
                        "file_name": "a.mkv",
                        "pick_code": "a" * 17,
                        "utime": 1,
                        "size": "2.98GB",
                        "size_byte": size_byte,
                    },
                ]
                local = MagicMock()
                local.name = "a.mkv"
                local.stat.return_value.st_size = 3199057340
                upload = _method(
                    Path(__file__).resolve().parents[1] / "core/u115_open.py",
                    "upload",
                    {
                        "Path": Path,
                        "datetime": datetime,
                        "timezone": timezone,
                        "perf_counter": lambda: 0,
                        "sleep": MagicMock(),
                        "logger": MagicMock(),
                        "UploadInfo": SimpleNamespace,
                        "upload_notifier": MagicMock(),
                        "configer": SimpleNamespace(notify=False),
                        "schemas": SimpleNamespace(FileItem=SimpleNamespace),
                    },
                )
                result = upload(
                    helper, SimpleNamespace(path="/cloud", fileid="1"), local
                )
                self.assertEqual(
                    result.size, 3199057349 if size_byte is not None else 3199057340
                )
