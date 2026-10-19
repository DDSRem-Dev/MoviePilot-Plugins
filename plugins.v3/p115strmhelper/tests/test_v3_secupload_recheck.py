from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from test_v3_worker_queue import _compile


def _config(**values):
    """
    构造可按字段返回配置值的配置对象

    :param values: 需要覆盖的配置项

    :return SimpleNamespace: 配置对象
    """

    def get_config(key):
        return values.get(key)

    return SimpleNamespace(get_config=get_config)


class TestV3SecuploadRecheck(TestCase):
    """
    验证分片上传期间复判秒传的间隔与命中判定
    """

    def setUp(self) -> None:
        """
        编译上传器并注入最小依赖，避免网络与真实 115 客户端
        """
        root = Path(__file__).resolve().parents[1]
        self.config = _config()
        namespace = {
            "configer": self.config,
            "logger": MagicMock(),
            "P115Center": MagicMock(),
            "upload_notifier": SimpleNamespace(capture=MagicMock()),
            "perf_counter": lambda: 0,
            "transfer_process": MagicMock(),
            "check_response": lambda response: response,
            "UploadInfo": SimpleNamespace,
        }
        self.core_class = _compile(
            root / "core/p115disk.py", namespace, "P115DiskCore"
        )
        self.open_class = _compile(
            root / "core/u115_open.py",
            {"configer": self.config, "logger": MagicMock()},
            "U115OpenHelper",
        )
        self.core = self.core_class.__new__(self.core_class)
        self.client = MagicMock()
        self.core._p115_api = SimpleNamespace(client=self.client)
        self.open_helper = self.open_class.__new__(self.open_class)
        self.open_helper._request_api = MagicMock()

    def test_interval_disabled_when_switch_off(self) -> None:
        """
        未开启复判开关时返回 0
        """
        self.assertEqual(self.core_class._secupload_recheck_interval(), 0)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 0)

    def test_interval_defaults_and_clamps(self) -> None:
        """
        开启后使用默认 300 秒，小于 60 秒按 60 秒处理
        """
        self.config.get_config = _config(
            upload_module_recheck_secupload=True
        ).get_config
        self.assertEqual(self.core_class._secupload_recheck_interval(), 300)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 300)

        self.config.get_config = _config(
            upload_module_recheck_secupload=True,
            upload_module_recheck_secupload_interval=30,
        ).get_config
        self.assertEqual(self.core_class._secupload_recheck_interval(), 60)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 60)

    def test_p115disk_recheck_hits_reuse(self) -> None:
        """
        Cookie 通道只在初始化返回 reuse 时判定命中
        """
        self.client.upload_file_init.return_value = {"state": True, "reuse": True}
        self.assertTrue(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )
        self.assertEqual(
            self.client.upload_file_init.call_args.kwargs["filename"], "video.mkv"
        )

        self.client.upload_file_init.return_value = {"state": True, "reuse": False}
        self.assertFalse(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )

    def test_p115disk_recheck_ignores_failure(self) -> None:
        """
        复判请求异常或状态异常时不阻断分片上传
        """
        self.client.upload_file_init.side_effect = RuntimeError("network")
        self.assertFalse(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )

        self.client.upload_file_init.side_effect = None
        self.client.upload_file_init.return_value = {"state": False}
        self.assertFalse(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )

    def test_p115open_recheck_hits_status_two(self) -> None:
        """
        OpenAPI 通道只在初始化返回 status 2 时判定命中
        """
        self.open_helper._request_api.return_value = {
            "state": True,
            "data": {"status": 2},
        }
        self.assertTrue(
            self.open_helper._recheck_secupload(
                "video.mkv", 10, "U_1_123", "sha1", "preid"
            )
        )
        self.assertEqual(
            self.open_helper._request_api.call_args.kwargs["data"],
            {
                "file_name": "video.mkv",
                "file_size": 10,
                "target": "U_1_123",
                "fileid": "sha1",
                "preid": "preid",
            },
        )

        self.open_helper._request_api.return_value = {
            "state": True,
            "data": {"status": 1},
        }
        self.assertFalse(
            self.open_helper._recheck_secupload(
                "video.mkv", 10, "U_1_123", "sha1", "preid"
            )
        )

    def test_p115open_recheck_ignores_failure(self) -> None:
        """
        OpenAPI 复判请求异常或状态异常时返回未命中
        """
        self.open_helper._request_api.side_effect = RuntimeError("network")
        self.assertFalse(
            self.open_helper._recheck_secupload("a", 1, "U_1_1", "s", "p")
        )

        self.open_helper._request_api.side_effect = None
        self.open_helper._request_api.return_value = {"state": False}
        self.assertFalse(
            self.open_helper._recheck_secupload("a", 1, "U_1_1", "s", "p")
        )
