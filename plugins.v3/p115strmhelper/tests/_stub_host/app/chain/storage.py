"""``app.chain.storage`` 替身。"""

from typing import Any, Dict, List, Optional

from .base import ChainBase

__all__ = ["StorageChain"]


class StorageChain(ChainBase):
    """存储处理链替身。"""

    def list_files(self, fileitem: Any, recursion: bool = False) -> Optional[List[Any]]:
        """列出文件。替身返回空列表。"""
        return []

    def get_file_item(self, storage: str, path: Any) -> Optional[Any]:
        """按路径取文件条目。替身返回 ``None``。"""
        return None

    def get_parent_item(self, fileitem: Any) -> Optional[Any]:
        """取父目录条目。替身返回 ``None``。"""
        return None

    def delete_file(self, fileitem: Any) -> bool:
        """删除文件。替身返回 True。"""
        return True

    def delete_media_file(self, fileitem: Any) -> bool:
        """删除媒体文件。替身返回 True。"""
        return True

    def manage_storage(self, storage: str, action: str, **params: Any) -> Dict[str, Any]:
        """存储管理动作。替身返回成功占位。"""
        return {"success": True, "message": "stub", "data": None}
