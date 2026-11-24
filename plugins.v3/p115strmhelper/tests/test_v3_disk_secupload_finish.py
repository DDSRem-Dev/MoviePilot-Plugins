from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import hashes

from test_v3_worker_queue import _compile


class TestV3DiskSecuploadFinish(TestCase):
    """
    验证 Cookie 通道在分片途中命中秒传后的收尾行为
    """

    def setUp(self) -> None:
        """
        用可推进的时钟与最小假件替换 OSS 交互，保留真实 upload 流程
        """
        root = Path(__file__).resolve().parents[1]
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "video.mkv"
        self.path.write_bytes(b"0123456789" * 3)
        self.ticks = 0

        def perf_counter() -> int:
            self.ticks += 100
            return self.ticks

        values = {
            "upload_module_skip_upload_wait_size": 0,
            "upload_module_wait_timeout": 0,
            "upload_module_recheck_secupload": True,
            "upload_module_recheck_secupload_interval": 60,
        }
        self.config = SimpleNamespace(
            notify=False,
            upload_module_notify=False,
            upload_module_skip_slow_upload=False,
            get_config=lambda key: values.get(key),
        )

        self.progress = []
        self.logger = MagicMock()
        self.bucket = MagicMock()
        self.bucket.init_multipart_upload.return_value = SimpleNamespace(
            upload_id="upload-1"
        )
        self.bucket.upload_part.return_value = SimpleNamespace(etag="etag-1")

        self.client = MagicMock()
        self.client.upload_file_init.side_effect = [
            {
                "state": True,
                "reuse": False,
                "bucket": "bucket-1",
                "object": "object-1",
                "callback": {"callback": "cb", "callback_var": "cv"},
            },
            {"state": True, "reuse": True},
        ]
        self.uploaded = SimpleNamespace(path="/movies/video.mkv")
        self.api = SimpleNamespace(
            client=self.client,
            _calc_sha1=lambda path: "sha1",
            _id_cache=SimpleNamespace(get_id_by_dir=lambda path: None),
            _id_item_cache=SimpleNamespace(remove=MagicMock(), get_item=MagicMock()),
            get_folder=MagicMock(return_value=SimpleNamespace(fileid="123")),
            get_item=MagicMock(return_value=self.uploaded),
            _get_oss_token=MagicMock(
                return_value=(
                    "oss.example",
                    "ak",
                    "sk",
                    "token",
                    datetime.now(timezone.utc),
                )
            ),
            _is_token_expiring=MagicMock(return_value=False),
        )

        case = self

        class FakeBucket:
            def __init__(self, *args, **kwargs) -> None:
                self.calls = []

            def init_multipart_upload(self, object_name, params=None):
                return case.bucket.init_multipart_upload(object_name, params=params)

            def upload_part(self, object_name, upload_id, part_number, data=None):
                return case.bucket.upload_part(
                    object_name, upload_id, part_number, data=data
                )

            def abort_multipart_upload(self, object_name, upload_id):
                case.bucket.abort_multipart_upload(object_name, upload_id)

            def complete_multipart_upload(
                self, object_name, upload_id, parts, headers=None
            ):
                raise AssertionError("命中秒传后不应完成分片上传")

        namespace = {
            "Path": Path,
            "perf_counter": perf_counter,
            "sleep": MagicMock(),
            "datetime": datetime,
            "timezone": timezone,
            "hashes": hashes,
            "logger": self.logger,
            "configer": self.config,
            "UploadInfo": SimpleNamespace,
            "P115Center": MagicMock(),
            "upload_notifier": SimpleNamespace(capture=MagicMock()),
            "post_message": MagicMock(),
            "i18n": MagicMock(),
            "MessageType": SimpleNamespace(Plugin="Plugin"),
            "b64encode_as_string": lambda value: value,
            "Bucket": FakeBucket,
            "StsAuth": MagicMock(),
            "SizedFileAdapter": lambda fileobj, size: fileobj.read(size),
            "PartInfo": lambda part_number, etag: (part_number, etag),
            "ServerError": RuntimeError,
            "determine_part_size": lambda size, preferred_size: 10,
            "check_response": lambda response: response,
            "global_vars": SimpleNamespace(is_transfer_stopped=lambda path: False),
            "_CACHE_DIR": Path(temporary.name),
            "transfer_process": MagicMock(
                return_value=lambda value: self.progress.append(value)
            ),
        }
        self.core_class = _compile(root / "core/p115disk.py", namespace, "P115DiskCore")
        self.core = self.core_class(p115_api=self.api)

    def test_recheck_hit_sets_progress_complete(self) -> None:
        """
        分片途中命中秒传时进度置 100、中止分片并返回文件项
        """
        result = self.core.upload(
            target_dir=SimpleNamespace(path="/movies"), local_path=self.path
        )

        self.assertIs(result, self.uploaded)
        self.assertEqual(self.progress[-1], 100)
        self.bucket.abort_multipart_upload.assert_called_once()
        self.bucket.upload_part.assert_called_once()
        self.bucket.complete_multipart_upload.assert_not_called()

    def test_abort_failure_still_finishes_as_secupload(self) -> None:
        """
        中止分片失败时仅记录清理告警，仍按秒传成功收尾
        """
        self.bucket.abort_multipart_upload.side_effect = RuntimeError("abort failed")

        result = self.core.upload(
            target_dir=SimpleNamespace(path="/movies"), local_path=self.path
        )

        self.assertIs(result, self.uploaded)
        self.assertEqual(self.progress[-1], 100)
        self.bucket.abort_multipart_upload.assert_called_once()
        self.bucket.upload_part.assert_called_once()
        self.bucket.complete_multipart_upload.assert_not_called()
