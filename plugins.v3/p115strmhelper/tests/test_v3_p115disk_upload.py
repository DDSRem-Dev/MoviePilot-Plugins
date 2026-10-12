from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, RLock
from types import SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock
from uuid import uuid4

from cryptography.hazmat.primitives import hashes

from test_v3_worker_queue import _compile


def _memory_cache(**kwargs: Any) -> Any:
    values = {}
    return SimpleNamespace(
        get=values.get,
        set=lambda key, value: values.__setitem__(key, value),
        delete=lambda key: values.pop(key, None),
        clear=values.clear,
    )


class TestV3P115DiskUpload(TestCase):
    """
    使用 V3 P115Api 的实际构造和缓存验证增强上传的实例归属
    """

    def setUp(self) -> None:
        """
        保留实际 API、缓存与限流器，隔离网络、通知和临时文件
        """
        root = Path(__file__).resolve().parents[1]
        disk_root = root.parent / "p115disk"
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "video.mkv"
        self.path.write_bytes(b"abcdefghij")
        self.config = SimpleNamespace(
            notify=True,
            upload_open_result_notify=True,
            get_config=lambda key: "test-machine" if key == "machine_id" else 0,
        )
        self.stop = SimpleNamespace(is_transfer_stopped=MagicMock(return_value=False))
        self.logger = MagicMock()
        namespace = {"TTLCache": _memory_cache, "uuid4": uuid4}
        id_cache = _compile(disk_root / "cache.py", namespace, "IdPathCache")
        item_cache = _compile(disk_root / "cache.py", namespace, "ItemIdCache")
        limiter = _compile(
            disk_root / "tools.py",
            {"Lock": Lock, "monotonic": lambda: 0, "sleep": MagicMock()},
            "RateLimiter",
        )
        self.api_class = _compile(
            disk_root / "p115_api.py",
            {
                "IdPathCache": id_cache,
                "ItemIdCache": item_cache,
                "RLock": RLock,
                "RateLimiter": limiter,
                "hashes": hashes,
                "global_vars": self.stop,
            },
            "P115Api",
        )
        self.notifier = MagicMock()
        self.namespace = {
            "configer": self.config,
            "P115Center": MagicMock(),
            "upload_notifier": SimpleNamespace(capture=lambda: self.notifier),
            "logger": self.logger,
            "Path": Path,
            "perf_counter": lambda: 0,
            "transfer_process": MagicMock(return_value=MagicMock()),
            "check_response": lambda response: response,
            "datetime": datetime,
            "timezone": timezone,
            "UploadInfo": SimpleNamespace,
        }
        self.core_class = _compile(
            root / "core/p115disk.py", self.namespace, "P115DiskCore"
        )
        self.patcher = _compile(
            root / "patch/p115disk_upload.py",
            {"P115DiskCore": self.core_class, "logger": self.logger},
            "P115DiskPatcher",
        )
        self.client = MagicMock()
        self.client.upload_file_init.return_value = {"state": True, "reuse": True}
        self.api = self.api_class(client=self.client, disk_name="instance-storage")
        self.target = SimpleNamespace(path="/movies", fileid="123")
        self.uploaded = SimpleNamespace(
            storage=self.api._disk_name,
            type="file",
            path="/movies/video.mkv",
            name="video.mkv",
            fileid="456",
            size=10,
        )
        self.api.get_folder = MagicMock(return_value=self.target)
        self.api.get_item = MagicMock(return_value=self.uploaded)
        self.core = self.core_class(p115_api=self.api)

    def test_core_keeps_actual_api_locks_caches_and_limiters(self) -> None:
        """
        增强上传持有原 API，不重新构造缓存、目录锁或限流器
        """
        self.assertIs(self.core._p115_api, self.api)
        for name in (
            "_id_cache",
            "_id_item_cache",
            "_folder_lock",
            "_list_rate_limiter",
        ):
            self.assertIs(getattr(self.core._p115_api, name), getattr(self.api, name))

    def test_instant_upload_invalidates_original_instance_cache(self) -> None:
        """
        秒传清理的是存储实例原有缓存，不是新建空缓存
        """
        self.api._id_cache.add_cache(id=456, directory=self.uploaded.path)
        self.api._id_item_cache.add_cache(id=456, item={"old": True})
        self.assertIs(self.core.upload(self.target, self.path), self.uploaded)
        self.assertIsNone(self.api._id_cache.get_id_by_dir(self.uploaded.path))
        self.assertIsNone(self.api._id_item_cache.get_item(456))
        self.api.get_folder.assert_called_once_with(path=Path("/movies"))
        self.api.get_item.assert_called_once_with(Path(self.uploaded.path))

    def test_two_instances_keep_separate_clients_and_cache_invalidation(self) -> None:
        """
        一个存储实例上传不清理另一个实例的同路径缓存
        """
        other_client = MagicMock()
        other = self.api_class(client=other_client, disk_name="other-storage")
        other._id_cache.add_cache(id=456, directory=self.uploaded.path)
        other._id_item_cache.add_cache(id=456, item={"other": True})
        other_core = self.core_class(p115_api=other)
        self.assertIs(self.core.upload(self.target, self.path), self.uploaded)
        self.assertIs(other_core._p115_api.client, other_client)
        other_client.upload_file_init.assert_not_called()
        self.assertEqual(other._id_cache.get_id_by_dir(self.uploaded.path), 456)
        self.assertEqual(other._id_item_cache.get_item(456), {"other": True})

    def test_patch_returns_original_storage_identity(self) -> None:
        """
        补丁执行完整秒传流程并保留实际 API 的存储名称
        """
        result = self.patcher._patch_upload(self.api, self.target, self.path)
        self.assertIs(result, self.uploaded)
        self.assertEqual(result.storage, "instance-storage")
        self.client.upload_file_init.assert_called_once()
        self.api.get_item.assert_called_once_with(Path(self.uploaded.path))

    def test_patch_preserves_renamed_destination(self) -> None:
        """
        上传改名参数继续由同一 API 接收
        """
        result = self.patcher._patch_upload(
            self.api, self.target, self.path, new_name="renamed.mkv"
        )
        self.assertIs(result, self.uploaded)
        self.assertEqual(
            self.client.upload_file_init.call_args.kwargs["filename"], "renamed.mkv"
        )
        self.api.get_item.assert_called_once_with(Path("/movies/renamed.mkv"))

    def test_patch_without_client_does_not_initialize_upload(self) -> None:
        """
        已释放客户端的 API 不启动增强上传
        """
        self.api.client = None
        self.assertIsNone(self.patcher._patch_upload(self.api, self.target, self.path))
        self.client.upload_file_init.assert_not_called()
        self.api.get_folder.assert_not_called()

    def test_v3_hash_cancellation_returns_without_upload(self) -> None:
        """
        实际 V3 散列方法抛出取消异常时，增强上传按存储合同返回 None
        """
        self.stop.is_transfer_stopped.return_value = True
        self.assertIsNone(self.patcher._patch_upload(self.api, self.target, self.path))
        self.stop.is_transfer_stopped.assert_called_once_with(self.path.as_posix())
        self.client.upload_file_init.assert_not_called()
        self.api.get_item.assert_not_called()
        self.namespace["transfer_process"].assert_not_called()
        self.notifier.add.assert_not_called()
