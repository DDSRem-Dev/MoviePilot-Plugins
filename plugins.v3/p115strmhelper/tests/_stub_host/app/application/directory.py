"""
``app.application.directory`` 替身。

真实宿主是下载/媒体库目录解析器，依赖系统配置。替身在无配置环境下返回空
结果，并支持通过 :func:`set_media_root_path` 注入确定值以便测试。
"""

from pathlib import Path
from typing import Any, List, Optional

__all__ = ["DirectoryHelper"]

#: 测试可注入的媒体库根路径
_MEDIA_ROOT_PATH: Optional[Path] = None


def set_media_root_path(path: Optional[Path]) -> None:
    """测试辅助：设置 ``get_media_root_path`` 的返回值。"""
    global _MEDIA_ROOT_PATH
    _MEDIA_ROOT_PATH = Path(path) if path is not None else None


class DirectoryHelper:
    """下载目录 / 媒体库目录帮助类替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @staticmethod
    def get_dirs() -> List[Any]:
        """获取所有目录配置。替身环境无配置，返回空列表。"""
        return []

    def get_download_dirs(self) -> List[Any]:
        return [d for d in self.get_dirs() if getattr(d, "download_path", None)]

    def get_local_download_dirs(self) -> List[Any]:
        return [
            d for d in self.get_download_dirs() if getattr(d, "storage", None) in (None, "local")
        ]

    @staticmethod
    def get_media_root_path() -> Path:
        """获取媒体库根路径。

        替身默认返回临时目录下的稳定路径；测试可用
        :func:`set_media_root_path` 覆盖。
        """
        if _MEDIA_ROOT_PATH is not None:
            return _MEDIA_ROOT_PATH
        from tempfile import gettempdir

        return Path(gettempdir()) / "v3-stub-media"

    @staticmethod
    def get_library_dirs() -> List[Any]:
        return []
