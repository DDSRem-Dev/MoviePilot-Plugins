"""
``app.db.oper.transferhistory`` 替身。

宿主是写库的整理历史操作类；``db_manager/moviepilot_transfer.py`` 还会继承它
并调用 ``super().__init__()``。替身因此保证：可被继承、构造无副作用、
查询方法返回空结果、``add`` 返回可用的记录对象。
"""

from typing import Any, Dict, List, Optional

from ..models.transferhistory import TransferHistory

__all__ = ["TransferHistoryOper"]


class TransferHistoryOper:
    """整理历史管理替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        #: 进程内记录，便于测试注入与断言
        self._records: List[TransferHistory] = []

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, historyid: int) -> Optional[TransferHistory]:
        return next((r for r in self._records if r.id == historyid), None)

    def get_by_id(self, record_id: int) -> Optional[TransferHistory]:
        return self.get(record_id)

    def get_by_title(self, title: str) -> List[TransferHistory]:
        return [r for r in self._records if r.title == title]

    def get_by_src(self, src: str, storage: Optional[str] = None) -> Optional[TransferHistory]:
        return next((r for r in self._records if r.src == src), None)

    def get_by_dest(self, dest: str, storage: Optional[str] = None) -> Optional[TransferHistory]:
        return next((r for r in self._records if r.dest == dest), None)

    def get_by_transfer_task_id(self, transfer_task_id: str) -> Optional[TransferHistory]:
        return next(
            (r for r in self._records if r.transfer_task_id == transfer_task_id), None
        )

    def get_success_by_src(self, src: str, storage: Optional[str] = None):
        return next((r for r in self._records if r.src == src and r.status), None)

    def list_success_by_src(self, src: str, storage: Optional[str] = None) -> List[TransferHistory]:
        return [r for r in self._records if r.src == src and r.status]

    def list_success_move_by_dest(self, dest: str, storage: Optional[str] = None) -> List[TransferHistory]:
        return [r for r in self._records if r.dest == dest and r.status]

    def list_by_hash(self, download_hash: str) -> List[TransferHistory]:
        return [r for r in self._records if r.download_hash == download_hash]

    def get_by_media_identity(
        self, media_source: Optional[str] = None, media_id: Optional[str] = None
    ) -> Optional[TransferHistory]:
        return next(
            (
                r
                for r in self._records
                if r.media_source == media_source and r.media_id == media_id
            ),
            None,
        )

    def query(self, *args: Any, **kwargs: Any):
        """分页查询替身：返回 ``(记录列表, 总数)``。"""
        return list(self._records), len(self._records)

    async def async_list_by_title(self, *args: Any, **kwargs: Any):
        return []

    async def async_count(self, status: Optional[bool] = None) -> Optional[int]:
        return len(self._records)

    async def async_get_by_transfer_task_id(self, transfer_task_id: str):
        return self.get_by_transfer_task_id(transfer_task_id)

    def statistic(self, days: int = 7) -> List[Any]:
        return []

    # ------------------------------------------------------------------
    # 写入 / 删除
    # ------------------------------------------------------------------
    def add(self, **kwargs: Any) -> TransferHistory:
        """新增历史记录。"""
        record = TransferHistory(**kwargs)
        self._records.append(record)
        return record

    def delete(self, historyid: int) -> bool:
        """按 ID 删除历史记录。"""
        before = len(self._records)
        self._records = [r for r in self._records if r.id != historyid]
        return len(self._records) != before

    def truncate(self) -> None:
        self._records.clear()

    # ------------------------------------------------------------------
    # 供测试注入
    # ------------------------------------------------------------------
    def _seed(self, records: List[TransferHistory]) -> None:
        self._records.extend(records)
