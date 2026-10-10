from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Sequence, Tuple, Union

from ._share_strm_scan import (  # type: ignore[import-untyped]
    __version__,
    scan_share_strm_index,
    scan_share_strm_pairs,
)

RootKey = Union[str, Path]
Pair = Tuple[str, str]


def _normalize_root(root: RootKey) -> str:
    """
    将根目录规范化为绝对路径字符串，用作缓存键
    """
    return str(Path(root).resolve())


class ShareStrmScanCache:
    """
    扫描本地目录下分享 STRM，支持信息组与路径互查及内存缓存
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_root: Dict[str, Tuple[List[Pair], Dict[Pair, List[str]]]] = {}

    def _ensure_index(
        self,
        root: RootKey,
        max_file_bytes: int = 262_144,
        num_threads: Optional[int] = None,
    ) -> Tuple[List[Pair], Dict[Pair, List[str]]]:
        key = _normalize_root(root)
        with self._lock:
            hit = self._by_root.get(key)
            if hit is not None:
                return hit
        pairs, pair_to_paths = scan_share_strm_index(
            key,
            max_file_bytes=max_file_bytes,
            num_threads=num_threads,
        )
        with self._lock:
            self._by_root[key] = (pairs, pair_to_paths)
            return self._by_root[key]

    def scan(
        self,
        root: RootKey,
        *,
        max_file_bytes: int = 262_144,
        num_threads: Optional[int] = None,
    ) -> List[Pair]:
        """
        扫描 ``root`` 下所有 ``.strm``，返回去重排序后的信息组列表并更新缓存

        :param root: 扫描根目录
        :param max_file_bytes: 每个 strm 文件最多读取字节数
        :param num_threads: Rayon 线程数；``None`` 使用 Rayon 默认
        :return: ``(share_code, receive_code)`` 列表
        """
        pairs, _ = self._ensure_index(root, max_file_bytes, num_threads)
        return list(pairs)

    def pairs(
        self,
        root: RootKey,
        *,
        max_file_bytes: int = 262_144,
        num_threads: Optional[int] = None,
    ) -> List[Pair]:
        """
        与 ``scan`` 相同，便于命名对齐「仅要信息组列表」的调用方
        """
        return self.scan(root, max_file_bytes=max_file_bytes, num_threads=num_threads)

    def paths_for(
        self,
        root: RootKey,
        share_code: str,
        receive_code: str,
        *,
        max_file_bytes: int = 262_144,
        num_threads: Optional[int] = None,
    ) -> List[str]:
        """
        返回包含该信息组的 ``.strm`` 文件路径列表；无缓存时先扫描再查表
        """
        _, pair_to_paths = self._ensure_index(root, max_file_bytes, num_threads)
        return list(pair_to_paths.get((share_code, receive_code), []))

    def paths_for_many(
        self,
        root: RootKey,
        pairs: Sequence[Pair],
        *,
        max_file_bytes: int = 262_144,
        num_threads: Optional[int] = None,
    ) -> Dict[Pair, List[str]]:
        """
        一次查询多组信息组的路径；返回 dict 的 key 与输入中**唯一**键一致（首次出现顺序）

        索引中不存在的组对应空列表
        """
        _, pair_to_paths = self._ensure_index(root, max_file_bytes, num_threads)
        out: Dict[Pair, List[str]] = {}
        seen: set[Pair] = set()
        for p in pairs:
            if p in seen:
                continue
            seen.add(p)
            out[p] = list(pair_to_paths.get(p, []))
        return out

    def invalidate(self, root: Optional[RootKey] = None) -> None:
        """
        使缓存失效；``root`` 为 ``None`` 时清空全部，否则只移除该根目录
        """
        with self._lock:
            if root is None:
                self._by_root.clear()
            else:
                self._by_root.pop(_normalize_root(root), None)


__all__: List[str] = [
    "Pair",
    "RootKey",
    "ShareStrmScanCache",
    "__version__",
    "scan_share_strm_index",
    "scan_share_strm_pairs",
]
