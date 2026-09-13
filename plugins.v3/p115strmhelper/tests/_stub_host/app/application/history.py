"""
``app.application.history`` 替身：整理历史落库入口。

真实宿主依赖 ``TransferHistoryOper`` 写库。替身只记录调用（便于测试断言），
并返回一个轻量的快照对象。
"""

from typing import Any, Optional

__all__ = [
    "TransferHistorySnapshot",
    "add_transfer_success",
    "add_transfer_fail",
    "recorded_history",
    "clear_history",
]


class TransferHistorySnapshot:
    """整理历史快照替身。"""

    def __init__(self, **kwargs: Any) -> None:
        self.id: int = kwargs.pop("id", 0)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **_kwargs) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def __repr__(self) -> str:
        return f"TransferHistorySnapshot(id={self.id}, mode={getattr(self, 'mode', None)!r})"


#: 替身记录的调用流水
_RECORDS: list = []


def recorded_history() -> list:
    """测试辅助：读取已记录的历史调用。"""
    return list(_RECORDS)


def clear_history() -> None:
    """测试辅助：清空记录。"""
    _RECORDS.clear()


def add_transfer_success(
    fileitem: Any,
    mode: str,
    meta: Any,
    mediainfo: Any,
    transferinfo: Any,
    downloader: Optional[str] = None,
    download_hash: Optional[str] = None,
    transfer_history_oper: Optional[Any] = None,
) -> TransferHistorySnapshot:
    """新增整理成功历史。替身记录后返回快照。"""
    snapshot = TransferHistorySnapshot(
        id=len(_RECORDS) + 1,
        mode=mode,
        src=getattr(fileitem, "path", None),
        downloader=downloader,
        download_hash=download_hash,
        status="success",
    )
    _RECORDS.append(snapshot)
    return snapshot


def add_transfer_fail(
    fileitem: Any,
    mode: str,
    meta: Any,
    mediainfo: Optional[Any] = None,
    transferinfo: Optional[Any] = None,
    downloader: Optional[str] = None,
    download_hash: Optional[str] = None,
    retry_count: Optional[int] = None,
    auto_paused: bool = False,
    transfer_history_oper: Optional[Any] = None,
) -> TransferHistorySnapshot:
    """新增整理失败历史。替身记录后返回快照。"""
    snapshot = TransferHistorySnapshot(
        id=len(_RECORDS) + 1,
        mode=mode,
        src=getattr(fileitem, "path", None),
        downloader=downloader,
        download_hash=download_hash,
        retry_count=retry_count,
        auto_paused=auto_paused,
        status="fail",
    )
    _RECORDS.append(snapshot)
    return snapshot
