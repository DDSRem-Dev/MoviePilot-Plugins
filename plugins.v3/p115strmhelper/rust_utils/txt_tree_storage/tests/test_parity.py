"""
txt_tree_storage Rust 模块 与 原 Python 实现 的行为一致性测试

运行方式（在本目录或 crate 根目录）：
    maturin develop
    pytest tests/test_parity.py -v

参考实现 (PyRef) 完整复刻 plugins.v2/p115strmhelper/utils/tree.py 中
TxtFileStorage 在重构前的行为，避免依赖 app.core / app.helper
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Iterable, List, Union

import pytest

import txt_tree_storage as rust_mod


# ---------------------------------------------------------------------------
# 参考实现：原 Python TxtFileStorage（不含 ABC 和 Redis 依赖）
# ---------------------------------------------------------------------------
class PyRef:
    def __init__(self, file_path: Union[str, Path]):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def add_paths(self, paths: Iterable[str], append: bool = False):
        mode = "a" if append else "w"
        buffer_size = 1048576
        with open(self.file_path, mode, encoding="utf-8", buffering=buffer_size) as f:
            f.writelines(f"{path}\n" for path in paths)

    def compare_trees(self, other: "PyRef") -> Generator[str, None, None]:
        try:
            with open(other.file_path, "r", encoding="utf-8") as f2:
                tree2_set = set(line.strip() for line in f2)
        except FileNotFoundError:
            tree2_set = set()
        with open(self.file_path, "r", encoding="utf-8") as f1:
            for line in f1:
                fp = line.strip()
                if fp not in tree2_set:
                    yield fp

    def compare_trees_lines(self, other: "PyRef") -> Generator[int, None, None]:
        try:
            with open(other.file_path, "r", encoding="utf-8") as f2:
                tree2_set = set(line.strip() for line in f2)
        except FileNotFoundError:
            tree2_set = set()
        with open(self.file_path, "r", encoding="utf-8") as f1:
            for line_num, line in enumerate(f1, start=1):
                fp = line.strip()
                if fp not in tree2_set:
                    yield line_num

    def get_path_by_line_number(self, line_number: int) -> Union[str, None]:
        if line_number <= 0:
            return None
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if i == line_number:
                        return line.strip()
        except FileNotFoundError:
            return None
        return None

    def count(self) -> int:
        cnt = 0
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        cnt += 1
        except FileNotFoundError:
            return 0
        return cnt

    def clear(self):
        if self.file_path.exists():
            self.file_path.unlink()


# ---------------------------------------------------------------------------
# Rust 适配器：把 rust_mod 的函数包装成与 PyRef 同样的接口
# ---------------------------------------------------------------------------
class RustImpl:
    def __init__(self, file_path: Union[str, Path]):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def add_paths(self, paths: Iterable[str], append: bool = False):
        rust_mod.add_paths(
            self.file_path,
            (p if isinstance(p, str) else str(p) for p in paths),
            append,
        )

    def compare_trees(self, other: "RustImpl"):
        return rust_mod.compare_trees(self.file_path, other.file_path)

    def compare_trees_lines(self, other: "RustImpl"):
        return rust_mod.compare_trees_lines(self.file_path, other.file_path)

    def get_path_by_line_number(self, line_number: int):
        return rust_mod.get_path_by_line_number(self.file_path, line_number)

    def count(self) -> int:
        return int(rust_mod.count(self.file_path))

    def clear(self):
        rust_mod.clear(self.file_path)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
@pytest.fixture
def pair(tmp_path: Path):
    """返回 (PyRef, RustImpl) 两个指向不同文件的 self 实例。"""
    return PyRef(tmp_path / "py_self.txt"), RustImpl(tmp_path / "rs_self.txt")


@pytest.fixture
def pair_other(tmp_path: Path):
    """返回 (PyRef, RustImpl) 两个指向不同文件的 other 实例。"""
    return PyRef(tmp_path / "py_other.txt"), RustImpl(tmp_path / "rs_other.txt")


def _seed(py: PyRef, rs: RustImpl, lines: List[str], append: bool = False):
    py.add_paths(lines, append=append)
    rs.add_paths(lines, append=append)


def _assert_files_equal(py: PyRef, rs: RustImpl):
    assert py.file_path.read_bytes() == rs.file_path.read_bytes()


# ---------------------------------------------------------------------------
# add_paths
# ---------------------------------------------------------------------------
class TestAddPaths:
    def test_basic_write(self, pair):
        py, rs = pair
        data = ["a/b.mkv", "a/c.mp4", "d/e.mkv"]
        _seed(py, rs, data)
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 3

    def test_overwrite_default(self, pair):
        py, rs = pair
        _seed(py, rs, ["x", "y"])
        _seed(py, rs, ["only"])  # 默认 append=False，应当覆盖
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 1

    def test_append_mode(self, pair):
        py, rs = pair
        _seed(py, rs, ["a", "b"])
        _seed(py, rs, ["c", "d"], append=True)
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 4

    def test_empty_iter(self, pair):
        py, rs = pair
        _seed(py, rs, [])
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 0

    def test_unicode_paths(self, pair):
        py, rs = pair
        data = ["电影/阿凡达 (2009).mkv", "动漫/进击的巨人/S01E01.mp4", "音乐/🎵.flac"]
        _seed(py, rs, data)
        _assert_files_equal(py, rs)

    def test_paths_with_spaces(self, pair):
        py, rs = pair
        data = ["a b/c d.mkv", "  leading.mkv", "trailing  .mkv"]
        _seed(py, rs, data)
        _assert_files_equal(py, rs)

    def test_very_long_path(self, pair):
        py, rs = pair
        long_seg = "x" * 500
        data = [f"{long_seg}/{long_seg}.mkv" for _ in range(50)]
        _seed(py, rs, data)
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 50

    def test_large_volume(self, pair):
        py, rs = pair
        data = [f"dir{i // 100}/file_{i}.mkv" for i in range(10_000)]
        _seed(py, rs, data)
        _assert_files_equal(py, rs)
        assert py.count() == rs.count() == 10_000

    def test_append_to_nonexistent(self, pair):
        py, rs = pair
        # 文件原本不存在，append 模式应该创建
        _seed(py, rs, ["a", "b"], append=True)
        _assert_files_equal(py, rs)


# ---------------------------------------------------------------------------
# compare_trees / compare_trees_lines
# ---------------------------------------------------------------------------
class TestCompareTrees:
    def test_basic_diff(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["a", "b", "c", "d"])
        _seed(py_o, rs_o, ["b", "d"])
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o))
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o))

    def test_identical(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        data = ["a", "b", "c"]
        _seed(py, rs, data)
        _seed(py_o, rs_o, data)
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o)) == []
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o)) == []

    def test_fully_disjoint(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["a", "b", "c"])
        _seed(py_o, rs_o, ["x", "y", "z"])
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o)) == ["a", "b", "c"]
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o)) == [1, 2, 3]

    def test_other_missing_file(self, pair, pair_other):
        """other 文件不存在时应等价于空集（self 全部为 diff）。"""
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["a", "b"])
        # 不写入 other —— PyRef.add_paths 不调用就不会创建文件
        # 但 fixture 已经 mkdir，所以确保文件不存在
        if py_o.file_path.exists():
            py_o.file_path.unlink()
        if rs_o.file_path.exists():
            rs_o.file_path.unlink()
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o)) == ["a", "b"]
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o)) == [1, 2]

    def test_self_missing_file_raises(self, pair, pair_other):
        """self 文件不存在时两边都应抛 FileNotFoundError（迭代时间点可能不同）。"""
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py_o, rs_o, ["a"])
        if py.file_path.exists():
            py.file_path.unlink()
        if rs.file_path.exists():
            rs.file_path.unlink()

        with pytest.raises(FileNotFoundError):
            list(py.compare_trees(py_o))
        with pytest.raises(FileNotFoundError):
            list(rs.compare_trees(rs_o))
        with pytest.raises(FileNotFoundError):
            list(py.compare_trees_lines(py_o))
        with pytest.raises(FileNotFoundError):
            list(rs.compare_trees_lines(rs_o))

    def test_duplicates_in_self(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["a", "a", "b", "a", "c"])
        _seed(py_o, rs_o, ["b"])
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o))
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o))

    def test_unicode_diff(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["电影/A.mkv", "动漫/B.mp4", "音乐/🎵.flac"])
        _seed(py_o, rs_o, ["动漫/B.mp4"])
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o))
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o))

    def test_large_diff(self, pair, pair_other):
        py, rs = pair
        py_o, rs_o = pair_other
        self_data = [f"f_{i}" for i in range(5000)]
        other_data = [f"f_{i}" for i in range(0, 5000, 2)]  # 偶数保留
        _seed(py, rs, self_data)
        _seed(py_o, rs_o, other_data)
        assert list(py.compare_trees(py_o)) == list(rs.compare_trees(rs_o))
        assert list(py.compare_trees_lines(py_o)) == list(rs.compare_trees_lines(rs_o))

    def test_iterator_protocol(self, pair, pair_other):
        """Rust 返回的对象是 self-iterator，单次消费（与 Python generator 一致）。"""
        py, rs = pair
        py_o, rs_o = pair_other
        _seed(py, rs, ["a", "b"])
        _seed(py_o, rs_o, [])
        it = rs.compare_trees(rs_o)
        assert iter(it) is it  # __iter__ 返回自身
        assert list(it) == ["a", "b"]
        # 二次消费应为空
        assert list(it) == []

        it2 = rs.compare_trees_lines(rs_o)
        assert iter(it2) is it2
        assert list(it2) == [1, 2]
        assert list(it2) == []


# ---------------------------------------------------------------------------
# get_path_by_line_number
# ---------------------------------------------------------------------------
class TestGetPathByLineNumber:
    def test_valid_lines(self, pair):
        py, rs = pair
        data = ["first", "second", "third"]
        _seed(py, rs, data)
        for n in (1, 2, 3):
            assert py.get_path_by_line_number(n) == rs.get_path_by_line_number(n)

    def test_zero_and_negative(self, pair):
        py, rs = pair
        _seed(py, rs, ["a"])
        for n in (0, -1, -100):
            assert py.get_path_by_line_number(n) == rs.get_path_by_line_number(n) is None

    def test_out_of_range(self, pair):
        py, rs = pair
        _seed(py, rs, ["a", "b"])
        for n in (3, 10, 100000):
            assert py.get_path_by_line_number(n) == rs.get_path_by_line_number(n) is None

    def test_missing_file(self, pair):
        py, rs = pair
        if py.file_path.exists():
            py.file_path.unlink()
        if rs.file_path.exists():
            rs.file_path.unlink()
        assert py.get_path_by_line_number(1) == rs.get_path_by_line_number(1) is None

    def test_empty_file(self, pair):
        py, rs = pair
        _seed(py, rs, [])
        assert py.get_path_by_line_number(1) == rs.get_path_by_line_number(1) is None

    def test_unicode_line(self, pair):
        py, rs = pair
        _seed(py, rs, ["普通", "电影/阿凡达.mkv", "🎬"])
        for n in (1, 2, 3):
            assert py.get_path_by_line_number(n) == rs.get_path_by_line_number(n)


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------
class TestCount:
    def test_normal(self, pair):
        py, rs = pair
        _seed(py, rs, ["a", "b", "c"])
        assert py.count() == rs.count() == 3

    def test_empty_file(self, pair):
        py, rs = pair
        _seed(py, rs, [])
        assert py.count() == rs.count() == 0

    def test_missing_file(self, pair):
        py, rs = pair
        if py.file_path.exists():
            py.file_path.unlink()
        if rs.file_path.exists():
            rs.file_path.unlink()
        assert py.count() == rs.count() == 0

    def test_skips_blank_lines(self, tmp_path):
        """count 跳过空白行——直接构造文件以包含空行。"""
        py_path = tmp_path / "py.txt"
        rs_path = tmp_path / "rs.txt"
        content = "a\n\nb\n   \nc\n\n"
        py_path.write_text(content, encoding="utf-8")
        rs_path.write_text(content, encoding="utf-8")
        py = PyRef(py_path)
        rs = RustImpl(rs_path)
        assert py.count() == rs.count() == 3


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------
class TestClear:
    def test_existing_file(self, pair):
        py, rs = pair
        _seed(py, rs, ["a"])
        assert py.file_path.exists() and rs.file_path.exists()
        py.clear()
        rs.clear()
        assert not py.file_path.exists()
        assert not rs.file_path.exists()

    def test_missing_file_no_error(self, pair):
        py, rs = pair
        if py.file_path.exists():
            py.file_path.unlink()
        if rs.file_path.exists():
            rs.file_path.unlink()
        # 两边都应静默成功
        py.clear()
        rs.clear()


# ---------------------------------------------------------------------------
# 随机化对拍 (fuzz)
# ---------------------------------------------------------------------------
class TestRandomizedParity:
    @pytest.mark.parametrize("seed", list(range(20)))
    def test_random_workload(self, tmp_path, seed):
        import random

        rng = random.Random(seed)
        py_self = PyRef(tmp_path / f"py_s_{seed}.txt")
        rs_self = RustImpl(tmp_path / f"rs_s_{seed}.txt")
        py_other = PyRef(tmp_path / f"py_o_{seed}.txt")
        rs_other = RustImpl(tmp_path / f"rs_o_{seed}.txt")

        def gen_path():
            depth = rng.randint(1, 4)
            parts = []
            for _ in range(depth):
                length = rng.randint(1, 8)
                parts.append("".join(rng.choice("abcdef电影动漫 _") for _ in range(length)))
            return "/".join(parts) + rng.choice([".mkv", ".mp4", ".flac", ""])

        self_data = [gen_path() for _ in range(rng.randint(0, 200))]
        other_data = [gen_path() for _ in range(rng.randint(0, 200))]
        # 故意混入 self 中的某些条目，增加交集
        if self_data:
            for _ in range(min(20, len(self_data))):
                other_data.append(rng.choice(self_data))

        _seed(py_self, rs_self, self_data)
        _seed(py_other, rs_other, other_data)

        _assert_files_equal(py_self, rs_self)
        _assert_files_equal(py_other, rs_other)

        assert py_self.count() == rs_self.count()
        assert py_other.count() == rs_other.count()

        assert list(py_self.compare_trees(py_other)) == list(
            rs_self.compare_trees(rs_other)
        )
        assert list(py_self.compare_trees_lines(py_other)) == list(
            rs_self.compare_trees_lines(rs_other)
        )

        # 抽几个行号交叉验证
        n = py_self.count()
        for ln in (0, 1, n // 2 if n else 1, n, n + 1, -3):
            assert py_self.get_path_by_line_number(ln) == rs_self.get_path_by_line_number(ln)
