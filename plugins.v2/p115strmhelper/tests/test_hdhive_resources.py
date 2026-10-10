"""
RE0 页面资源数据与分享地址回归测试
"""

from json import dumps
from typing import Any, Dict
from unittest import TestCase

from utils.hdhive import (
    extract_hdhive_page_resources,
    extract_hdhive_resource_rows,
    extract_hdhive_resource_slug,
    is_hdhive_share_url,
)


def _resource(**overrides: Any) -> Dict[str, Any]:
    return {
        "slug": "sample-resource",
        "website": "115",
        "title": "测试电影",
        "remark": "4K REMUX 简英双语",
        "unlock_points": 8,
        "share_size": "67.75GB",
        "video_resolution": ["4K"],
        "source": ["蓝光原盘/REMUX"],
        "subtitle_language": ["简英双语"],
        "subtitle_type": ["内封"],
        "submitted_at": "2026-08-27 14:49:37",
        "user": {"nickname": "分享者"},
        **overrides,
    }


def _page_record(groups: object) -> str:
    return (
        "1:"
        + dumps(["$", "$L56", None, {"groupData": groups}], ensure_ascii=False)
        + "\n"
    )


class TestRE0PageResources(TestCase):
    """
    测试页面分片解析和网盘过滤
    """

    def test_split_chunks_keep_metadata_and_filter_ed2k(self) -> None:
        """
        跨分片的数据正确拼接，115 分组内的 ED2K 也必须剔除
        """
        resource = _resource()
        payload = _page_record(
            {
                "115": [resource, _resource(website="ed2k")],
                "123": [_resource(website="123")],
            }
        )
        rows = extract_hdhive_page_resources(
            [payload[:21], payload[21:100], payload[100:]]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["href"], "/resource/115/sample-resource")
        self.assertEqual(rows[0]["title"], "4K REMUX 简英双语")
        self.assertEqual(rows[0]["user"], "分享者")
        self.assertEqual(rows[0]["size"], "67.75GB")
        self.assertEqual(rows[0]["source"], ["蓝光原盘/REMUX"])
        self.assertEqual(rows[0]["subtitle_language"], ["简英双语"])
        self.assertEqual(rows[0]["unlock_points"], 8)

    def test_null_points_are_free(self) -> None:
        """
        新站将空积分显示为免费，不能显示为未知价格
        """
        rows = extract_hdhive_page_resources(
            [_page_record({"115": [_resource(unlock_points=None)]})]
        )
        self.assertEqual(rows[0]["unlock_points"], 0)
        self.assertTrue(rows[0]["is_free"])

    def test_resolves_resource_and_user_references(self) -> None:
        """
        支持分组、条目和分享者引用其他数据行
        """
        chunks = [
            _page_record("$a"),
            'a:{"115":"$b"}\n',
            'b:["$c"]\n',
            "c:" + dumps(_resource(user="$d")) + "\n",
            'd:{"nickname":"author"}\n',
        ]
        rows = extract_hdhive_page_resources(chunks)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user"], "author")

    def test_missing_data_is_distinct_from_no_resources(self) -> None:
        """
        页面未加载和真实空列表必须区分，避免误报没有资源
        """
        self.assertIsNone(extract_hdhive_page_resources([]))
        self.assertIsNone(extract_hdhive_page_resources(["1:invalid\n"]))
        self.assertEqual(extract_hdhive_page_resources([_page_record({})]), [])
        self.assertEqual(extract_hdhive_page_resources([_page_record({"115": []})]), [])
        self.assertIsNone(
            extract_hdhive_page_resources([_page_record({"115": "$dead"})])
        )

    def test_circular_reference_does_not_recurse_forever(self) -> None:
        """
        循环数据引用不能阻塞搜索
        """
        self.assertIsNone(
            extract_hdhive_page_resources([_page_record("$a"), 'a:"$b"\nb:"$a"\n'])
        )

    def test_pending_rows_do_not_return_empty_or_partial_results(self) -> None:
        """
        资源条目分片未到齐时继续等待，不能漏掉后到资源
        """
        for items in (["$c"], [_resource(), "$c"]):
            with self.subTest(items=items):
                chunks = [_page_record({"115": items})]
                self.assertIsNone(extract_hdhive_page_resources(chunks))
                chunks.append("c:" + dumps(_resource(slug="second")) + "\n")
                self.assertEqual(len(extract_hdhive_page_resources(chunks)), len(items))

    def test_pending_metadata_waits_but_other_providers_do_not_block(self) -> None:
        """
        等待 115 的价格与作者分片，不等待已排除网盘的数据
        """
        chunks = [
            _page_record(
                {
                    "115": [
                        _resource(unlock_points="$a"),
                        _resource(website="ed2k", user="$b"),
                    ]
                }
            )
        ]
        self.assertIsNone(extract_hdhive_page_resources(chunks))
        chunks.append("a:6\n")
        rows = extract_hdhive_page_resources(chunks)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unlock_points"], 6)

    def test_deduplicates_and_rejects_invalid_resources(self) -> None:
        """
        仅保留有效的 115 资源并按 slug 去重
        """
        rows = extract_hdhive_resource_rows(
            {
                "data": [
                    _resource(),
                    _resource(),
                    _resource(website="ed2k"),
                    _resource(slug="../escape"),
                    {"slug": "not-a-resource"},
                    {"href": "/resource/123/another"},
                    {"href": "https://evil.example/resource/115/another"},
                ]
            }
        )
        self.assertEqual(len(rows), 1)

    def test_empty_remark_uses_title_and_unknown_price_stays_unknown(self) -> None:
        """
        缺少备注时使用片名，异常积分不应误标免费
        """
        row = extract_hdhive_resource_rows(
            {"data": [_resource(remark=None, unlock_points="unknown")]}
        )[0]
        self.assertEqual(row["title"], "测试电影")
        self.assertIsNone(row["unlock_points"])
        self.assertFalse(row["is_free"])


class TestRE0ResourceURLs(TestCase):
    """
    测试资源 slug 与 115 分享地址边界
    """

    def test_resource_slug_ignores_query_and_fragment(self) -> None:
        """
        新站 from 参数不能混入资源 slug
        """
        for href in (
            "/resource/115/abc-def?from=%2Fmovie%2F123#details",
            "https://re0.me/resource/115/abc-def/",
            "https://hdhive.com/resource/115/abc-def",
        ):
            with self.subTest(href=href):
                self.assertEqual(extract_hdhive_resource_slug(href), "abc-def")

    def test_rejects_foreign_and_non_115_resource_links(self) -> None:
        """
        其他网盘和伪造来源不能用于解锁
        """
        for href in (
            "https://evil.example/resource/115/abc",
            "/resource/123/abc",
            "/resource/abc",
            "/resource/115/%2fescape",
        ):
            with self.subTest(href=href):
                self.assertIsNone(extract_hdhive_resource_slug(href))

    def test_share_url_preserves_password(self) -> None:
        """
        支持新旧分享域名和提取码参数
        """
        for host in ("115.com", "115cdn.com", "anxia.com"):
            self.assertTrue(
                is_hdhive_share_url(f"https://{host}/s/example?password=1122")
            )

    def test_rejects_substring_domain_and_unrelated_pages(self) -> None:
        """
        域名包含 115 字样或非分享页面不能被当成解锁成功
        """
        for value in (
            None,
            "https://115cdn.com.evil.example/s/code",
            "https://evil.example/115.com/s/code",
            "https://115.com/",
            "https://115.com/s/",
            "https://115.com/s/code/extra",
            "https://user@115.com/s/code",
            "https://re0.me/resource/115/code",
            "javascript:https://115.com/s/code",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_hdhive_share_url(value))
