"""
``app.sdk.utilities`` 替身。

真实宿主这里是**门面模块**，把散落在 ``app.foundation`` / ``app.adapters``
的实现重新导出。本替身只提供插件实际使用到的部分：

* ``StringUtils`` —— 插件只调用 ``str_filesize`` / ``num_filesize`` /
  ``format_ep`` / ``format_size``（这 4 个在 V3 宿主真实存在）
* ``SystemUtils`` —— ``copy`` / ``list_files`` / ``exits_files`` / ``cpu_arch``

实现直接对齐宿主语义，保证测试行为可信，而非简单地返回 Mock。
"""

import shutil
import platform
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

__all__ = [
    "StringUtils",
    "SystemUtils",
]


class StringUtils:
    """宿主 ``app.sdk.string.StringUtils`` 的等价子集替身。"""

    @staticmethod
    def str_filesize(size: Union[str, float, int], pre: int = 2) -> str:
        """把字节数格式化为人类可读字符串（默认保留 2 位小数）。"""
        try:
            value = float(size)
        except (TypeError, ValueError):
            return "0 B"
        if value < 0:
            return "0 B"
        suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]
        index = 0
        while value >= 1024 and index < len(suffixes) - 1:
            value /= 1024.0
            index += 1
        return f"{value:.{pre}f} {suffixes[index]}"

    @staticmethod
    def num_filesize(text: Union[str, int, float]) -> int:
        """把 ``"1.5GB"`` 这类文本解析为字节数。"""
        if isinstance(text, (int, float)):
            return int(text)
        if not text:
            return 0
        units = {
            "B": 1,
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
            "PB": 1024**5,
        }
        cleaned = str(text).strip().upper().replace(" ", "")
        for unit, multiplier in sorted(units.items(), key=lambda kv: -len(kv[0])):
            if cleaned.endswith(unit):
                number = cleaned[: -len(unit)]
                try:
                    return int(float(number) * multiplier)
                except ValueError:
                    return 0
        try:
            return int(float(cleaned))
        except ValueError:
            return 0

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """宿主同名方法：固定 2 位小数的尺寸格式化。"""
        return StringUtils.str_filesize(size_bytes, pre=2)

    @staticmethod
    def format_ep(nums: List[int]) -> str:
        """把集数列表压缩成 ``E01-03,E05`` 形式的区间表达式。"""
        if not nums:
            return ""
        ordered = sorted({int(n) for n in nums})
        ranges: List[str] = []
        start = prev = ordered[0]
        for current in ordered[1:]:
            if current == prev + 1:
                prev = current
                continue
            ranges.append(_format_range(start, prev))
            start = prev = current
        ranges.append(_format_range(start, prev))
        return ",".join(ranges)


def _format_range(start: int, end: int) -> str:
    """把一对起止集数格式化为区间字符串。"""
    width = max(2, len(str(end)))
    if start == end:
        return f"E{start:0{width}d}"
    return f"E{start:0{width}d}-{end:0{width}d}"


class SystemUtils:
    """宿主 ``app.adapters.system.host.SystemUtils`` 的等价子集替身。"""

    @staticmethod
    def copy(src: Path, dest: Path) -> Tuple[int, str]:
        """复制文件。返回 ``(retcode, errmsg)``，0 表示成功。"""
        try:
            shutil.copy2(src, dest)
            return 0, ""
        except Exception as err:  # noqa: BLE001 - 与宿主一致，宽捕获后回报错误串
            return 1, str(err)

    @staticmethod
    def list_files(
        directory: Path,
        extensions: Optional[list] = None,
        min_filesize: int = 0,
        recursive: bool = True,
    ) -> List[Path]:
        """列出目录下指定扩展名的文件。"""
        directory = Path(directory)
        if not directory.exists():
            return []
        pattern = "**/*" if recursive else "*"
        min_bytes = max(0, int(min_filesize)) * 1024 * 1024
        result: List[Path] = []
        for item in directory.glob(pattern):
            if not item.is_file():
                continue
            if extensions:
                suffix = item.suffix.lstrip(".").lower()
                if suffix not in [str(e).lower().lstrip(".") for e in extensions]:
                    continue
            if min_bytes and item.stat().st_size < min_bytes:
                continue
            result.append(item)
        return result

    @staticmethod
    def exits_files(
        directory: Path,
        extensions: list,
        min_filesize: int = 0,
        recursive: bool = True,
    ) -> bool:
        """判断目录下是否存在指定扩展名的文件。"""
        return bool(
            SystemUtils.list_files(
                directory=directory,
                extensions=extensions,
                min_filesize=min_filesize,
                recursive=recursive,
            )
        )

    @staticmethod
    def cpu_arch() -> str:
        """返回 CPU 架构标识。"""
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return "x86_64"
        if machine in ("aarch64", "arm64"):
            return "aarch64"
        if machine in ("i386", "i686", "x86"):
            return "x86_32"
        return machine

    @staticmethod
    def is_docker() -> bool:
        return False

    @staticmethod
    def is_windows() -> bool:
        return platform.system().lower() == "windows"

    @staticmethod
    def platform() -> str:
        return platform.system()
