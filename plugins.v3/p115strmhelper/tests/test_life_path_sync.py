"""
生活事件路径同步测试模块
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import SkipTest, TestCase
from unittest.mock import MagicMock, patch


def _load_life_module() -> Any:
    """
    按插件包路径加载生活事件模块

    :return Any: 已加载的生活事件模块
    """
    plugin_root = Path(__file__).resolve().parents[1]
    package_name = "app.plugins.p115strmhelper"
    package = ModuleType(package_name)
    package.__path__ = [str(plugin_root)]
    sys.modules[package_name] = package
    return importlib.import_module("app.plugins.p115strmhelper.helper.life.client")


class TestMonitorLifeRenamePathSync(TestCase):
    """
    测试生活事件重命名的路径同步
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载生活事件模块，缺少插件运行依赖时跳过本组测试
        """
        try:
            cls.life_module = _load_life_module()
        except ModuleNotFoundError as exc:
            if exc.name not in {"aligo", "diskcache"}:
                raise
            raise SkipTest(f"缺少插件运行依赖: {exc.name}") from exc

    def test_non_media_folder_rename_syncs_database_and_cache(self) -> None:
        """
        非媒体目录文件夹重命名时同步数据库和目录缓存
        """
        module = self.life_module
        monitor = object.__new__(module.MonitorLife)
        database = MagicMock()
        database.get_by_id.return_value = {"path": "/待整理(手动)/电影"}
        cache = MagicMock()
        cache.get_dir_by_id.return_value = "/待整理(手动)/电影"
        config = MagicMock()
        config.monitor_life_enabled = True
        config.monitor_life_paths = "/媒体库#/local/media"
        config.monitor_life_event_modes = ["rename"]
        config.pan_transfer_enabled = False
        config.pan_transfer_paths = None
        config.pan_transfer_unrecognized_path = None
        config.get_ios_ua_app.return_value = {}
        event = {
            "file_id": 10,
            "file_category": 0,
            "type": 20,
            "file_name": "电影",
        }

        with (
            patch.object(module, "configer", config),
            patch.object(module, "FileDbHelper", return_value=database),
            patch.object(module, "idpathcacher", cache),
            patch.object(module, "get_path", return_value="/待整理/电影") as get_path,
        ):
            monitor._client = MagicMock()
            monitor.rename(event)

        get_path.assert_called_once()
        database.update_path_prefix_batch.assert_called_once_with(
            "/待整理(手动)/电影", "/待整理/电影", False
        )
        cache.update_path_prefix.assert_called_once_with(
            "/待整理(手动)/电影", "/待整理/电影"
        )
        cache.add_cache.assert_called_once_with(id=10, directory="/待整理/电影")

    def test_transfer_path_rename_reuses_resolved_path(self) -> None:
        """
        待整理目录内文件重命名时复用路径查询结果触发整理
        """
        module = self.life_module
        monitor = object.__new__(module.MonitorLife)
        monitor.rmt_mediaext = [".mkv"]
        database = MagicMock()
        database.get_by_id.return_value = {"path": "/待整理(手动)/电影.mkv"}
        cache = MagicMock()
        config = MagicMock()
        config.monitor_life_enabled = True
        config.monitor_life_paths = "/媒体库#/local/media"
        config.monitor_life_event_modes = ["rename"]
        config.pan_transfer_enabled = True
        config.pan_transfer_paths = "/待整理"
        config.pan_transfer_unrecognized_path = None
        config.get_ios_ua_app.return_value = {}
        event = {
            "file_id": 11,
            "file_category": 1,
            "type": 24,
            "file_name": "电影.mkv",
            "file_size": 100,
            "pick_code": "pick-code",
            "update_time": 1,
        }

        with (
            patch.object(module, "configer", config),
            patch.object(module, "FileDbHelper", return_value=database),
            patch.object(module, "idpathcacher", cache),
            patch.object(
                module, "get_path", return_value="/待整理/电影.mkv"
            ) as get_path,
            patch.object(monitor, "media_transfer") as media_transfer,
        ):
            monitor._client = MagicMock()
            monitor.rename(event)

        get_path.assert_called_once()
        media_transfer.assert_called_once_with(
            event=event,
            file_path=Path("/待整理/电影.mkv"),
            rmt_mediaext=[".mkv"],
        )

    def test_parent_path_resolution_uses_database_without_api(self) -> None:
        """
        重命名后的父目录从数据库解析时不再访问 115 路径接口
        """
        module = self.life_module
        monitor = object.__new__(module.MonitorLife)
        database = MagicMock()
        database.get_by_id.return_value = {"path": "/待整理"}
        cache = MagicMock()
        cache.get_dir_by_id.return_value = None

        with (
            patch.object(module, "FileDbHelper", return_value=database),
            patch.object(module, "idpathcacher", cache),
            patch.object(module, "get_path") as get_path,
        ):
            monitor._client = MagicMock()
            result = monitor._get_path_by_cid(10)

        self.assertEqual(result, Path("/待整理"))
        get_path.assert_not_called()
