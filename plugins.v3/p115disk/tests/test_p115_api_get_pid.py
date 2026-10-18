"""
P115Api.get_pid_by_path 回归测试

覆盖两个缺陷：
1. 命中目录后未写路径缓存，导致每次 list 都重新请求 115 接口；
2. 在 web / app 之间交替调用，web 接口偶发 405 时整次调用直接返回 -1（列表变空）。
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock

from app.schemas import FileItem


def _load_api_module():
    """
    按 MoviePilot 插件包路径加载 p115_api 模块

    :return: 已加载模块
    """
    plugin_root = Path(__file__).resolve().parent.parent
    package_name = "app.plugins.p115disk"
    package = ModuleType(package_name)
    package.__path__ = [str(plugin_root)]
    sys.modules[package_name] = package
    module_name = "app.plugins.p115disk.p115_api"
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def _build_api(module):
    """
    构造一个只带缓存与客户端的 P115Api 实例，跳过真实网络初始化

    :param module: p115_api 模块

    :return: P115Api 实例
    """
    api = object.__new__(module.P115Api)
    api.client = Mock()
    api._disk_name = "115网盘Plus"
    api._id_cache = module.IdPathCache(maxsize=16)
    api._id_item_cache = module.ItemIdCache(maxsize=16)
    api._get_pid_by_path_rate_limiter = Mock()
    api._get_pid_by_path_rate_limiter.acquire = Mock()
    return api


class TestGetPidByPath(TestCase):
    """测试 get_pid_by_path 的缓存与接口回退行为"""

    def test_caches_pid_after_success(self):
        """首次查询成功后写入路径缓存，第二次直接命中缓存"""
        module = _load_api_module()
        api = _build_api(module)
        api.client.fs_dir_getid_app.return_value = {"state": True, "id": "123"}
        path = Path("/MoviePilot/媒体库/电影/华语电影")

        first = api.get_pid_by_path(path)
        second = api.get_pid_by_path(path)

        self.assertEqual(first, 123)
        self.assertEqual(second, 123)
        # 只应请求一次 115 接口
        self.assertEqual(api.client.fs_dir_getid_app.call_count, 1)
        api.client.fs_dir_getid.assert_not_called()

    def test_falls_back_to_web_when_app_fails(self):
        """app 接口失败时回退 web 接口，不返回 -1"""
        module = _load_api_module()
        api = _build_api(module)
        api.client.fs_dir_getid_app.side_effect = RuntimeError("app 不可用")
        api.client.fs_dir_getid.return_value = {"state": True, "id": "456"}

        result = api.get_pid_by_path(Path("/MoviePilot/媒体库/电影"))

        self.assertEqual(result, 456)
        api.client.fs_dir_getid.assert_called_once()

    def test_returns_minus_one_when_both_interfaces_fail(self):
        """两个接口都失败时返回 -1，交给上层判空"""
        module = _load_api_module()
        api = _build_api(module)
        api.client.fs_dir_getid_app.side_effect = RuntimeError("app 失败")
        api.client.fs_dir_getid.side_effect = RuntimeError("web 405")
        api.get_item = Mock(return_value=None)

        result = api.get_pid_by_path(Path("/MoviePilot/媒体库/电影"))

        self.assertEqual(result, -1)

    def test_root_path_returns_zero(self):
        """根路径直接返回 0，不发起请求"""
        module = _load_api_module()
        api = _build_api(module)

        self.assertEqual(api.get_pid_by_path(Path("/")), 0)
        api.client.fs_dir_getid_app.assert_not_called()
        api.client.fs_dir_getid.assert_not_called()

    def test_creates_directory_when_id_is_zero(self):
        """返回 id=0 时按原逻辑创建目录并写入缓存"""
        module = _load_api_module()
        api = _build_api(module)
        api.client.fs_dir_getid_app.return_value = {"state": True, "id": "0"}
        api.client.fs_makedirs_app.return_value = {"state": True, "cid": "789"}
        path = Path("/MoviePilot/媒体库/新目录")

        result = api.get_pid_by_path(path)

        self.assertEqual(result, 789)
        self.assertEqual(api.get_pid_by_path(path), 789)
        # 创建后应命中缓存，不再重复请求
        self.assertEqual(api.client.fs_dir_getid_app.call_count, 1)

    def test_falls_back_to_get_item_when_interface_errors(self):
        """接口异常且降级查询命中时返回该目录 id"""
        module = _load_api_module()
        api = _build_api(module)
        api.client.fs_dir_getid_app.side_effect = RuntimeError("app 失败")
        api.client.fs_dir_getid.side_effect = RuntimeError("web 失败")
        api.get_item = Mock(
            return_value=FileItem(
                storage="115网盘Plus",
                fileid="999",
                path="/MoviePilot/媒体库/电影/",
                name="电影",
                basename="电影",
                type="dir",
            )
        )

        self.assertEqual(api.get_pid_by_path(Path("/MoviePilot/媒体库/电影")), 999)
