"""
同步删除入口与实际存储模块的无网络契约测试
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest import TestCase
from unittest.mock import Mock

from test_p115_cleanup import AUDIO, M, ROOT, SUB, VIDEO, FakeChain, mod


PLUGIN = Path(__file__).resolve().parents[1]


def _load_class(
    path: Path, name: str, namespace: Dict[str, Any], method: Optional[str] = None
) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    node.decorator_list = []
    node.bases = []
    if method:
        node.body = [
            n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == method
        ]
    module = ast.Module(
        body=[ast.parse("from __future__ import annotations").body[0], node],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


class StorageProviderContracts(TestCase):
    """
    验证插件入口不会吞掉底层严格查询错误
    """

    def test_storage_providers_propagate_errors_and_missing_state(self) -> None:
        """
        网络错误、未初始化和真实不存在必须保持不同结果
        """
        for folder, name, attribute, storage in (
            ("p115disk", "P115Disk", "_p115_api", "115网盘Plus"),
            ("clouddrivedisk", "CloudDriveDisk", "_clouddrive_api", "CloudDrive储存"),
        ):
            with self.subTest(storage=storage):
                source = PLUGIN.parent / folder / "__init__.py"
                cls = _load_class(source, name, {}, "get_file_item")
                provider = object.__new__(cls)
                provider._disk_name = storage
                api = Mock()
                setattr(provider, attribute, api)
                api.get_item.return_value = None
                self.assertIsNone(provider.get_file_item(storage, Path("/missing")))
                api.get_item.assert_called_once_with(Path("/missing"))
                api.get_item_strict.assert_not_called()
                receipt_cls = _load_class(
                    source,
                    name,
                    {"FileItemQueryResult": SimpleNamespace},
                    "get_file_item_strict",
                )
                receipt_provider = object.__new__(receipt_cls)
                receipt_provider._disk_name = storage
                setattr(receipt_provider, attribute, api)
                api.get_item.reset_mock()
                api.get_item_strict.side_effect = OSError("offline")
                with self.assertRaises(OSError):
                    receipt_provider.get_file_item_strict(storage, Path("/media"))
                api.get_item.assert_not_called()
                api.get_item_strict.side_effect = None
                api.get_item_strict.return_value = None
                receipt = receipt_provider.get_file_item_strict(
                    storage, Path("/missing")
                )
                self.assertIsNotNone(receipt)
                self.assertIsNone(receipt.item)
                item = SimpleNamespace(path="/media/Movie.mkv")
                api.get_item_strict.return_value = item
                self.assertIs(
                    receipt_provider.get_file_item_strict(
                        storage, Path(item.path)
                    ).item,
                    item,
                )
                api.get_item_strict.reset_mock()
                self.assertIsNone(
                    receipt_provider.get_file_item_strict("unrelated", Path("/media"))
                )
                api.get_item_strict.assert_not_called()
                self.assertIn(
                    '"get_file_item_strict": self.get_file_item_strict',
                    source.read_text(),
                )
                setattr(provider, attribute, None)
                self.assertIsNone(provider.get_file_item(storage, Path("/media")))
                self.assertIsNone(provider.get_file_item("unrelated", Path("/media")))
                setattr(receipt_provider, attribute, None)
                with self.assertRaises(RuntimeError):
                    receipt_provider.get_file_item_strict(storage, Path("/media"))


class SyncDeleteEntryContracts(TestCase):
    """
    在真实助手方法上验证类型筛选、后缀回退与历史删除顺序
    """

    def setUp(self) -> None:
        """
        加载真实方法并隔离宿主资源
        """
        self.config = SimpleNamespace(
            sync_del_remove_versions=False,
            sync_del_mediaservers=[],
            storage_module="u115",
        )
        self.settings = SimpleNamespace(
            RMT_MEDIAEXT=VIDEO, RMT_SUBEXT=SUB, RMT_AUDIOEXT=AUDIO
        )
        self.ns = {
            "Path": Path,
            "configer": self.config,
            "settings": self.settings,
            "logger": Mock(),
            "P115Cleaner": mod.P115Cleaner,
            "is_video_library_item": mod.is_video_library_item,
            "dir_event_allowed": mod.dir_event_allowed,
            "looks_like_media_file": mod.looks_like_media_file,
            "valid_container_suffix": mod.valid_container_suffix,
            "_FALLBACK_MEDIA_EXTENSIONS": VIDEO,
            "PathUtils": SimpleNamespace(
                get_p115_media_path=lambda *args: (
                    True,
                    ["/library", "/not-existing-pr492", ROOT],
                ),
                get_media_file_paths_with_suffix=lambda file_path, media_suffix: (
                    file_path,
                    file_path,
                ),
            ),
            "MediaType": SimpleNamespace(MOVIE="movie", TV="tv"),
            "MediaSource": SimpleNamespace(TMDB="tmdb"),
        }
        cls = _load_class(
            PLUGIN / "helper/mediasyncdel/__init__.py", "MediaSyncDelHelper", self.ns
        )
        self.helper = object.__new__(cls)
        self.helper.storagechain = FakeChain([f"{M}/Movie.mkv", f"{M}/Movie.ass"])

    def _event(self, raw: Any, normalized: str = "Movie") -> Any:
        return SimpleNamespace(
            event="deep.delete",
            item_type=normalized,
            item_name="Movie",
            item_path="/library/电影/Movie (2020)/Movie.strm",
            tmdb_id="42",
            season_id=None,
            episode_id=None,
            json_object=raw,
        )

    def _run_event(self, event: Any) -> Any:
        return self.helper.sync_del_by_webhook(
            event, True, False, False, "/library#/not-existing-pr492#" + ROOT, False
        )

    def test_explicit_video_type_fallback_only(self) -> None:
        """
        缺少原始类型时接受明确 Movie，拒绝含混 MOV 和明确非视频类型
        """
        self.helper._MediaSyncDelHelper__sync_del = Mock(return_value={"ok": True})
        self.helper._MediaSyncDelHelper__get_p115_media_suffix = Mock(
            return_value="mkv"
        )
        self.assertEqual(self._run_event(self._event({"Item": {}})), {"ok": True})
        self.helper._MediaSyncDelHelper__sync_del.reset_mock()
        for raw, normalized in (
            ({}, "MOV"),
            ({"Item": {"Type": "Audio"}}, "Movie"),
            ({"Item": []}, "MOV"),
        ):
            self.assertIsNone(self._run_event(self._event(raw, normalized)))
        self.helper._MediaSyncDelHelper__sync_del.assert_not_called()

    def test_actual_delete_entry_resolves_unique_container(self) -> None:
        """
        实际删除入口保留唯一真实后缀回退并复核结果
        """
        result = self.helper._MediaSyncDelHelper__delete_p115_files(
            "u115", f"{M}/Movie.mp4", "Movie", ROOT
        )
        self.assertTrue(result)
        self.assertEqual(self.helper.storagechain.files, set())

    def _sync(self) -> Dict[str, Any]:
        return self.helper._MediaSyncDelHelper__sync_del(
            media_type="Movie",
            media_name="Movie",
            media_path="/library/电影/Movie (2020)/Movie.mkv",
            tmdb_id=42,
            season_num=None,
            episode_num=None,
            media_suffix="mkv",
            p115_library_path="/library#/not-existing-pr492#" + ROOT,
            p115_force_delete_files=False,
            del_source=False,
            notify=False,
        )

    def test_history_is_retained_when_cloud_cleanup_fails(self) -> None:
        """
        网盘查询异常不得清除转移历史或写入成功记录
        """
        record = SimpleNamespace(
            id=1,
            title="Movie",
            image=None,
            year=2020,
            dest=f"{M}/Movie.mkv",
            dest_storage="u115",
        )
        self.helper._MediaSyncDelHelper__get_transfer_his = Mock(
            return_value=("Movie", [record])
        )
        self.helper.storagechain.get_file_item_strict = Mock(
            side_effect=OSError("offline")
        )
        self.helper._delete_transfer_history = Mock(return_value=True)
        self.helper._save_sync_del_history = Mock()
        result = self._sync()
        self.assertEqual(result["error_cnt"], 1)
        self.helper._delete_transfer_history.assert_not_called()
        self.helper._save_sync_del_history.assert_not_called()

    def test_history_removed_only_after_cloud_verification(self) -> None:
        """
        删除转移记录时网盘文件必须已经确认消失
        """
        record = SimpleNamespace(
            id=1,
            title="Movie",
            image=None,
            year=2020,
            dest=f"{M}/Movie.mkv",
            dest_storage="u115",
        )
        self.helper._MediaSyncDelHelper__get_transfer_his = Mock(
            return_value=("Movie", [record])
        )

        def history(record_id):
            self.assertNotIn(record.dest, self.helper.storagechain.files)
            return True

        self.helper._delete_transfer_history = Mock(side_effect=history)
        self.helper._save_sync_del_history = Mock()
        self.assertEqual(self._sync()["error_cnt"], 0)
        self.helper._delete_transfer_history.assert_called_once_with(1)
        self.helper._save_sync_del_history.assert_called_once()
