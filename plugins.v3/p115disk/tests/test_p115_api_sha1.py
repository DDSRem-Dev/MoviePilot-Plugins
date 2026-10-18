"""
P115Api SHA1 计算与缓存回归测试

覆盖：
1. 大文件分块从 8KB 提升到 8MB 后哈希结果不变；
2. SHA1 缓存命中（同路径 + 大小 + mtime 只计算一次）；
3. 文件变化后缓存失效；
4. 缓存容量上限触发清理。
"""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch


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
    构造只带 SHA1 缓存所需字段的 P115Api 实例

    :param module: p115_api 模块

    :return: P115Api 实例
    """
    api = object.__new__(module.P115Api)
    api._sha1_cache = {}
    api._sha1_cache_max = 64
    import threading

    api._sha1_lock = threading.RLock()
    return api


class TestSha1(TestCase):
    """测试 _calc_sha1 与 SHA1 缓存"""

    def setUp(self):
        """创建临时文件"""
        self.module = _load_api_module()
        handle, self.path = tempfile.mkstemp(suffix=".bin")
        os.close(handle)
        self.file = Path(self.path)
        # 1.5 MB 可跨多块，校验分块拼接正确
        self.file.write_bytes(bytes(range(256)) * 6144)

    def tearDown(self):
        """清理临时文件"""
        self.file.unlink(missing_ok=True)

    def test_calc_sha1_matches_hashlib(self):
        """分块读取的 SHA1 与内存整块计算一致"""
        import hashlib

        with patch.object(self.module.global_vars, "is_transfer_stopped", return_value=False):
            value = self.module.P115Api._calc_sha1(self.file)
        self.assertEqual(value, hashlib.sha1(self.file.read_bytes()).hexdigest())

    def test_calc_sha1_raises_when_stopped(self):
        """传输被取消时抛出 InterruptedError"""
        with patch.object(self.module.global_vars, "is_transfer_stopped", return_value=True):
            with self.assertRaises(InterruptedError):
                self.module.P115Api._calc_sha1(self.file)

    def test_calc_sha1_prefix_size(self):
        """指定 size 时只计算前 N 字节"""
        import hashlib

        with patch.object(self.module.global_vars, "is_transfer_stopped", return_value=False):
            value = self.module.P115Api._calc_sha1(self.file, size=1024)
        self.assertEqual(value, hashlib.sha1(self.file.read_bytes()[:1024]).hexdigest())

    def test_sha1_cache_hit_computes_once(self):
        """同一文件第二次调用命中缓存，不再重新读取"""
        api = _build_api(self.module)
        with patch.object(
            self.module.P115Api, "_calc_sha1", return_value="deadbeef"
        ) as calc:
            first = api._sha1_with_cache(self.file)
            second = api._sha1_with_cache(self.file)

        self.assertEqual(first, "deadbeef")
        self.assertEqual(second, "deadbeef")
        self.assertEqual(calc.call_count, 1)

    def test_sha1_cache_invalidated_on_change(self):
        """文件大小或 mtime 变化后缓存失效并重新计算"""
        api = _build_api(self.module)
        with patch.object(
            self.module.P115Api, "_calc_sha1", side_effect=["aaa", "bbb"]
        ) as calc:
            self.assertEqual(api._sha1_with_cache(self.file), "aaa")
            # 修改内容并推进 mtime
            self.file.write_bytes(b"changed" * 100)
            stat = self.file.stat()
            os.utime(self.file, (stat.st_atime, stat.st_mtime + 10))
            self.assertEqual(api._sha1_with_cache(self.file), "bbb")

        self.assertEqual(calc.call_count, 2)

    def test_sha1_cache_clears_when_oversized(self):
        """缓存超过上限时整体清理，不会无限增长"""
        api = _build_api(self.module)
        api._sha1_cache_max = 2
        api._sha1_cache = {"a": "1", "b": "2", "c": "3"}
        api._store_cached_sha1(self.file, "value")

        self.assertLessEqual(len(api._sha1_cache), 2)
        self.assertEqual(api._get_cached_sha1(self.file), "value")

    def test_sequential_read_hint_is_safe(self):
        """顺序读提示在任意平台都不抛异常"""
        with open(self.file, "rb") as f:
            self.module.P115Api._hint_sequential_read(f)

    def test_sha1_cache_invalidated_on_same_second_same_size(self):
        """
        同路径、同字节数、同秒内被替换时缓存必须失效

        这是评审指出的窗口：秒级 mtime + 大小不足以标识文件内容。
        通过原地写入相同长度内容并把 mtime 固定在同一秒内复现。
        """
        api = _build_api(self.module)
        payload = b"a" * 1024
        self.file.write_bytes(payload)
        stat = self.file.stat()
        same_second = stat.st_mtime_ns // 1_000_000_000 * 1_000_000_000
        os.utime(self.file, ns=(same_second, same_second))

        with patch.object(
            self.module.P115Api, "_calc_sha1", side_effect=["first", "second"]
        ) as calc:
            self.assertEqual(api._sha1_with_cache(self.file), "first")
            # 覆盖为等长内容，并把 mtime 固定回同一秒
            self.file.write_bytes(b"b" * 1024)
            os.utime(self.file, ns=(same_second, same_second))
            self.assertEqual(api._sha1_with_cache(self.file), "second")

        self.assertEqual(calc.call_count, 2)

    def test_sha1_cache_key_uses_nanosecond_mtime(self):
        """
        缓存键包含纳秒级 mtime、ctime 与 inode，避免秒级精度碰撞
        """
        stat = self.file.stat()
        key = self.module.P115Api._sha1_cache_key(self.file, stat)

        self.assertIn(f":{stat.st_mtime_ns}:{stat.st_ctime_ns}:", key)
        self.assertTrue(key.endswith(f":{stat.st_ino}"))
