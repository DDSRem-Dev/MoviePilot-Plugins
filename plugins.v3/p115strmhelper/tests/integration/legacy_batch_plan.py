from dataclasses import replace
from pathlib import Path
from typing import Any

from app.application.transfer.models import TransferPlanItem
from app.schemas import FileItem
from app.sdk.media import MetaInfoPath
from app.plugins.p115strmhelper.schemas.transfer import TransferTask
from app.plugins.p115strmhelper.helper.transfer.file_types import TransferFileTypes
from app.plugins.p115strmhelper.helper.transfer.linked_subtitle_audio import (
    is_subtitle_or_audio_file,
    match_audio_track_files,
    match_subtitle_files,
)
from app.plugins.p115strmhelper.helper.transfer.planning import (
    MAIN_ACTION,
    LINKED_ACTION,
    LINKED_SKIP,
)


def legacy_plan(checkpoint: Any, source_oper: Any, linked: bool) -> Any:
    """
    构造升级前的持久计划，验证旧任务恢复兼容
    """
    if checkpoint.skip_reason or checkpoint.rejection_error or not checkpoint.items:
        return checkpoint
    source = FileItem(**checkpoint.planning_input.source_fileitem)
    if source.type != "file":
        return checkpoint
    if linked and is_subtitle_or_audio_file(source):
        return replace(checkpoint, items=(), skip_reason=LINKED_SKIP, need_notify=False)
    items = [replace(checkpoint.items[0], action=MAIN_ACTION)]
    if linked and TransferFileTypes._is_media_file(source) and not checkpoint.preview:
        folder = source_oper.get_item_strict(Path(source.path).parent)
        if not folder:
            raise OSError(f"无法确认关联文件目录：{source.path}")
        files = source_oper.list(folder)
        if files is None:
            raise OSError(f"关联文件目录读取失败：{folder.path}")
        task = TransferTask(
            fileitem=source,
            target_path=Path(checkpoint.final_target_path),
            mediainfo=None,
            meta=None,
            transfer_type=checkpoint.resolved_transfer_type,
        )
        match_subtitle_files(
            task, Path(source.path), MetaInfoPath(Path(source.path)), files
        )
        match_audio_track_files(task, Path(source.path), files)
        seen = set()
        for related in task.related_files:
            if related.fileitem.path in seen:
                continue
            seen.add(related.fileitem.path)
            items.append(
                TransferPlanItem(
                    sequence=len(items),
                    source_fileitem=related.fileitem.model_dump(mode="json"),
                    target_storage=checkpoint.target_storage,
                    target_path=related.target_path.as_posix(),
                    action=LINKED_ACTION,
                )
            )
    return replace(checkpoint, items=tuple(items))
