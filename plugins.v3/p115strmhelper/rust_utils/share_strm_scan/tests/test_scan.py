from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import share_strm_scan as rust_mod
from share_strm_scan import ShareStrmScanCache, scan_share_strm_index


class TestShareStrmScan(unittest.TestCase):
    """
    `share_strm_scan.scan_share_strm_pairs` 行为测试
    """

    def test_scan_nested_dedup_and_non_share_strm(self) -> None:
        """
        子目录、多文件、重复 URL 与仅 pickcode 的 STRM 混合场景

        断言仅解析出唯一一组 `(share_code, receive_code)`，且非分享 STRM 不产生条目
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "media"
            d.mkdir()
            sub = d / "a"
            sub.mkdir()
            url = (
                "http://127.0.0.1:3000/api/v1/plugin/P115StrmHelper/redirect_url"
                "?share_code=sc1&receive_code=r1&id=99"
            )
            (sub / "a.strm").write_text(url + "\n", encoding="utf-8")
            (sub / "dup.strm").write_text(url + "\n", encoding="utf-8")
            (d / "pick.strm").write_text(
                "http://x/api/v1/plugin/P115StrmHelper/redirect_url?pickcode=abc\n",
                encoding="utf-8",
            )
            pairs = set(rust_mod.scan_share_strm_pairs(str(root)))
            self.assertEqual(pairs, {("sc1", "r1")})

    def test_multiline_two_pairs(self) -> None:
        """
        单文件内多行 URL，每行一组 `share_code` / `receive_code`

        断言去重后得到两组不同码对
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = (
                "http://h/api/v1/plugin/P115StrmHelper/r"
                "?share_code={sc}&receive_code={rc}"
            )
            body = base.format(sc="a", rc="b") + "\n" + base.format(sc="c", rc="d")
            (root / "m.strm").write_text(body, encoding="utf-8")
            pairs = set(rust_mod.scan_share_strm_pairs(str(root)))
            self.assertEqual(pairs, {("a", "b"), ("c", "d")})

    def test_version(self) -> None:
        """
        模块暴露 `__version__` 且非空
        """
        self.assertTrue(hasattr(rust_mod, "__version__"))
        self.assertTrue(rust_mod.__version__)


class TestScanShareStrmIndex(unittest.TestCase):
    """
    `scan_share_strm_index` 返回 pairs 与 pair -> paths 映射
    """

    def test_index_two_paths_one_pair(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "media" / "a"
            sub.mkdir(parents=True)
            url = (
                "http://127.0.0.1:3000/api/v1/plugin/P115StrmHelper/redirect_url"
                "?share_code=sc1&receive_code=r1&id=99"
            )
            (sub / "a.strm").write_text(url + "\n", encoding="utf-8")
            (sub / "dup.strm").write_text(url + "\n", encoding="utf-8")
            pairs, pair_to_paths = scan_share_strm_index(str(root))
            self.assertEqual(pairs, [("sc1", "r1")])
            paths = pair_to_paths[("sc1", "r1")]
            self.assertEqual(len(paths), 2)
            self.assertEqual({Path(p).name for p in paths}, {"a.strm", "dup.strm"})


class TestShareStrmScanCache(unittest.TestCase):
    """
    `ShareStrmScanCache` 缓存与 `paths_for` / `paths_for_many` / `invalidate`
    """

    def test_paths_for_without_prior_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            url = (
                "http://h/api/v1/plugin/P115StrmHelper/r?share_code=aa&receive_code=bb"
            )
            (root / "one.strm").write_text(url + "\n", encoding="utf-8")
            cache = ShareStrmScanCache()
            paths = cache.paths_for(root, "aa", "bb")
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith("one.strm"))

    def test_paths_for_many_and_missing_pair(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            u1 = "http://h/api/v1/plugin/P115StrmHelper/r?share_code=a&receive_code=b"
            u2 = "http://h/api/v1/plugin/P115StrmHelper/r?share_code=c&receive_code=d"
            (root / "x.strm").write_text(u1 + "\n" + u2 + "\n", encoding="utf-8")
            cache = ShareStrmScanCache()
            got = cache.paths_for_many(
                root,
                [
                    ("a", "b"),
                    ("a", "b"),
                    ("c", "d"),
                    ("missing", "pair"),
                ],
            )
            self.assertEqual(
                list(got.keys()), [("a", "b"), ("c", "d"), ("missing", "pair")]
            )
            self.assertEqual(len(got[("a", "b")]), 1)
            self.assertEqual(got[("missing", "pair")], [])

    def test_invalidate_then_paths_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            url = "http://h/api/v1/plugin/P115StrmHelper/r?share_code=z&receive_code=w"
            (root / "z.strm").write_text(url + "\n", encoding="utf-8")
            cache = ShareStrmScanCache()
            before = cache.paths_for(root, "z", "w")
            self.assertEqual(len(before), 1)
            cache.invalidate(root)
            after = cache.paths_for(root, "z", "w")
            self.assertEqual(len(after), 1)
            self.assertEqual(Path(before[0]).name, Path(after[0]).name)


if __name__ == "__main__":
    unittest.main()
