from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from p115client import check_response

from app.application.directory import DirectoryHelper
from app.schemas import FileItem
from app.sdk.config import settings
from app.sdk.logging import logger

from ...core.config import configer
from .cache_updater import CacheUpdater


class SourceDirectoryCleaner:
    """
    串行清理同一存储的源目录，同批成功任务集合只处理一次
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._completed: OrderedDict = OrderedDict()

    def cleanup(self, chain: Any, task: Any, source_oper: Any) -> None:
        """
        合并同批重复收尾，失败时允许后续调用重新检查
        """
        if source_oper is None or not chain.jobview.is_success(task):
            return
        with self._lock:
            tasks = chain.jobview.success_tasks(task.mediainfo, task.meta.begin_season)
            paths = sorted(
                {
                    successful.fileitem.path
                    for successful in tasks
                    if successful.fileitem
                    and successful.fileitem.storage == task.fileitem.storage
                }
            )
            batch_id = getattr(task, "transfer_batch_id", None)
            key = (batch_id, source_oper, tuple(paths))
            if batch_id and key in self._completed:
                return
            if _cleanup_paths(paths, source_oper) and batch_id:
                self._completed[key] = True
                while len(self._completed) > 128:
                    self._completed.popitem(last=False)


def _cleanup_paths(paths: List[str], source_oper: Any) -> bool:
    protected = [
        Path(path)
        for directory in DirectoryHelper().get_dirs()
        for path in (directory.download_path, directory.library_path)
        if path
    ]
    media_exts = {
        str(ext).lower().lstrip(".")
        for ext in (
            settings.RMT_MEDIAEXT
            + settings.RMT_SUBEXT
            + settings.RMT_AUDIOEXT
            + settings.DOWNLOAD_TMPEXT
        )
    }

    listings: Dict[str, List[FileItem]] = {}
    folders: Dict[Path, Optional[FileItem]] = {}
    observed: Dict[str, FileItem] = {}

    def list_files(folder: FileItem) -> List[FileItem]:
        if folder.fileid in listings:
            return listings[folder.fileid]
        items = source_oper.list(folder)
        if items is None:
            raise OSError(f"无法确认待清理目录内容：{folder.path}")
        listings[folder.fileid] = items
        observed[folder.fileid] = folder
        for item in items:
            observed[item.fileid] = item
            if item.type == "dir":
                folders[Path(item.path)] = item
        return items

    def contains_media(folder: FileItem) -> bool:
        for item in list_files(folder):
            if item.type == "dir":
                if contains_media(item):
                    return True
            elif (
                str(item.extension or Path(item.path).suffix).lower().lstrip(".")
                in media_exts
            ):
                return True
        return False

    def eligible(path: Path, boundary: Optional[Path]) -> Optional[FileItem]:
        if len(path.parts) <= 2 or any(root.is_relative_to(path) for root in protected):
            return None
        if path not in folders:
            folders[path] = source_oper.get_item_strict(path)
        folder = folders[path]
        if not folder or folder.type != "dir" or not folder.fileid:
            return None
        if boundary is None and list_files(folder):
            return None
        if contains_media(folder):
            return None
        return folder

    try:
        candidates: Dict[str, Tuple[FileItem, Optional[Path]]] = {}
        visited = set()
        for source in map(Path, paths):
            boundary = max(
                (root for root in protected if source.is_relative_to(root)),
                key=lambda path: len(path.parts),
                default=None,
            )
            path = source.parent
            while len(path.parts) > 2 and path not in visited:
                visited.add(path)
                folder = eligible(path, boundary)
                if folder is None:
                    break
                candidates[folder.fileid] = (folder, boundary)
                path = path.parent
        ordered = sorted(
            candidates.values(),
            key=lambda entry: len(Path(entry[0].path).parts),
        )
        # 删除前重新读取；同轮的父子目录复核共享结果，避免按集重复扫描
        listings.clear()
        confirmed: List[FileItem] = []
        for folder, boundary in ordered:
            if any(
                Path(folder.path).is_relative_to(Path(root.path)) for root in confirmed
            ):
                continue
            if eligible(Path(folder.path), boundary):
                confirmed.append(folder)
        if not confirmed:
            return True
        logger.info(f"【整理接管】开始批量删除空目录：{len(confirmed)} 个目录")
        for folder in confirmed:
            logger.info(
                "【整理接管】待清理目录：路径=%r，目录ID=%s",
                folder.path,
                folder.fileid,
            )
        response = source_oper.client.fs_delete(
            [folder.fileid for folder in confirmed],
            **configer.get_ios_ua_app(app=False),
        )
        check_response(response)
        for item in observed.values():
            if item.fileid and any(
                Path(item.path).is_relative_to(Path(folder.path))
                for folder in confirmed
            ):
                CacheUpdater(source_oper).remove_cache(int(item.fileid))
        logger.info(f"【整理接管】批量删除空目录成功：{len(confirmed)} 个目录")
        return True
    except Exception as error:
        logger.warning(f"【整理接管】源目录清理未完成：{error}", exc_info=True)
        return False
