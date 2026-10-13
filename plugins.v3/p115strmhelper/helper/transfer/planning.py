from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from app.application.transfer.models import TransferPlanItem
from app.schemas import FileItem, TransferInfo
from app.sdk.media import MetaInfoPath

from ...schemas.transfer import TransferTask
from .file_types import TransferFileTypes
from .linked_subtitle_audio import (
    is_subtitle_or_audio_file,
    match_audio_track_files,
    match_subtitle_files,
)


MAIN_ACTION = "p115_batch_v1"
LINKED_ACTION = "p115_linked_v1"
LINKED_SKIP = "关联字幕/音轨由主视频的持久计划处理"


def extend_plan(checkpoint: Any, source_oper: Any, linked: bool) -> Any:
    """
    冻结批量执行标识及与 V2 相同的字幕、音轨匹配结果
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
                    target_path=str(related.target_path),
                    action=LINKED_ACTION,
                )
            )
    return replace(checkpoint, items=tuple(items))


def execute_plan(
    original: Callable, handler: Any, checkpoint: Any, **kwargs: Any
) -> TransferInfo:
    """
    使用同一任务 runner 执行冻结主文件与关联文件，保留逐文件结果供原子结算
    """
    main = replace(
        checkpoint,
        items=(replace(checkpoint.items[0], sequence=0, action="transfer"),),
    )
    result = original(handler, main, **kwargs)
    if not result.success or result.target_item is None or checkpoint.preview:
        return result
    sources, targets = [], []
    failures = []
    for item in checkpoint.items[1:]:
        if item.action != LINKED_ACTION:
            raise ValueError(f"不支持的批量计划操作：{item.action}")
        child = replace(
            checkpoint,
            planning_input=replace(
                checkpoint.planning_input, source_fileitem=item.source_fileitem
            ),
            items=(replace(item, sequence=0, action="transfer"),),
            final_target_path=item.target_path,
            overwrite_mode="always",
            need_notify=False,
            need_scrape=False,
        )
        child_kwargs = dict(kwargs)
        child_kwargs["cleanup_before_transfer"] = None
        child_result = original(handler, child, **child_kwargs)
        sources.append(FileItem(**item.source_fileitem))
        if child_result.success and child_result.target_item is not None:
            targets.append(child_result.target_item)
            result.file_list.extend(child_result.file_list or [])
            result.file_list_new.extend(child_result.file_list_new or [])
        else:
            failures.append(item.source_fileitem["path"])
    if sources:
        result.fileitem = result.fileitem.model_copy(update={"children": sources})
        result.target_item = result.target_item.model_copy(update={"children": targets})
    if failures:
        result.success = False
        result.fail_list = failures
        result.message = "主文件已整理，部分关联字幕/音轨整理失败"
    return result
