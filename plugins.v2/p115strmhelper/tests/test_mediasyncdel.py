"""
MediaSyncDelHelper 测试模块

包含同步删除相关方法的单元测试
"""

import importlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


def _load_mediasyncdel_module():
    """
    按 MoviePilot 插件包路径加载同步删除模块

    :return: 已加载模块
    """
    plugin_root = Path(__file__).resolve().parent.parent
    moviepilot_path = next(
        (
            path
            for path in sys.path
            if path and Path(path).name == "MoviePilot" and Path(path).exists()
        ),
        None,
    )
    if moviepilot_path:
        sys.path.remove(moviepilot_path)
        sys.path.insert(0, moviepilot_path)

    package_name = "app.plugins.p115strmhelper"
    package = ModuleType(package_name)
    package.__path__ = [str(plugin_root)]
    sys.modules[package_name] = package
    module_name = "app.plugins.p115strmhelper.helper.mediasyncdel"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


class TestMediaSyncDelHelper(TestCase):
    """
    测试 MediaSyncDelHelper
    """

    def test_get_p115_media_suffix_uses_embedded_iso_suffix(self):
        """
        ISO STRM 文件名已带真实后缀时直接返回，不访问网盘目录
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper.storagechain = Mock()

        with patch.object(module.settings, "RMT_MEDIAEXT", [".iso", ".mkv"]):
            result = helper._MediaSyncDelHelper__get_p115_media_suffix(
                "/媒体库/ISO/极限审判 (2026)/极限审判 (2026).iso.strm",
                "/媒体库#/mp#/115",
            )

        self.assertEqual(result, "iso")
        helper.storagechain.get_file_item.assert_not_called()

    def test_resolve_strm_symlink_path_supports_absolute_target(self) -> None:
        """
        绝对软链接目标唯一匹配 MoviePilot 路径时切换到对应映射
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            target_root = root / "linshi"
            source_root.mkdir()
            target_root.mkdir()
            target_path = target_root / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            (source_root / "movie.strm").symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载"
            )

            result = helper._MediaSyncDelHelper__resolve_strm_symlink_path(
                "/emby-media/movie.strm", mappings
            )

        self.assertEqual(
            result,
            ("/emby-linshi/movie.strm", True, source_root / "movie.strm"),
        )

    def test_resolve_strm_symlink_path_supports_relative_target(self) -> None:
        """
        相对软链接目标按软链接父目录转换为绝对路径
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            source_dir = source_root / "电影"
            target_root = root / "linshi"
            target_dir = target_root / "电影"
            source_dir.mkdir(parents=True)
            target_dir.mkdir(parents=True)
            target_path = target_dir / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            (source_dir / "movie.strm").symlink_to(Path("../../linshi/电影/movie.strm"))
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载"
            )

            result = helper._MediaSyncDelHelper__resolve_strm_symlink_path(
                "/emby-media/电影/movie.strm", mappings
            )

        self.assertEqual(
            result,
            ("/emby-linshi/电影/movie.strm", True, source_dir / "movie.strm"),
        )

    def test_resolve_strm_symlink_path_rejects_ambiguous_target(self) -> None:
        """
        软链接目标匹配多条路径映射时阻止同步删除
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            target_root = root / "linshi"
            source_root.mkdir()
            target_root.mkdir()
            target_path = target_root / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            (source_root / "movie.strm").symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载\n"
                f"/emby-other#{target_root}#/emby/其他目录"
            )

            result = helper._MediaSyncDelHelper__resolve_strm_symlink_path(
                "/emby-media/movie.strm", mappings
            )

        self.assertEqual(result, (None, True, source_root / "movie.strm"))

    def test_resolve_strm_symlink_path_ignores_regular_and_hardlink_files(
        self,
    ) -> None:
        """
        普通 STRM 文件和硬链接保持现有路径映射逻辑
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "media"
            source_root.mkdir()
            regular_path = source_root / "regular.strm"
            regular_path.write_text("https://example.com/movie", encoding="utf-8")
            hardlink_path = source_root / "hardlink.strm"
            hardlink_path.hardlink_to(regular_path)
            mappings = f"/emby-media#{source_root}#/emby/整理完成"

            regular_result = helper._MediaSyncDelHelper__resolve_strm_symlink_path(
                "/emby-media/regular.strm", mappings
            )
            hardlink_result = helper._MediaSyncDelHelper__resolve_strm_symlink_path(
                "/emby-media/hardlink.strm", mappings
            )

        self.assertEqual(
            regular_result,
            ("/emby-media/regular.strm", False, None),
        )
        self.assertEqual(
            hardlink_result,
            ("/emby-media/hardlink.strm", False, None),
        )

    def test_sync_del_by_webhook_uses_symlink_target_mapping(self) -> None:
        """
        Webhook 同步删除将软链接目标映射传入统一删除流程
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        sync_del = Mock(return_value={"deleted": True})
        helper._MediaSyncDelHelper__sync_del = sync_del

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            target_root = root / "linshi"
            source_root.mkdir()
            target_root.mkdir()
            target_path = target_root / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            symlink_path = source_root / "movie.strm"
            symlink_path.symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载"
            )
            event_data = SimpleNamespace(
                event="deep.delete",
                item_type="Series",
                item_name="测试剧集",
                item_path="/emby-media/movie.strm",
                tmdb_id=123,
                season_id=None,
                episode_id=None,
                json_object={"Item": {"Container": "mkv"}},
            )

            helper.sync_del_by_webhook(
                event_data=event_data,
                enabled=True,
                notify=False,
                del_source=False,
                delete_symlink=True,
                p115_library_path=mappings,
                p115_force_delete_files=True,
            )

            self.assertFalse(symlink_path.exists())
            self.assertFalse(symlink_path.is_symlink())
            self.assertTrue(target_path.exists())

        sync_del.assert_called_once()
        self.assertEqual(
            sync_del.call_args.kwargs["media_path"],
            "/emby-linshi/movie.strm",
        )
        self.assertTrue(sync_del.call_args.kwargs["symlink_detected"])

    def test_sync_del_by_webhook_keeps_symlink_when_disabled(self) -> None:
        """
        关闭软链接删除开关时保留本地链接
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper._MediaSyncDelHelper__sync_del = Mock(return_value={"deleted": True})

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            target_root = root / "linshi"
            source_root.mkdir()
            target_root.mkdir()
            target_path = target_root / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            symlink_path = source_root / "movie.strm"
            symlink_path.symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载"
            )
            event_data = SimpleNamespace(
                event="deep.delete",
                item_type="Series",
                item_name="测试剧集",
                item_path="/emby-media/movie.strm",
                tmdb_id=123,
                season_id=None,
                episode_id=None,
                json_object={"Item": {"Container": "mkv"}},
            )

            helper.sync_del_by_webhook(
                event_data=event_data,
                enabled=True,
                notify=False,
                del_source=False,
                delete_symlink=False,
                p115_library_path=mappings,
                p115_force_delete_files=True,
            )

            self.assertTrue(symlink_path.is_symlink())
            self.assertTrue(target_path.exists())

    def test_sync_del_by_webhook_skips_ambiguous_symlink_target(self) -> None:
        """
        Webhook 遇到目标映射不唯一的软链接时不进入删除流程
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        sync_del = Mock(return_value={})
        helper._MediaSyncDelHelper__sync_del = sync_del

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            target_root = root / "linshi"
            source_root.mkdir()
            target_root.mkdir()
            target_path = target_root / "movie.strm"
            target_path.write_text("https://example.com/movie", encoding="utf-8")
            symlink_path = source_root / "movie.strm"
            symlink_path.symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载\n"
                f"/emby-other#{target_root}#/emby/其他目录"
            )
            event_data = SimpleNamespace(
                event="deep.delete",
                item_type="Series",
                item_name="测试剧集",
                item_path="/emby-media/movie.strm",
                tmdb_id=123,
                season_id=None,
                episode_id=None,
                json_object={"Item": {"Container": "mkv"}},
            )

            result = helper.sync_del_by_webhook(
                event_data=event_data,
                enabled=True,
                notify=False,
                del_source=False,
                delete_symlink=True,
                p115_library_path=mappings,
                p115_force_delete_files=True,
            )

            self.assertTrue(symlink_path.is_symlink())

        self.assertIsNone(result)
        sync_del.assert_not_called()

    def test_sync_del_by_webhook_expands_directory_strm_files(self) -> None:
        """
        Webhook 删除目录时递归解析普通 STRM 和软链接 STRM
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        sync_del = Mock(return_value={"deleted": True})
        helper._MediaSyncDelHelper__sync_del = sync_del
        helper._MediaSyncDelHelper__get_p115_media_suffix = Mock(return_value="mkv")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            media_directory = source_root / "测试剧集"
            season_directory = media_directory / "Season 01"
            target_root = root / "linshi"
            target_directory = target_root / "测试剧集"
            season_directory.mkdir(parents=True)
            target_directory.mkdir(parents=True)

            regular_path = season_directory / "S01E01.strm"
            regular_path.write_text("https://example.com/episode/1", encoding="utf-8")
            target_path = target_directory / "S01E02.strm"
            target_path.write_text("https://example.com/episode/2", encoding="utf-8")
            symlink_path = season_directory / "S01E02.STRM"
            symlink_path.symlink_to(target_path)
            mappings = (
                f"/emby-media#{source_root}#/emby/整理完成\n"
                f"/emby-linshi#{target_root}#/emby/临时下载"
            )
            event_data = SimpleNamespace(
                event="deep.delete",
                item_type="Series",
                item_name="测试剧集",
                item_path="/emby-media/测试剧集",
                tmdb_id=123,
                season_id=None,
                episode_id=None,
                json_object={"Item": {"Container": "folder"}},
            )

            helper.sync_del_by_webhook(
                event_data=event_data,
                enabled=True,
                notify=False,
                del_source=False,
                delete_symlink=True,
                p115_library_path=mappings,
                p115_force_delete_files=True,
            )

            self.assertTrue(regular_path.exists())
            self.assertFalse(symlink_path.exists())
            self.assertTrue(target_path.exists())

        self.assertEqual(sync_del.call_count, 2)
        calls_by_path = {
            call.kwargs["media_path"]: call.kwargs for call in sync_del.call_args_list
        }
        self.assertEqual(
            set(calls_by_path),
            {
                "/emby-media/测试剧集/Season 01/S01E01.strm",
                "/emby-linshi/测试剧集/S01E02.strm",
            },
        )
        self.assertFalse(
            calls_by_path["/emby-media/测试剧集/Season 01/S01E01.strm"][
                "symlink_detected"
            ]
        )
        self.assertTrue(
            calls_by_path["/emby-linshi/测试剧集/S01E02.strm"]["symlink_detected"]
        )
        self.assertTrue(all(call["exact_path_only"] for call in calls_by_path.values()))

    def test_expand_strm_directory_paths_falls_back_for_missing_directory(
        self,
    ) -> None:
        """
        本地目录已被 Emby 删除时回退为网盘目录映射
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            mappings = f"/emby-media#{Path(temp_dir) / 'media'}#/emby/整理完成"
            result = helper._MediaSyncDelHelper__expand_strm_directory_paths(
                "/emby-media/测试剧集",
                mappings,
            )

        self.assertEqual(result, (["/emby-media/测试剧集"], False))

    def test_sync_del_by_webhook_processes_missing_directory(self) -> None:
        """
        Webhook 在本地目录已被 Emby 删除后继续同步删除
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        sync_del = Mock(return_value={"deleted": True})
        helper._MediaSyncDelHelper__sync_del = sync_del

        with TemporaryDirectory() as temp_dir:
            mappings = f"/emby-media#{Path(temp_dir) / 'media'}#/emby/整理完成"
            event_data = SimpleNamespace(
                event="deep.delete",
                item_type="Series",
                item_name="测试剧集",
                item_path="/emby-media/测试剧集",
                tmdb_id=123,
                season_id=None,
                episode_id=None,
                json_object={"Item": {"Container": "folder"}},
            )

            result = helper.sync_del_by_webhook(
                event_data=event_data,
                enabled=True,
                notify=False,
                del_source=True,
                delete_symlink=False,
                p115_library_path=mappings,
                p115_force_delete_files=True,
            )

        self.assertEqual(result, {"deleted": True})
        sync_del.assert_called_once()
        self.assertEqual(sync_del.call_args.kwargs["media_path"], event_data.item_path)
        self.assertFalse(sync_del.call_args.kwargs["exact_path_only"])

    def test_expand_strm_directory_paths_preserves_directory_prefix(self) -> None:
        """
        目录展开后的 STRM 路径保留 Emby 上报目录层级
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "media"
            season_directory = source_root / "测试剧集" / "Season 01"
            season_directory.mkdir(parents=True)
            (season_directory / "S01E01.strm").write_text(
                "https://example.com/episode/1",
                encoding="utf-8",
            )
            mappings = f"/emby-media#{source_root}#/emby/整理完成"

            result = helper._MediaSyncDelHelper__expand_strm_directory_paths(
                "/emby-media/测试剧集",
                mappings,
            )

        self.assertEqual(
            result,
            (["/emby-media/测试剧集/Season 01/S01E01.strm"], True),
        )

    def test_expand_strm_directory_paths_keeps_media_file_path(self) -> None:
        """
        媒体文件路径不进入目录递归流程
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            mappings = f"/emby-media#{Path(temp_dir) / 'media'}#/emby/整理完成"
            with patch.object(module.settings, "RMT_MEDIAEXT", [".mkv"]):
                result = helper._MediaSyncDelHelper__expand_strm_directory_paths(
                    "/emby-media/测试电影.mkv",
                    mappings,
                )

        self.assertEqual(result, (["/emby-media/测试电影.mkv"], False))

    def test_sync_del_uses_most_specific_overlapping_mapping(self) -> None:
        """
        重叠路径映射按最长媒体服务器前缀转换最终网盘路径
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper.transferhis = Mock()
        helper.transferhis.get_by_dest.return_value = None
        helper._MediaSyncDelHelper__delete_p115_files = Mock()
        helper._save_sync_del_history = Mock()
        parent_mapping = "/media#/local/media#/emby/整理完成"
        child_mapping = "/media/TV#/local/media/TV#/emby/临时下载"

        for mappings in (
            f"{parent_mapping}\n{child_mapping}",
            f"{child_mapping}\n{parent_mapping}",
        ):
            with self.subTest(mappings=mappings):
                helper._MediaSyncDelHelper__delete_p115_files.reset_mock()
                with patch.object(
                    module.configer,
                    "storage_module",
                    "u115",
                    create=True,
                ):
                    helper._MediaSyncDelHelper__sync_del(
                        media_type="Series",
                        media_name="测试剧集",
                        media_path="/media/TV/show/S01E01.strm",
                        tmdb_id=123,
                        season_num=None,
                        episode_num=None,
                        media_suffix="mkv",
                        p115_library_path=mappings,
                        p115_force_delete_files=True,
                        del_source=False,
                        notify=False,
                        exact_path_only=True,
                    )

                helper._MediaSyncDelHelper__delete_p115_files.assert_called_once_with(
                    storage="u115",
                    file_path="/emby/临时下载/show/S01E01.mkv",
                    media_name="测试剧集",
                )

    def test_sync_del_skips_ambiguous_longest_mapping(self) -> None:
        """
        相同最长前缀指向不同网盘目录时阻止同步删除
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        sync_del = Mock(return_value={"deleted": True})
        helper._MediaSyncDelHelper__sync_del = sync_del
        mappings = (
            "/media/TV#/local/media/TV#/emby/临时下载\n"
            "/media/TV#/local/media/TV#/emby/其他目录"
        )
        event_data = SimpleNamespace(
            event="deep.delete",
            item_type="Episode",
            item_name="测试剧集",
            item_path="/media/TV/show/S01E01.strm",
            tmdb_id=123,
            season_id=1,
            episode_id=1,
            json_object={"Item": {"Container": "mkv"}},
        )

        result = helper.sync_del_by_webhook(
            event_data=event_data,
            enabled=True,
            notify=False,
            del_source=False,
            delete_symlink=False,
            p115_library_path=mappings,
            p115_force_delete_files=True,
        )

        self.assertIsNone(result)
        sync_del.assert_not_called()

    def test_expand_directory_uses_most_specific_overlapping_mapping(self) -> None:
        """
        目录展开在父子映射重叠时选择最长媒体服务器前缀
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)

        with TemporaryDirectory() as temp_dir:
            local_root = Path(temp_dir) / "media"
            show_directory = local_root / "TV" / "show"
            show_directory.mkdir(parents=True)
            (show_directory / "S01E01.strm").write_text(
                "https://example.com/episode/1",
                encoding="utf-8",
            )
            mappings = (
                f"/media#{local_root}#/emby/整理完成\n"
                f"/media/TV#{local_root / 'TV'}#/emby/临时下载"
            )

            result = helper._MediaSyncDelHelper__expand_strm_directory_paths(
                "/media/TV/show",
                mappings,
            )

        self.assertEqual(result, (["/media/TV/show/S01E01.strm"], True))

    def test_get_transfer_his_exact_path_avoids_series_wide_query(self) -> None:
        """
        目录展开后的 STRM 仅查询目标路径完全匹配的转移记录
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        transfer_history = SimpleNamespace(id=1)
        helper.transferhis = Mock()
        helper.transferhis.get_by_dest.return_value = transfer_history

        _, result = helper._MediaSyncDelHelper__get_transfer_his(
            media_type="Series",
            media_name="测试剧集",
            media_path="/emby/临时下载/测试剧集/S01E01.mkv",
            tmdb_id=123,
            season_num=None,
            episode_num=None,
            exact_path_only=True,
        )

        self.assertEqual(result, [transfer_history])
        helper.transferhis.get_by_dest.assert_called_once_with(
            "/emby/临时下载/测试剧集/S01E01.mkv"
        )
        helper.transferhis.get_by.assert_not_called()
