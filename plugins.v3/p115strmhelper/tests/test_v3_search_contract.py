import ast
import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, Union
from unittest import TestCase
from unittest.mock import AsyncMock

import test_v3_scrape_identity as host_fixture


class TestV3SearchContract(TestCase):
    """
    使用真实媒体投影验证搜索排序与资源查询字段
    """

    def setUp(self) -> None:
        """
        加载宿主媒体模型并隔离在线搜索
        """
        self.host_fixture = host_fixture.TestV3ScrapeIdentity()
        self.addCleanup(self.host_fixture.doCleanups)
        self.host_fixture.setUp()
        self.root = Path(__file__).resolve().parents[1]
        path = self.root / "helper/search/media/__init__.py"
        spec = importlib.util.spec_from_file_location("_p115_search_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.searcher = module.MediaSearcher
        self.host_fixture.settings.SEARCH_SOURCE = "douban,themoviedb"
        self.search = AsyncMock()
        self.host_fixture.chain.async_search = self.search

    def test_native_sources_follow_host_order_before_count_limit(self) -> None:
        """
        原生来源按宿主设置稳定排序后截取，不丢失媒体身份
        """
        context = self.host_fixture.context
        types = self.host_fixture.types
        medias = [
            context.MediaInfo(
                media_source=source,
                media_id=str(index),
                type=types.MediaType.MOVIE,
                title=f"电影{index}",
            )
            for index, source in enumerate(
                [
                    types.MediaSource.TMDB,
                    types.MediaSource.Douban,
                    types.MediaSource.Douban,
                    types.MediaSource.Bangumi,
                ],
                start=1,
            )
        ]
        self.search.return_value = (None, medias)
        result = self.searcher.search_like_api("  电影  ", 2)
        self.assertEqual([item["media_id"] for item in result], ["2", "3"])
        self.assertTrue(all(item["media_source"] == "douban" for item in result))
        self.search.assert_awaited_once_with(title="电影")

    def test_source_accessor_matches_actual_host_endpoint(self) -> None:
        """
        字典与媒体对象的来源读取遵循宿主新字段及旧缓存回退合同
        """
        host = Path(
            os.environ.get("MOVIEPILOT_SOURCE", self.root.parents[2] / "MoviePilot")
        )
        path = host / "app/api/endpoints/media.py"
        node = next(
            node
            for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_get_search_result_source"
        )
        namespace = {
            "Union": Union,
            "Any": Any,
            "Dict": Dict,
            "_SchemaMediaInfo": object,
            "_SchemaMediaPerson": object,
        }
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
            namespace,
        )
        expected = namespace[node.name]
        for value in [
            {"media_source": "douban", "source": "themoviedb"},
            {"media_source": None, "source": "themoviedb"},
            {},
            self.host_fixture.context.MediaInfo(
                media_source="themoviedb", media_id="42"
            ),
        ]:
            with self.subTest(value=value):
                self.assertEqual(self.searcher._get_source(value), expected(value))

    def test_tmdb_projection_keeps_existing_re0_resource_key(self) -> None:
        """
        TMDB 辅助字段仍由宿主提供，资源查询无需把其他来源 ID 当成 TMDB
        """
        media = self.host_fixture.context.MediaInfo(
            tmdb_info={"id": 42, "title": "电影", "media_type": "movie"}
        )
        self.search.return_value = (None, [media])
        result = self.searcher.search_like_api("电影", 1)[0]
        self.assertEqual(result["media_source"], "themoviedb")
        self.assertEqual(result["media_id"], "42")
        self.assertEqual(result["tmdb_id"], 42)

    def test_empty_results_and_blank_title_keep_existing_behavior(self) -> None:
        """
        空关键词不搜索，宿主空结果仍返回空列表
        """
        self.assertEqual(self.searcher.search_like_api(" ", 10), [])
        self.search.assert_not_awaited()
        self.search.return_value = (None, [])
        self.assertEqual(self.searcher.search_like_api("电影", 10), [])
