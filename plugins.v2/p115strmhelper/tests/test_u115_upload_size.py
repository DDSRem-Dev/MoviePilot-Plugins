"""
验证 V2 秒传返回精确大小，不依赖 V3 宿主或插件实现
"""

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import TestCase
from unittest.mock import MagicMock


class TestU115UploadSize(TestCase):
    """
    执行 V2 真实上传方法，隔离云端请求、源文件读取和通知
    """

    def setUp(self) -> None:
        """
        从 V2 源码加载上传方法并提供宿主边界替身
        """
        source = Path(__file__).resolve().parents[1] / "core/u115_open.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "U115OpenHelper"
        )
        upload = next(
            node
            for node in helper.body
            if isinstance(node, ast.FunctionDef) and node.name == "upload"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__", names=[ast.alias(name="annotations")], level=0
                ),
                upload,
            ],
            type_ignores=[],
        )
        self.string_utils = MagicMock()
        self.string_utils.num_filesize.return_value = 3199750636
        self.delayed_lookup = MagicMock()
        namespace = {
            "Path": Path,
            "datetime": datetime,
            "timezone": timezone,
            "perf_counter": lambda: 0,
            "sleep": MagicMock(),
            "logger": MagicMock(),
            "UploadInfo": SimpleNamespace,
            "configer": SimpleNamespace(notify=False),
            "schemas": SimpleNamespace(FileItem=SimpleNamespace),
            "StringUtils": self.string_utils,
            "U115OpenHelper": SimpleNamespace(_delay_get_item=self.delayed_lookup),
        }
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        self.upload = namespace["upload"]

    def _upload(
        self, info: Dict[str, Any], source_size: int, file_id: Optional[str] = "101"
    ) -> Any:
        helper = MagicMock()
        helper._request_api.side_effect = [
            {"state": True, "data": {"status": 2, "file_id": file_id}},
            info,
        ]
        local = MagicMock(spec=Path)
        local.name = "source.mkv"
        local.stat.return_value.st_size = source_size
        return self.upload(
            helper, SimpleNamespace(path="/cloud", fileid="1"), local, "target.mkv"
        )

    def _info(self, **overrides: Any) -> Dict[str, Any]:
        return {
            "file_id": "101",
            "file_category": "1",
            "file_name": "target.mkv",
            "pick_code": "a" * 17,
            "utime": 1,
            "size": "2.98GB",
            **overrides,
        }

    def test_display_sizes_do_not_replace_exact_bytes(self) -> None:
        """
        四组已知显示误差均返回云端精确大小并保留目标文件信息
        """
        for display, actual in (
            ("2.98GB", 3199057349),
            ("1.02GB", 1099528789),
            ("1.75GB", 1873923911),
            ("907.85MB", 951951920),
        ):
            for size_byte in (actual, str(actual)):
                with self.subTest(display=display, size_byte=size_byte):
                    result = self._upload(
                        self._info(size=display, size_byte=size_byte), actual + 1
                    )
                    self.assertEqual(result.size, actual)
                    self.assertIsInstance(result.size, int)
                    self.assertEqual(result.fileid, "101")
                    self.assertEqual(result.pickcode, "a" * 17)
                    self.assertEqual(result.path, str(Path("/cloud") / "target.mkv"))
                    self.assertEqual(result.name, "target.mkv")
        self.string_utils.num_filesize.assert_not_called()

    def test_missing_or_null_size_byte_uses_source_bytes(self) -> None:
        """
        接口没有精确大小时回退到上传前读取的源文件字节数
        """
        for fields in ({}, {"size_byte": None}):
            with self.subTest(fields=fields):
                result = self._upload(self._info(**fields), 3199057349)
                self.assertEqual(result.size, 3199057349)
        self.string_utils.num_filesize.assert_not_called()

    def test_zero_size_byte_is_not_treated_as_missing(self) -> None:
        """
        精确大小为零时不回退到源文件大小
        """
        result = self._upload(self._info(size_byte=0), 123)
        self.assertEqual(result.size, 0)

    def test_display_field_is_not_required(self) -> None:
        """
        接口省略显示大小仍能返回有效文件信息
        """
        for fields in ({"size_byte": 123}, {}):
            with self.subTest(fields=fields):
                info = self._info(**fields)
                info.pop("size")
                self.assertEqual(self._upload(info, 123).size, 123)

    def test_directory_does_not_receive_file_size(self) -> None:
        """
        目录响应继续保留空大小与目录类型
        """
        result = self._upload(self._info(file_category="0", size_byte=123), 456)
        self.assertIsNone(result.size)
        self.assertEqual(result.type, "dir")

    def test_missing_upload_id_preserves_delayed_lookup(self) -> None:
        """
        秒传未返回文件 ID 时继续使用已有的延迟查询流程
        """
        expected = SimpleNamespace(size=3199057349)
        self.delayed_lookup.return_value = expected
        self.assertIs(self._upload({}, 3199057349, file_id=None), expected)
        self.delayed_lookup.assert_called_once_with(Path("/cloud") / "target.mkv")
