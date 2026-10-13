"""
旧关联持久任务的字幕事件分类回归测试
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


class TestExtNormalization(TestCase):
    """
    验证旧任务结算仍能准确区分字幕和音轨事件
    """

    def setUp(self) -> None:
        """
        仅隔离字幕分类依赖，测试结束后恢复模块表
        """
        config = ModuleType("app.sdk.config")
        config.settings = FakeSettings()
        schemas = ModuleType("app.schemas")
        schemas.FileItem = FakeFileItem
        modules = patch.dict(
            sys.modules,
            {
                "app.sdk.config": config,
                "app.schemas": schemas,
            },
        )
        modules.start()
        self.addCleanup(modules.stop)
        path = Path(__file__).resolve().parents[1] / "helper/transfer/file_types.py"
        spec = importlib.util.spec_from_file_location("transfer_file_types", path)
        self.handler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.handler)

    def test_normalize_ext(self) -> None:
        """
        归一化兼容带点/不带点/大小写/空格
        """
        normalize = self.handler.TransferFileTypes._normalize_ext
        self.assertEqual(normalize("ass"), ".ass")
        self.assertEqual(normalize(".ass"), ".ass")
        self.assertEqual(normalize("ASS"), ".ass")
        self.assertEqual(normalize(" .Mkv "), ".mkv")
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(""))

    def test_is_subtitle_file(self) -> None:
        """
        默认配置下字幕判定
        """
        is_sub = self.handler.TransferFileTypes._is_subtitle_file
        self.assertTrue(is_sub(FakeFileItem(extension="ass")))
        self.assertTrue(is_sub(FakeFileItem(extension="srt")))
        self.assertFalse(is_sub(FakeFileItem(extension="mkv")))
        self.assertFalse(is_sub(FakeFileItem(extension=None, path="/x/noext")))

    def test_is_subtitle_file_fallback_path(self) -> None:
        """
        extension 缺失时回退路径后缀（u115 存储 ico 缺失场景）
        """
        is_sub = self.handler.TransferFileTypes._is_subtitle_file
        self.assertTrue(
            is_sub(FakeFileItem(extension=None, path="/115/媒体库/x/xx.ass"))
        )
        self.assertFalse(
            is_sub(FakeFileItem(extension=None, path="/115/媒体库/x/xx.mkv"))
        )

    def test_is_subtitle_file_config_without_dot(self) -> None:
        """
        配置不带点时仍能判定（用户配置 srt,ass）
        """
        is_sub = self.handler.TransferFileTypes._is_subtitle_file
        with patch.object(FakeSettings, "RMT_SUBEXT", ["srt", "ass"]):
            self.assertTrue(is_sub(FakeFileItem(extension="ass")))
            self.assertFalse(is_sub(FakeFileItem(extension="ssa")))


class FakeSettings:
    """
    字幕配置替身
    """

    RMT_SUBEXT = [".srt", ".ass", ".ssa", ".sup"]


class FakeFileItem(SimpleNamespace):
    """
    字幕分类所需的文件项替身
    """

    path = None
    extension = None
