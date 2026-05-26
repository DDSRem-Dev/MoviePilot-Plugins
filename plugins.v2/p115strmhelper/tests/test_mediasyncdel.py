"""
MediaSyncDelHelper 测试模块

包含同步删除相关方法的单元测试
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType
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

    return importlib.import_module(
        "app.plugins.p115strmhelper.helper.mediasyncdel"
    )


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
