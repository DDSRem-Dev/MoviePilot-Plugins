from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from cryptography.hazmat.primitives import hashes

from test_v3_worker_queue import _compile


class TestV3OpenSecuploadFinish(TestCase):
    """
    验证 OpenAPI 通道在分片途中命中秒传后的收尾行为
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
            upload_open_result_notify=False,
            get_config=lambda key: values.get(key),
        )

        self.progress = []
        self.logger = MagicMock()
        self.bucket = MagicMock()
        self.bucket.init_multipart_upload.return_value = SimpleNamespace(
            upload_id="upload-1"
        )
        self.bucket.upload_part.return_value = SimpleNamespace(etag="etag-1")
        self.requests = []
        self.open_helper = None

        def request_api(method, endpoint, result_key=None, **kwargs):
            self.requests.append((method, endpoint))
            if endpoint == "/open/upload/init":
                if len(self.requests) == 1:
                    return {
                        "state": True,
                        "data": {
                            "status": 1,
                            "bucket": "bucket-1",
                            "object": "object-1",
                            "callback": {},
                        },
                    }
                return {"state": True, "data": {"status": 2}}
            if endpoint == "/open/upload/get_token":
                return {
                    "endpoint": "oss.example",
                    "AccessKeyId": "ak",
                    "AccessKeySecret": "sk",
                    "SecurityToken": "token",
                }
            return {}

        case = self

        class FakeBucket:
            def __init__(self, auth, endpoint, bucket_name, **kwargs):
                self.calls = []

            def init_multipart_upload(self, object_name, params=None):
                return case.bucket.init_multipart_upload(object_name, params=params)

            def upload_part(self, object_name, upload_id, part_number, data=None):
                return case.bucket.upload_part(
                    object_name, upload_id, part_number, data=data
                )

            def abort_multipart_upload(self, object_name, upload_id):
                case.bucket.abort_multipart_upload(object_name, upload_id)

            def complete_multipart_upload(self, object_name, upload_id, parts, headers=None):
                raise AssertionError("命中秒传后不应完成分片上传")

        self.uploaded = SimpleNamespace(path="/movies/video.mkv")
        namespace = {
            "Path": Path,
            "perf_counter": perf_counter,
            "sleep": MagicMock(),
            "datetime": MagicMock(),
            "timezone": MagicMock(),
            "hashes": hashes,
            "logger": self.logger,
            "configer": self.config,
            "UploadInfo": SimpleNamespace,
            "upload_notifier": SimpleNamespace(capture=MagicMock()),
            "post_message": MagicMock(),
            "i18n": MagicMock(),
            "MessageType": SimpleNamespace(Plugin="Plugin"),
            "b64encode_as_string": lambda value: value,
            "Bucket": FakeBucket,
            "StsAuth": MagicMock(),
            "SizedFileAdapter": lambda fileobj, size: fileobj.read(size),
            "PartInfo": lambda part_number, etag: (part_number, etag),
            "OssError": RuntimeError,
            "determine_part_size": lambda size, preferred_size: 10,
            "global_vars": SimpleNamespace(is_transfer_stopped=lambda path: False),
            "transfer_process": MagicMock(
                return_value=lambda value: self.progress.append(value)
            ),
            "StorageChain": MagicMock(
                return_value=SimpleNamespace(
                    get_file_item=MagicMock(return_value=self.uploaded)
                )
            ),
            "StringUtils": SimpleNamespace(str_filesize=lambda value: str(value)),
        }
        helper_class = _compile(root / "core/u115_open.py", namespace, "U115OpenHelper")
        self.helper = helper_class.__new__(helper_class)
        self.helper.chunk_size = 10
        self.helper.p115_center = MagicMock()
        self.helper._request_api = request_api
        self.helper._calc_sha1 = lambda path, size=0: "sha1"

    def test_recheck_hit_sets_progress_complete(self) -> None:
        """
        分片途中命中秒传时进度置 100、中止分片并返回文件项
        """
        target = SimpleNamespace(path="/movies", fileid="123")
        result = self.helper.upload(target_dir=target, local_path=self.path)

        self.assertEqual(result, self.uploaded)
        self.assertIn(100, self.progress)
        self.assertEqual(self.progress[-1], 100)
        self.bucket.abort_multipart_upload.assert_called_once()
        self.assertEqual(
            [endpoint for _, endpoint in self.requests].count("/open/upload/init"), 2
        )
