"""
Chain 基类替身。

真实宿主中 ``ChainBase`` 由多个 mixin 组合而成（识别、消息、通知等），并持有
大量运行时 provider。替身按插件**实际访问到的成员**提供等价面：

* 自身方法：``recognize_by_meta`` / ``recognize_media`` / ``async_search`` /
  ``post_message`` / ``send_transfer_message``
* 惰性属性：``storage`` / ``media`` / ``tmdb`` / ``transfer``，返回共享单例
* ``jobview``：委托给 ``TransferChain``，供补丁路径使用

所有业务方法默认返回「空结果」而不是抛异常，保证补丁逻辑能在测试里走通。
"""

from typing import Any, Dict, List, Optional

__all__ = ["ChainBase"]


class ChainBase:
    """处理链基类替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._storage: Any = None
        self._media: Any = None
        self._tmdb: Any = None
        self._transfer: Any = None

    # ------------------------------------------------------------------
    # 惰性组件
    # ------------------------------------------------------------------
    @property
    def storage(self):
        """存储链单例。"""
        if self._storage is None:
            from .storage import StorageChain

            self._storage = StorageChain()
        return self._storage

    @property
    def media(self):
        """媒体链单例。"""
        if self._media is None:
            from .media import MediaChain

            self._media = MediaChain()
        return self._media

    @property
    def tmdb(self):
        """TMDB 链单例。"""
        if self._tmdb is None:
            from .tmdb import TmdbChain

            self._tmdb = TmdbChain()
        return self._tmdb

    @property
    def transfer(self):
        """整理链单例。"""
        if self._transfer is None:
            from .transfer import TransferChain

            self._transfer = TransferChain()
        return self._transfer

    @property
    def jobview(self):
        """整理任务视图（V3 中由 TransferChain 持有）。"""
        return self.transfer.jobview

    @property
    def retry_scheduler(self):
        """重试调度器替身。"""
        return None

    # ------------------------------------------------------------------
    # 业务方法（替身返回空结果）
    # ------------------------------------------------------------------
    def recognize_by_meta(self, meta: Any) -> Optional[Any]:
        """按识别元数据查找媒体信息。替身返回 ``None``。"""
        return None

    def recognize_media(
        self, mediainfo: Any = None, mtype: Any = None, **kwargs: Any
    ) -> Optional[Any]:
        """刮削媒体信息。替身原样回传入参。"""
        return mediainfo

    def async_search(self, *args: Any, **kwargs: Any) -> List[Any]:
        """异步搜索。替身返回空列表。"""
        return []

    def post_message(self, *args: Any, **kwargs: Any) -> bool:
        """发送通知消息。替身记录后返回 True。"""
        return True

    def send_transfer_message(self, *args: Any, **kwargs: Any) -> bool:
        """发送整理完成消息。替身返回 True。"""
        return True

    # ------------------------------------------------------------------
    # 存储相关透传（补丁里会经 chain 调用）
    # ------------------------------------------------------------------
    def get_file_item(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def get_parent_item(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def list_files(self, *args: Any, **kwargs: Any) -> Optional[List[Any]]:
        return None

    def create_folder(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def delete_file(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def delete_media_file(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def is_bluray_folder(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def do_transfer(self, *args: Any, **kwargs: Any):
        return None, "stub"

    #: 补丁会读取该私有属性，替身给出空集合
    _success_target_files: Dict[str, Any] = {}
