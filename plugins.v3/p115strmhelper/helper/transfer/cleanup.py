from pathlib import Path
from typing import Any, Dict, List, Optional

from p115client import check_response

from app.application.directory import DirectoryHelper
from app.schemas import FileItem
from app.sdk.config import settings
from app.sdk.logging import logger

from ...core.config import configer
from .cache_updater import CacheUpdater


def cleanup_source_directories(chain: Any, task: Any, source_oper: Any) -> None:
    """
    按 V2 边界清理成功移动后的源目录，不操作下载器种子
    """
    if source_oper is None or not chain.jobview.is_success(task):
        return
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

    def list_files(folder: FileItem) -> List[FileItem]:
        items = source_oper.list(folder)
        if items is None:
            raise OSError(f"无法确认待清理目录内容：{folder.path}")
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
        folder = source_oper.get_item_strict(path)
        if not folder or folder.type != "dir" or not folder.fileid:
            return None
        if boundary is None and list_files(folder):
            return None
        if contains_media(folder):
            return None
        return folder

    try:
        candidates: Dict[str, Any] = {}
        for successful in chain.jobview.success_tasks(
            task.mediainfo, task.meta.begin_season
        ):
            if successful.fileitem.storage != task.fileitem.storage:
                continue
            source = Path(successful.fileitem.path)
            boundary = max(
                (root for root in protected if source.is_relative_to(root)),
                key=lambda path: len(path.parts),
                default=None,
            )
            path = source.parent
            while len(path.parts) > 2:
                folder = eligible(path, boundary)
                if folder is None:
                    break
                candidates[folder.fileid] = (folder, boundary)
                path = path.parent
        ordered = sorted(
            candidates.values(),
            key=lambda entry: len(Path(entry[0].path).parts),
            reverse=True,
        )
        confirmed = [
            folder
            for folder, boundary in ordered
            if eligible(Path(folder.path), boundary)
        ]
        if not confirmed:
            return
        logger.info(f"【整理接管】开始批量删除空目录：{len(confirmed)} 个目录")
        response = source_oper.client.fs_delete(
            [folder.fileid for folder in confirmed],
            **configer.get_ios_ua_app(app=False),
        )
        check_response(response)
        for folder in confirmed:
            CacheUpdater(source_oper).remove_cache(int(folder.fileid))
        logger.info(f"【整理接管】批量删除空目录成功：{len(confirmed)} 个目录")
    except Exception as error:
        logger.warning(f"【整理接管】源目录清理未完成：{error}", exc_info=True)
