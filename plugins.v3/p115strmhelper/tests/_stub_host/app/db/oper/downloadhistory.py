"""
``app.db.oper.downloadhistory`` 替身。

插件用它把「下载器文件」与「种子 hash」互相映射。替身维护进程内的
``DownloadHistory`` / ``DownloadFiles`` 记录，支持完整的增删查。
"""

from typing import Any, Dict, List, Optional

from ..models.transferhistory import DownloadFiles, DownloadHistory

__all__ = ["DownloadHistoryOper"]


class DownloadHistoryOper:
    """下载历史管理替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._records: List[DownloadHistory] = []
        self._files: List[DownloadFiles] = []

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_by_id(self, record_id: int) -> Optional[DownloadHistory]:
        return next((r for r in self._records if r.id == record_id), None)

    def get_by_path(self, path: str) -> Optional[DownloadHistory]:
        return next((r for r in self._records if r.path == path), None)

    def get_by_hash(self, download_hash: str) -> Optional[DownloadHistory]:
        return next((r for r in self._records if r.download_hash == download_hash), None)

    def get_by_hashes(self, download_hashes: List[str]) -> Dict[str, DownloadHistory]:
        wanted = set(download_hashes or [])
        return {
            r.download_hash: r for r in self._records if r.download_hash in wanted
        }

    def get_by_media_identity(
        self, media_source: Optional[str] = None, media_id: Optional[str] = None
    ) -> Optional[DownloadHistory]:
        return next(
            (
                r
                for r in self._records
                if r.media_source == media_source and r.media_id == media_id
            ),
            None,
        )

    def query(self, *args: Any, **kwargs: Any):
        return list(self._records), len(self._records)

    def list_by_page(self, page: int = 1, count: int = 30) -> List[DownloadHistory]:
        start = max(0, (page - 1) * count)
        return self._records[start : start + count]

    # ------------------------------------------------------------------
    # 文件记录
    # ------------------------------------------------------------------
    def get_files_by_hash(
        self, download_hash: str, state: Optional[int] = None
    ) -> List[DownloadFiles]:
        return [
            f
            for f in self._files
            if f.download_hash == download_hash and (state is None or f.state == state)
        ]

    def get_file_by_fullpath(self, fullpath: str) -> Optional[DownloadFiles]:
        return next((f for f in self._files if f.fullpath == fullpath), None)

    def get_files_by_fullpath(self, fullpath: str) -> List[DownloadFiles]:
        return [f for f in self._files if f.fullpath == fullpath]

    def get_files_by_savepath(self, fullpath: str) -> List[DownloadFiles]:
        return [f for f in self._files if f.savepath == fullpath]

    def get_hash_by_fullpath(self, fullpath: str) -> Optional[str]:
        record = self.get_file_by_fullpath(fullpath)
        return record.download_hash if record else None

    # ------------------------------------------------------------------
    # 写入 / 删除
    # ------------------------------------------------------------------
    def add(self, **kwargs: Any) -> DownloadHistory:
        record = DownloadHistory(**kwargs)
        self._records.append(record)
        return record

    def add_files(self, file_items: List[dict]):
        created = [DownloadFiles(**item) for item in file_items or []]
        self._files.extend(created)
        return created

    def stage_add(self, payload: dict) -> DownloadHistory:
        return self.add(**payload)

    def stage_add_files(self, file_items: List[dict]) -> None:
        self.add_files(file_items)

    def delete_file_by_fullpath(self, fullpath: str):
        """按完整路径删除文件记录。"""
        self._files = [f for f in self._files if f.fullpath != fullpath]
        return True

    def stage_delete_file_by_fullpath(self, fullpath: str) -> None:
        self.delete_file_by_fullpath(fullpath)

    def truncate(self) -> None:
        self._records.clear()

    def truncate_files(self) -> None:
        self._files.clear()
