"""
增量同步实例隔离与源文件映射回归测试
"""

from __future__ import annotations

import ast
from collections import deque
from itertools import cycle
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4


class _SharedTree:
    """
    按路径或 Redis 键名共享数据的目录树替身
    """

    def __init__(self, path: Path, backend: str, data: Dict[str, List[str]]) -> None:
        self.path = path
        self.key = path.stem if backend == "redis" else str(path)
        self.data = data
        self.after_append = None

    def generate_tree_from_list(self, paths: List[str], append: bool = False) -> None:
        """
        写入路径并在追加完成后触发竞态注入
        """
        if not append:
            self.clear()
        self.data.setdefault(self.key, []).extend(paths)
        self.path.touch()
        if append and self.after_append:
            callback, self.after_append = self.after_append, None
            callback()

    def compare_trees(self, other: _SharedTree) -> Iterator[str]:
        """
        以反向顺序返回差集，验证配对不依赖枚举顺序
        """
        yield from sorted(
            set(self.data.get(self.key, [])) - set(other.data.get(other.key, [])),
            reverse=True,
        )

    def compare_trees_lines(self, other: _SharedTree) -> Iterator[int]:
        """
        提供旧实现使用的行号差集，支持复现原始故障
        """
        for index, path in enumerate(self.data.get(self.key, []), 1):
            if path not in other.data.get(other.key, []):
                yield index

    def get_path_by_line_number(self, line: int) -> Optional[str]:
        """
        返回指定行的路径
        """
        paths = self.data.get(self.key, [])
        return paths[line - 1] if 0 < line <= len(paths) else None

    def count(self) -> int:
        """
        返回条目数
        """
        return len(self.data.get(self.key, []))

    def clear(self) -> None:
        """
        清理当前键或文件
        """
        self.data.pop(self.key, None)
        self.path.unlink(missing_ok=True)


def _load_helper(root: Path, backend: str) -> Tuple[type, Dict[str, Any]]:
    source = Path(__file__).resolve().parents[1] / "helper/strm/increment.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "IncrementSyncStrmHelper"
    )
    config = Mock()
    config.get_config.side_effect = lambda key: {
        "PLUGIN_TEMP_PATH": root,
        "user_rmt_mediaext": "mkv,mp4",
        "user_download_mediaext": "srt,nfo,jpg",
        "increment_sync_auto_download_mediainfo_enabled": True,
    }.get(key, False)
    config.PLUGIN_TEMP_PATH = root
    config.increment_sync_second_level_dir_scan = False
    config.increment_sync_remove_unless_strm = False
    data = {}
    namespace = {
        "Path": Path,
        "cycle": cycle,
        "deque": deque,
        "uuid4": uuid4,
        "perf_counter": perf_counter,
        "sleep": Mock(),
        "configer": config,
        "settings": Mock(CACHE_BACKEND_TYPE=backend),
        "logger": Mock(),
        "sentry_manager": Mock(),
        "ItertreeInternalError": RuntimeError,
        "DirectoryTree": lambda path: _SharedTree(path, backend, data),
        **{
            name: Mock()
            for name in (
                "FileDbHelper",
                "DirectoryCache",
                "AutomatonUtils",
                "StrmUrlGetter",
                "MediaServerRefresh",
            )
        },
    }
    exec(
        compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace[helper.name], namespace


class TestIncrementMapping(TestCase):
    """
    使用真实构造、析构、目录树构建和同步入口验证源文件配对
    """

    def _create_helper(self, helper_class: type, pairs: List[Tuple[str, str]]) -> Any:
        helper = helper_class(Mock(), Mock())
        helper.mediainfodownloader.batch_auto_downloader.return_value = (0, 0, [])
        helper._IncrementSyncStrmHelper__itertree = Mock(return_value=iter(pairs))
        helper._IncrementSyncStrmHelper__handle_addition_path = Mock()
        helper._IncrementSyncStrmHelper__wait_generate_local_tree = Mock()

        def scan(target_dir: str) -> None:
            helper.local_tree.generate_tree_from_list([])
            helper.local_strm_tree.generate_tree_from_list([])

        helper._IncrementSyncStrmHelper__generate_local_tree = scan
        self.addCleanup(helper.__del__)
        return helper

    def _run(self, helper: Any) -> Dict[str, str]:
        helper.generate_strm_files("/local#/remote")
        return {
            call.kwargs["local_path"]: call.kwargs["pan_path"]
            for call in helper._IncrementSyncStrmHelper__handle_addition_path.call_args_list
        }

    def test_old_destructor_cannot_shift_episodes(self) -> None:
        """
        首条本地路径写入后析构旧实例，三集仍各自对应正确源文件
        """
        pairs = [(f"/local/E{i:02}.strm", f"/remote/E{i:02}.mkv") for i in (9, 10, 11)]
        for backend in ("txt", "redis"):
            with self.subTest(backend=backend), TemporaryDirectory() as tmp:
                helper_class, _ = _load_helper(Path(tmp), backend)
                old = self._create_helper(helper_class, [])
                new = self._create_helper(helper_class, pairs)
                new.pan_to_local_tree.after_append = old.__del__
                self.assertEqual(self._run(new), dict(pairs))

    def test_conflicting_sources_are_skipped_and_preserved_in_cleanup_tree(
        self,
    ) -> None:
        """
        同名不同扩展名及路径清洗冲突均跳过，仍保留远端存在性记录以防误删
        """
        pairs = [
            ("/local/E09.strm", "/remote/E09.mkv"),
            ("/local/E09.strm", "/remote/E09.mp4"),
            ("/local/E09.strm", "/remote/E09.mkv"),
            ("/local/ab.strm", "/remote/a:b.mkv"),
            ("/local/ab.strm", "/remote/a?b.mkv"),
            ("/local/E10.strm", "/remote/E10.mkv"),
        ]
        with TemporaryDirectory() as tmp:
            helper_class, namespace = _load_helper(Path(tmp), "redis")
            helper = self._create_helper(helper_class, pairs)
            self.assertEqual(self._run(helper), dict(pairs[-1:]))
            self.assertIn(
                "/local/E09.strm",
                list(helper.pan_to_local_strm_tree.compare_trees(helper.local_tree)),
            )
            self.assertIn(
                "/local/ab.strm",
                list(helper.pan_to_local_strm_tree.compare_trees(helper.local_tree)),
            )
            self.assertTrue(namespace["logger"].warning.called)

    def test_invalid_types_do_not_reach_file_generation(self) -> None:
        """
        视频与字幕交叉映射及附件扩展名不一致时不生成或下载文件
        """
        pairs = [
            ("/local/E09.strm", "/remote/E09.srt"),
            ("/local/E10.srt", "/remote/E10.mkv"),
            ("/local/poster.jpg", "/remote/movie.nfo"),
            ("/local/E11.strm", "/remote/E11.MKV"),
            ("/local/E11.SRT", "/remote/E11.srt"),
            ("/local/movie.nfo", "/remote/movie.nfo"),
        ]
        with TemporaryDirectory() as tmp:
            helper_class, namespace = _load_helper(Path(tmp), "redis")
            helper = self._create_helper(helper_class, pairs)
            self.assertEqual(self._run(helper), dict(pairs[3:]))
            self.assertEqual(namespace["logger"].warning.call_count, 3)

    def test_identical_duplicate_and_existing_file(self) -> None:
        """
        重复的相同映射可正常生成，已存在的本地文件不再次处理
        """
        pairs = [
            ("/local/E09.strm", "/remote/E09.mkv"),
            ("/local/E09.strm", "/remote/E09.mkv"),
            ("/local/E10.strm", "/remote/E10.mkv"),
        ]
        with TemporaryDirectory() as tmp:
            helper_class, _ = _load_helper(Path(tmp), "redis")
            helper = self._create_helper(helper_class, pairs)
            helper._IncrementSyncStrmHelper__generate_local_tree = lambda **kwargs: (
                helper.local_tree.generate_tree_from_list(["/local/E10.strm"])
            )
            self.assertEqual(self._run(helper), dict(pairs[:1]))
            helper._IncrementSyncStrmHelper__handle_addition_path.assert_called_once()

    def test_missing_mapping_is_skipped(self) -> None:
        """
        目录树中存在但没有源映射的路径不会回退到行号配对
        """
        pairs = [("/local/E09.strm", "/remote/E09.mkv")]
        with TemporaryDirectory() as tmp:
            helper_class, namespace = _load_helper(Path(tmp), "redis")
            helper = self._create_helper(helper_class, pairs)
            helper._IncrementSyncStrmHelper__wait_generate_local_tree = lambda _: (
                helper._pan_path_by_local.clear()
            )
            self.assertEqual(self._run(helper), {})
            self.assertIn("缺少网盘源路径映射", helper.strm_fail_dict[pairs[0][0]])
            namespace["logger"].warning.assert_called_once()

    def test_retry_and_next_directory_reset_mappings(self) -> None:
        """
        重试和切换同步目录时不残留之前的源路径或冲突标记
        """
        pairs = [("/local/E09.strm", "/remote/E09.mkv")]

        def interrupted_export() -> Iterator[Tuple[str, str]]:
            yield "/local/stale.strm", "/remote/stale.mkv"
            yield "/local/E09.strm", "/remote/E09.mp4"
            yield pairs[0]
            raise OSError("Broken pipe")

        with TemporaryDirectory() as tmp:
            helper_class, _ = _load_helper(Path(tmp), "redis")
            helper = self._create_helper(helper_class, pairs)
            helper._IncrementSyncStrmHelper__itertree = Mock(
                side_effect=[interrupted_export(), iter(pairs), iter([])]
            )
            self.assertEqual(self._run(helper), dict(pairs))
            self.assertEqual(helper._pan_path_by_local, dict(pairs))
            helper._IncrementSyncStrmHelper__generate_pan_tree("/other", "/other-local")
            self.assertEqual(helper._pan_path_by_local, {})
            self.assertEqual(helper.pan_to_local_tree.count(), 0)
            self.assertEqual(helper.pan_to_local_strm_tree.count(), 0)

    def test_all_trees_are_isolated_and_owned_data_is_cleaned(self) -> None:
        """
        TXT 文件和 Redis 键均独立，析构只清理所属实例的所有树
        """
        for backend in ("txt", "redis"):
            with self.subTest(backend=backend), TemporaryDirectory() as tmp:
                helper_class, _ = _load_helper(Path(tmp), backend)
                old = self._create_helper(helper_class, [])
                new = self._create_helper(helper_class, [])
                tree_names = (
                    "local_tree",
                    "local_strm_tree",
                    "pan_to_local_tree",
                    "pan_to_local_strm_tree",
                )
                for name in tree_names:
                    getattr(old, name).generate_tree_from_list(["/old"])
                    getattr(new, name).generate_tree_from_list(["/new"])
                old.__del__()
                for name in tree_names:
                    self.assertEqual(getattr(old, name).count(), 0)
                    self.assertEqual(getattr(new, name).count(), 1)
                new.__del__()
                for name in tree_names:
                    self.assertEqual(getattr(new, name).count(), 0)
                    self.assertFalse(getattr(new, name).path.exists())

    def test_generated_urls_and_downloads_use_the_mapped_source(self) -> None:
        """
        真实写入的 STRM 内容和字幕下载项对应源文件，重叠扩展名优先生成 STRM
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper_class, namespace = _load_helper(root, "redis")
            pairs = [
                (str(root / "E09.strm"), "/remote/E09.mkv"),
                (str(root / "E10.strm"), "/remote/E10.mkv"),
                (str(root / "E10.srt"), "/remote/E10.srt"),
            ]
            helper = self._create_helper(helper_class, pairs)
            del helper._IncrementSyncStrmHelper__handle_addition_path
            helper.directory_cache.is_in_cache.return_value = False
            helper.pan_transfer_enabled = False
            helper.emby_mediainfo_enabled = False
            helper.download_mediaext.append(".mkv")
            namespace["configer"].pan_transfer_unrecognized_path = None
            namespace["StrmGenerater"] = Mock()
            namespace["StrmGenerater"].should_generate_strm.return_value = ("", True)
            namespace["StrmGenerater"].not_min_limit.return_value = ("", True)
            namespace["MediainfoDownloadMiddleware"] = Mock()
            namespace["MediainfoDownloadMiddleware"].should_download.return_value = (
                "",
                True,
            )
            helper._IncrementSyncStrmHelper__get_size = Mock(return_value=1024)
            codes = {
                "/remote/E09.mkv": "a" * 17,
                "/remote/E10.mkv": "b" * 17,
                "/remote/E10.srt": "c" * 17,
            }
            helper._IncrementSyncStrmHelper__get_pickcode_sha1 = lambda path: (
                codes[path],
                "sha1",
            )
            helper.strmurlgetter.get_strm_url.side_effect = lambda code, name, path: (
                f"https://example.test/{code}?path={path}"
            )
            helper.generate_strm_files("/local#/remote")
            for local_path, remote_path in pairs[:2]:
                self.assertEqual(
                    Path(local_path).read_text(encoding="utf-8"),
                    f"https://example.test/{codes[remote_path]}?path={remote_path}",
                )
            self.assertEqual(helper.strm_count, 2)
            self.assertEqual(helper.strm_fail_count, 0)
            self.assertEqual(
                helper.download_mediainfo_list,
                [
                    {
                        "type": "local",
                        "pickcode": codes[pairs[2][1]],
                        "path": pairs[2][0],
                        "sha1": "sha1",
                    }
                ],
            )
