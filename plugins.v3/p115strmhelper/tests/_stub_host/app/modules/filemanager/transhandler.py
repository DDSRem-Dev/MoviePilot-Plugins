"""
``app.modules.filemanager.transhandler`` 替身。

``TransHandler`` 是整理的核心执行器。补丁通过
``getattr(TransHandler, "_TransHandler__rename_subtitles", None)`` 探测字幕重命名
私有方法是否存在——替身**提供**该方法，用于验证「宿主具备该能力」的正向路径。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["TransHandler"]

_HOST_MODULE = "app.modules.filemanager.transhandler"


class TransHandler:
    """文件转移整理类替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._plan: List[Any] = []

    # ------------------------------------------------------------------
    # 补丁会探测的私有方法
    # ------------------------------------------------------------------
    def _TransHandler__rename_subtitles(
        self,
        target_path: Path,
        meta: Any = None,
        mediainfo: Any = None,
    ) -> Optional[List[str]]:
        """重命名字幕文件（宿主私有方法替身）。"""
        return []

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def transfer_media(
        self,
        fileitem: Any = None,
        meta: Any = None,
        mediainfo: Any = None,
        target_directory: Any = None,
        **kwargs: Any,
    ) -> Optional[Any]:
        """整理媒体文件。替身返回 ``None``（未产生结果）。"""
        return None

    def plan_transfer(self, *args: Any, **kwargs: Any) -> List[Any]:
        return []

    def execute_transfer_plan(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def get_dest_path(
        self,
        fileitem: Any = None,
        meta: Any = None,
        mediainfo: Any = None,
        target_directory: Any = None,
        **kwargs: Any,
    ) -> Optional[Path]:
        """计算目标路径。替身返回 ``None``。"""
        return None

    def get_dest_dir(self, *args: Any, **kwargs: Any) -> Optional[Path]:
        return None

    def get_naming_dict(
        self, meta: Any = None, mediainfo: Any = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """构建命名模板字典。"""
        return {
            "title": getattr(mediainfo, "title", None) or getattr(meta, "title", None),
            "year": getattr(mediainfo, "year", None) or getattr(meta, "year", None),
            "season": getattr(meta, "begin_season", None) or getattr(meta, "season", None),
            "episode": getattr(meta, "begin_episode", None) or getattr(meta, "episode", None),
        }

    def get_rename_path(
        self,
        fileitem: Any = None,
        meta: Any = None,
        mediainfo: Any = None,
        **kwargs: Any,
    ) -> Optional[Tuple[Path, str]]:
        return None


for _name in ("_TransHandler__rename_subtitles", "transfer_media", "get_dest_path"):
    getattr(TransHandler, _name).__module__ = _HOST_MODULE
del _name
