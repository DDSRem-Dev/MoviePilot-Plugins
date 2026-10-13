from dataclasses import replace
from pathlib import Path
from typing import Any, Tuple

from app.application.transfer.models import TransferPlanItem
from app.schemas import FileItem
from app.plugins.p115strmhelper.helper.transfer.planning import (
    MAIN_ACTION,
    LINKED_ACTION,
    LINKED_SKIP,
)


def legacy_plan(
    checkpoint: Any,
    related: Tuple[Tuple[FileItem, str], ...] = (),
    *,
    skip: bool = False,
) -> Any:
    """
    用已冻结的附件及目标后缀构造旧计划，独立验证恢复格式而不重跑旧匹配算法
    """
    if skip:
        return replace(checkpoint, items=(), skip_reason=LINKED_SKIP, need_notify=False)
    target = Path(checkpoint.final_target_path)
    items = [replace(checkpoint.items[0], action=MAIN_ACTION)]
    for source, suffix in related:
        items.append(
            TransferPlanItem(
                sequence=len(items),
                source_fileitem=source.model_dump(mode="json"),
                target_storage=checkpoint.target_storage,
                target_path=target.with_name(target.stem + suffix).as_posix(),
                action=LINKED_ACTION,
            )
        )
    return replace(checkpoint, items=tuple(items))
