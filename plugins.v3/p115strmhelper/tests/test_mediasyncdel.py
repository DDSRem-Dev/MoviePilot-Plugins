"""
MediaSyncDelHelper 测试模块

包含同步删除相关方法的单元测试
"""

import importlib
import sys
from pathlib import Path
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

    def test_match_file_by_stem_falls_back_to_real_extension(self):
        """
        精确路径不存在时按文件名主干匹配网盘真实文件

        场景：115 上是 (48).mov，Emby 上报的 Container 为 mp4。
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper.storagechain = Mock()
        helper.storagechain.get_file_item.return_value = object()
        real_item = SimpleNamespace(
            type="file",
            basename="(48)",
            path="/MoviePilot/媒体库/demo/(48).mov",
        )
        helper.storagechain.list_files.return_value = [real_item]

        result = helper._MediaSyncDelHelper__match_file_by_stem(
            storage="115网盘Plus",
            file_path="/MoviePilot/媒体库/demo/(48).mp4",
        )

        self.assertIs(result, real_item)

    def test_match_file_by_stem_returns_none_without_parent(self):
        """
        父目录不存在时按主干匹配返回 None，不抛异常
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper.storagechain = Mock()
        helper.storagechain.get_file_item.return_value = None

        result = helper._MediaSyncDelHelper__match_file_by_stem(
            storage="115网盘Plus",
            file_path="/MoviePilot/媒体库/missing/(48).mp4",
        )

        self.assertIsNone(result)
        helper.storagechain.list_files.assert_not_called()

    def test_delete_p115_files_uses_stem_fallback(self):
        """
        网盘文件与 Emby 容器后缀不一致时，仍能删除真实文件
        """
        module = _load_mediasyncdel_module()
        helper = object.__new__(module.MediaSyncDelHelper)
        helper.storagechain = Mock()
        real_item = SimpleNamespace(
            type="file",
            basename="(48)",
            path="/MoviePilot/媒体库/demo/(48).mov",
        )
        # 第一次按期望路径查文件返回 None，第二次查父目录成功
        helper.storagechain.get_file_item.side_effect = [None, object()]
        helper.storagechain.list_files.return_value = [real_item]

        helper._MediaSyncDelHelper__delete_p115_files(
            storage="115网盘Plus",
            file_path="/MoviePilot/媒体库/demo/(48).mp4",
            media_name="(48)",
        )

        helper.storagechain.delete_media_file.assert_called_once_with(
            fileitem=real_item
        )
