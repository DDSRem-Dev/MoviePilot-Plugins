"""独立通知引擎离线回归测试"""

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

path = Path(__file__).resolve().parents[1] / "engine.py"
spec = importlib.util.spec_from_file_location("strmnotify_engine", path)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class TestEngine(TestCase):
    """验证存量过滤、持久化重放与准确匹配"""

    def test_baseline_addition_restart_and_rewrite(self):
        """存量与重写不通知，新文件跨重启保留待处理状态"""
        state = engine.reconcile(None, {"old": 1}, 10)
        self.assertEqual(state["pending"], {})
        state = engine.reconcile(state, {"old": 9, "new": 2}, 20)
        self.assertEqual(state["pending"], {"new": 20})
        self.assertEqual(engine.reconcile(state, {"old": 9, "new": 2}, 30), state)
        state["pending"].clear()
        self.assertEqual(engine.reconcile(state, {"old": 9, "new": 2}, 40)["pending"], {})

    def test_delete_and_recreate(self):
        """已观察到删除后重新创建的路径视作新条目"""
        state = engine.reconcile(None, {"file": 1}, 10)
        state = engine.reconcile(state, {}, 20)
        self.assertEqual(engine.reconcile(state, {"file": 2}, 30)["pending"], {"file": 30})

    def test_reconcile_and_pending_candidates_are_deterministic(self):
        """多目录队列按时间、目录和文件名稳定排序，避免单目录长期占满配额"""
        state = {
            "/media/b": {"known": [], "pending": {"/media/b/z.strm": 20}},
            "/media/a": {"known": [], "pending": {"/media/a/a.strm": 20}},
        }
        self.assertEqual(
            engine.pending_candidates(state),
            [(20.0, "/media/a", "/media/a/a.strm"), (20.0, "/media/b", "/media/b/z.strm")],
        )
        reconciled = engine.reconcile(
            {"known": ["old"], "pending": {}},
            {"z": 1, "a": 2},
            30,
        )
        self.assertEqual(reconciled["known"], ["a", "z"])
        self.assertEqual(list(reconciled["pending"]), ["a", "z"])

    def test_scan_and_unavailable_directory(self):
        """仅扫描 STRM，不跟随符号链接且不可用根目录报错"""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.STRM").write_text("https://example.invalid/media")
            (root / "other.txt").write_text("ignore")
            (root / "link.strm").symlink_to(root / "one.STRM")
            self.assertEqual(len(engine.scan(root)), 1)
            with self.assertRaises(OSError):
                engine.scan(root / "missing")

    def test_exact_nfo_and_xml_fields(self):
        """同名 NFO 优先，解析 XML 转义、演员和远程封面"""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "episode.strm"
            video.touch()
            nfo = root / "episode.nfo"
            nfo.write_text('<episodedetails><title>A &amp; B</title><actor><name>Actor</name></actor><thumb>https://example.invalid/cover.jpg</thumb></episodedetails>')
            os.utime(nfo, (0, 0))
            info = engine.metadata(video, 100)
            self.assertEqual(info["title"], "A & B")
            self.assertEqual(info["actors"], ["Actor"])
            self.assertTrue(info["image"].startswith("https://"))

    def test_movie_fallback_rejects_ambiguous_directory(self):
        """多 STRM 目录不使用公共 movie.nfo，避免串片"""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "one.strm"
            video.touch()
            nfo = root / "movie.nfo"
            nfo.write_text('<movie><title>Movie</title><cover>/private/cover.jpg</cover></movie>')
            os.utime(nfo, (0, 0))
            self.assertIsNone(engine.metadata(video, 100)["image"])
            (root / "two.strm").touch()
            self.assertIsNone(engine.metadata(video, 100))

    def test_incomplete_recent_and_unsafe_nfo(self):
        """未写完、尚未稳定及带实体声明的 NFO 均等待重试"""
        with TemporaryDirectory() as folder:
            video = Path(folder) / "one.strm"
            video.touch()
            nfo = video.with_suffix('.nfo')
            for content in ['<movie>', '<!DOCTYPE movie [<!ENTITY x "bad">]><movie><title>&x;</title></movie>']:
                nfo.write_text(content)
                os.utime(nfo, (0, 0))
                self.assertIsNone(engine.metadata(video, 100))
            nfo.write_text('<movie><title>Movie</title></movie>')
            self.assertIsNone(engine.metadata(video, nfo.stat().st_mtime + 1))

    def test_missing_nfo_is_retryable(self):
        """缺失 NFO 时返回等待状态而不是让扫描任务失败"""
        with TemporaryDirectory() as folder:
            video = Path(folder) / "one.strm"
            video.touch()
            self.assertIsNone(engine.metadata(video, 100))
