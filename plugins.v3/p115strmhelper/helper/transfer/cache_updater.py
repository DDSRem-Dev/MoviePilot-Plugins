from typing import Optional, TYPE_CHECKING, Any

from app.sdk.logging import logger
from app.schemas import FileItem

if TYPE_CHECKING:
    from ....p115disk.p115_api import P115Api
else:
    P115Api = Any


class CacheUpdater:
    """
    115 网盘缓存更新器
    """

    def __init__(self, p115_api: Optional["P115Api"] = None) -> None:
        """
        初始化缓存更新器

        :param p115_api (P115Api): P115Api 实例
        """
        self._p115_api = p115_api

    def update_file_cache(self, file_item: FileItem) -> None:
        """
        更新文件缓存

        :param file_item (FileItem): 文件项
        """
        if not self._p115_api or not file_item or not file_item.fileid:
            return
        try:
            if hasattr(self._p115_api, "_id_cache"):
                self._p115_api._id_cache.add_cache(
                    id=int(file_item.fileid),
                    directory=file_item.path,
                )
            if hasattr(self._p115_api, "_id_item_cache"):
                self._p115_api._id_item_cache.add_cache(
                    id=int(file_item.fileid),
                    item={
                        "path": file_item.path,
                        "id": file_item.fileid,
                        "size": file_item.size or 0,
                        "modify_time": file_item.modify_time or 0,
                        "pickcode": file_item.pickcode or "",
                        "is_dir": False,
                    },
                )
        except Exception as e:
            logger.debug(f"【整理接管】更新文件缓存失败: {e}")

    def remove_cache(self, file_id: int) -> None:
        """
        删除缓存

        :param file_id (int): 文件ID
        """
        if not self._p115_api:
            return
        try:
            if hasattr(self._p115_api, "_id_cache"):
                self._p115_api._id_cache.remove(id=file_id)
            if hasattr(self._p115_api, "_id_item_cache"):
                self._p115_api._id_item_cache.remove(file_id)
        except Exception as e:
            logger.debug(f"【整理接管】删除缓存失败: {e}")
