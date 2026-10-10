"""
路径缓存测试模块
"""

from typing import Any, Dict, List, Tuple
from unittest import TestCase
from unittest.mock import patch

from core.cache import IdPathCache


class _MemoryCache:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def clear(self) -> None:
        self.data.clear()

    def items(self) -> List[Tuple[str, Any]]:
        return list(self.data.items())


class TestIdPathCache(TestCase):
    """
    测试文件夹 ID 与路径双向缓存
    """

    @patch("core.cache.LRUCache")
    def test_add_cache_replaces_stale_reverse_mapping(self, mock_cache: Any) -> None:
        """
        更新同一 ID 或同一路径时清理旧的反向映射
        """
        mock_cache.side_effect = lambda **_: _MemoryCache()
        cache = IdPathCache()

        cache.add_cache(id=1, directory="/旧目录")
        cache.add_cache(id=1, directory="/新目录")

        self.assertIsNone(cache.get_id_by_dir("/旧目录"))
        self.assertEqual(cache.get_id_by_dir("/新目录"), 1)

        cache.add_cache(id=2, directory="/新目录")

        self.assertIsNone(cache.get_dir_by_id(1))
        self.assertEqual(cache.get_dir_by_id(2), "/新目录")

    @patch("core.cache.LRUCache")
    def test_update_path_prefix_updates_nested_directories(
        self, mock_cache: Any
    ) -> None:
        """
        重命名目录时同步所有已缓存的子目录路径
        """
        mock_cache.side_effect = lambda **_: _MemoryCache()
        cache = IdPathCache()
        cache.add_cache(id=1, directory="/待整理(手动)")
        cache.add_cache(id=2, directory="/待整理(手动)/电影")
        cache.add_cache(id=3, directory="/待整理(手动2)")

        cache.update_path_prefix("/待整理(手动)", "/待整理")

        self.assertEqual(cache.get_dir_by_id(1), "/待整理")
        self.assertEqual(cache.get_dir_by_id(2), "/待整理/电影")
        self.assertIsNone(cache.get_id_by_dir("/待整理(手动)"))
        self.assertEqual(cache.get_dir_by_id(3), "/待整理(手动2)")
