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
from typing import Any, Dict
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
