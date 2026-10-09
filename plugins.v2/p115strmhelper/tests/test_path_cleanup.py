"""
重新整理后关联刮削文件清理回归测试
"""

from __future__ import annotations

import ast
from os import name as os_name
from pathlib import Path, PurePosixPath
from shutil import rmtree
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import TestCase
from unittest.mock import Mock


def _load_cleanup() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    namespace = {
        "Path": Path,
        "PurePosixPath": PurePosixPath,
        "os_name": os_name,
        "rmtree": rmtree,
        "logger": Mock(),
        "SystemUtils": Mock(),
        "configer": SimpleNamespace(
            transfer_monitor_remove_stale_strm=True,
            transfer_monitor_remove_stale_strm_file=True,
            transfer_monitor_remove_stale_strm_dir=True,
        ),
        "StrmGenerater": Mock(),
    }
    namespace["SystemUtils"].exits_files.side_effect = lambda directory, extensions: (
        any(
            path.is_file() and path.suffix.lower().lstrip(".") in extensions
            for path in directory.rglob("*")
        )
    )
    namespace["StrmGenerater"].get_strm_filename.side_effect = lambda path: (
        path.with_suffix(".strm").name
    )
    source = root / "utils/path.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    exec(
        compile(ast.Module(body=classes, type_ignores=[]), str(source), "exec"),
        namespace,
    )
    source = root / "helper/strm/transfer.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    helper = next(node for node in module.body if isinstance(node, ast.ClassDef))
    cleanup = next(
        node
        for node in helper.body
        if isinstance(node, ast.FunctionDef) and node.name == "_cleanup_stale_strm"
    )
    exec(
        compile(ast.Module(body=[cleanup], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace


class TestPathCleanup(TestCase):
    """
    验证通用图片清理条件及重新整理开关
    """

    def setUp(self) -> None:
        """
        创建临时媒体库和旧影片的刮削文件
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old_dir = self.root / "library" / "Spiral (2021)"
        self.old_dir.mkdir(parents=True)
        self.old_strm = self.old_dir / "Spiral (2021).strm"
        self.old_strm.write_text("old-url", encoding="utf-8")
        self.scrap_names = (
            "Spiral (2021).nfo",
            "Spiral (2021).zh.srt",
            "backdrop.jpg",
            "fanart.jpg",
            "poster.jpg",
            "landscape.PNG",
            "logo.webp",
            "movie.nfo",
        )
        for name in self.scrap_names:
            (self.old_dir / name).write_text("scraped", encoding="utf-8")
        self.new_strm = self.root / "library" / "new.strm"
        self.new_strm.write_text("new-url", encoding="utf-8")
        self.namespace = _load_cleanup()
        self.paths = self.namespace["PathRemoveUtils"]
        self.config = self.namespace["configer"]
        self.config.transfer_monitor_paths = f"{self.root / 'library'}#/remote"
        self.transfer = SimpleNamespace(
            fileitem=SimpleNamespace(path="/remote/Spiral (2021)/Spiral (2021).mkv")
        )

    def _transfer_cleanup(self, target: Optional[Path] = None) -> None:
        self.namespace["_cleanup_stale_strm"](
            None, self.transfer, str(target or self.new_strm)
        )

    def test_retransfer_removes_scraped_files_and_empty_directory(self) -> None:
        """
        重新整理清理通用图片及 NFO 后，旧目录可正常删除
        """
        self._transfer_cleanup()
        self.assertFalse(self.old_dir.exists())
        self.assertEqual(self.new_strm.read_text(encoding="utf-8"), "new-url")

    def test_other_content_preserves_shared_artwork(self) -> None:
        """
        同目录仍有媒体、未知文件、子目录或链接时保留通用刮削文件
        """
        for remaining in (
            "other.strm",
            "other.MKV",
            "other.flac",
            "notes.txt",
            "Season 02",
            "linked.jpg",
        ):
            with self.subTest(remaining=remaining):
                keep = self.old_dir / remaining
                if remaining == "Season 02":
                    keep.mkdir()
                    (keep / "E01.strm").touch()
                elif remaining == "linked.jpg":
                    keep.symlink_to(self.new_strm)
                else:
                    keep.touch()
                self.old_strm.unlink(missing_ok=True)
                self.paths.clean_related_files(self.old_strm)
                self.assertTrue((self.old_dir / "poster.jpg").exists())
                self.assertTrue((self.old_dir / "movie.nfo").exists())
                self.assertTrue(keep.exists())
                self.assertFalse((self.old_dir / "Spiral (2021).nfo").exists())
                if keep.is_dir():
                    rmtree(keep)
                else:
                    keep.unlink()
        self.paths.clean_related_files(self.old_strm)
        self.assertEqual(list(self.old_dir.iterdir()), [])

    def test_same_directory_new_strm_keeps_shared_artwork(self) -> None:
        """
        原目录内改名时新 STRM 与共享图片不受影响
        """
        target = self.old_dir / "renamed.strm"
        target.write_text("new-url", encoding="utf-8")
        self._transfer_cleanup(target)
        self.assertFalse(self.old_strm.exists())
        self.assertTrue((self.old_dir / "poster.jpg").exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "new-url")

    def test_identical_target_is_untouched(self) -> None:
        """
        源目标相同的原地整理不触发文件清理
        """
        self._transfer_cleanup(self.old_strm)
        self.assertTrue(self.old_strm.exists())
        for name in self.scrap_names:
            self.assertTrue((self.old_dir / name).exists())

    def test_disabled_related_cleanup_preserves_artwork(self) -> None:
        """
        关闭关联文件清理时只删除旧 STRM，保留刮削文件和目录
        """
        self.config.transfer_monitor_remove_stale_strm_file = False
        self._transfer_cleanup()
        self.assertFalse(self.old_strm.exists())
        for name in self.scrap_names:
            self.assertTrue((self.old_dir / name).exists())

    def test_disabled_directory_cleanup_preserves_empty_directory(self) -> None:
        """
        关闭目录清理时清空刮削文件但保留空目录
        """
        self.config.transfer_monitor_remove_stale_strm_dir = False
        self._transfer_cleanup()
        self.assertTrue(self.old_dir.is_dir())
        self.assertEqual(list(self.old_dir.iterdir()), [])

    def test_disabled_stale_cleanup_preserves_everything(self) -> None:
        """
        关闭总清理开关时所有旧文件保留
        """
        self.config.transfer_monitor_remove_stale_strm = False
        self._transfer_cleanup()
        self.assertTrue(self.old_strm.exists())
        for name in self.scrap_names:
            self.assertTrue((self.old_dir / name).exists())
