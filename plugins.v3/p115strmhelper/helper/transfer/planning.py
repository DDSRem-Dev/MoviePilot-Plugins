from dataclasses import replace
from typing import Any, Callable

from app.application.transfer.models import TransferPlanItem
from app.schemas import FileItem, TransferInfo


MAIN_ACTION = "p115_batch_v1"
LINKED_ACTION = "p115_linked_v1"
LINKED_SKIP = "关联字幕/音轨由主视频的持久计划处理"


def restore_skipped_plan(checkpoint: Any) -> Any:
    """
    将旧版无副作用附件计划派生为原目标单文件操作，保留持久计划指纹
    """
    if checkpoint.skip_reason != LINKED_SKIP:
        return checkpoint
    return replace(
        checkpoint,
        skip_reason=None,
        items=(
            TransferPlanItem(
                sequence=0,
                source_fileitem=checkpoint.planning_input.source_fileitem,
                target_storage=checkpoint.target_storage,
                target_path=checkpoint.final_target_path,
                action=MAIN_ACTION,
            ),
        ),
    )


def extend_plan(checkpoint: Any) -> Any:
    """
    仅标记单文件批量执行，关联附件在请求阶段创建独立宿主持久任务
    """
    if checkpoint.skip_reason or checkpoint.rejection_error or not checkpoint.items:
        return checkpoint
    return replace(
        checkpoint,
        items=(replace(checkpoint.items[0], action=MAIN_ACTION),),
    )


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
