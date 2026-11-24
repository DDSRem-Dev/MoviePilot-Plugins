import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock


def _compile_class(path: Path, namespace: Dict[str, Any], class_name: str) -> Any:
    """
    从源文件中编译指定类，隔离 MoviePilot 宿主依赖

    :param path (Path): 源文件路径
    :param namespace (dict): 编译命名空间
    :param class_name (str): 类名

    :return type: 编译后的类
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    class_node.decorator_list = []
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            class_node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[class_name]


class TestSecuploadRecheck(TestCase):
    """
    验证 V2 分片上传期间复判秒传的间隔和响应判定
    """

    def setUp(self) -> None:
        """
        编译上传器并注入最小依赖，避免网络与真实 MoviePilot 宿主
        """
        root = Path(__file__).resolve().parents[1]
        values = {}
        self.config = SimpleNamespace(get_config=values.get)
        self.core_class = _compile_class(
            root / "core/p115disk.py",
            {"configer": self.config, "logger": MagicMock()},
            "P115DiskCore",
        )
        self.open_class = _compile_class(
            root / "core/u115_open.py",
            {
                "configer": self.config,
                "logger": MagicMock(),
                "RateLimiter": MagicMock(return_value=MagicMock()),
            },
            "U115OpenHelper",
        )
        self.core = self.core_class.__new__(self.core_class)
        self.client = MagicMock()
        self.core._p115_api = SimpleNamespace(client=self.client)
        self.open_helper = self.open_class.__new__(self.open_class)
        self.open_helper._request_api = MagicMock()

    def test_interval_defaults_and_clamps(self) -> None:
        """
        复判关闭时返回零，开启后使用默认值并限制最小间隔
        """
        self.assertEqual(self.core_class._secupload_recheck_interval(), 0)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 0)

        self.config.get_config = lambda key: {
            "upload_module_recheck_secupload": True,
        }.get(key)
        self.assertEqual(self.core_class._secupload_recheck_interval(), 300)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 300)

        self.config.get_config = lambda key: {
            "upload_module_recheck_secupload": True,
            "upload_module_recheck_secupload_interval": 30,
        }.get(key)
        self.assertEqual(self.core_class._secupload_recheck_interval(), 60)
        self.assertEqual(self.open_class._secupload_recheck_interval(), 60)

    def test_cookie_recheck_requires_reuse(self) -> None:
        """
        Cookie 通道只在初始化响应明确命中秒传时返回真
        """
        self.client.upload_file_init.return_value = {"state": True, "reuse": True}
        self.assertTrue(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )

        self.client.upload_file_init.return_value = "error text"
        self.assertFalse(
            self.core._recheck_secupload("video.mkv", 10, "sha1", 123, lambda _: "")
        )

    def test_open_recheck_requires_status_two_dict(self) -> None:
        """
        OpenAPI 通道只在结构完整且 status 为 2 时返回真
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

        for payload in (
            "error text",
            ["state"],
            {"state": True, "data": "invalid"},
            {"state": True, "data": [{"status": 2}]},
        ):
            with self.subTest(payload=payload):
                self.open_helper._request_api.return_value = payload
                self.assertFalse(
                    self.open_helper._recheck_secupload(
                        "video.mkv", 10, "U_1_123", "sha1", "preid"
                    )
                )
