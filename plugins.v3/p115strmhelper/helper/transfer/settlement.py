from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.application.chain.events import snapshot_transfer_result
from app.application.history import add_transfer_fail, add_transfer_success
from app.application.outbox import (
    AUDIO_TRANSFER_COMPLETED_TOPIC,
    AUDIO_TRANSFER_FAILED_TOPIC,
    SUBTITLE_TRANSFER_COMPLETED_TOPIC,
    SUBTITLE_TRANSFER_FAILED_TOPIC,
    TRANSFER_COMPLETED_TOPIC,
    OutboxIntent,
)
from app.application.transfer.models import TransferPlanCheckpoint
from app.db.adapters.chain import _StagingTransferHistoryRepository
from app.db.adapters.outbox import SqlAlchemyOutboxStager
from app.db.models.transferexecutionstep import TransferExecutionStep
from app.db.models.transferpending import TransferPending
from app.schemas import FileItem, TransferInfo

from .file_types import TransferFileTypes
from .planning import LINKED_SKIP, MAIN_ACTION


def _restore_failed_files(session: Any, settlement: Any, result: TransferInfo) -> None:
    if result.success or result.fileitem is None or result.fileitem.children:
        return
    pending = session.scalar(
        select(TransferPending).where(TransferPending.task_id == settlement.task_id)
    )
    if pending is None or not pending.checkpoint_payload:
        return
    plan = TransferPlanCheckpoint.from_payload(pending.checkpoint_payload)
    if not plan.items or plan.items[0].action != MAIN_ACTION:
        return
    steps = list(
        session.scalars(
            select(TransferExecutionStep)
            .where(
                TransferExecutionStep.task_id == settlement.task_id,
                TransferExecutionStep.checkpoint_fingerprint == plan.fingerprint,
                TransferExecutionStep.phase == "p115_batch",
                TransferExecutionStep.state == "succeeded",
            )
            .order_by(TransferExecutionStep.ordinal)
        )
    )
    if not steps:
        return
    materialized = {}
    renamed = {}
    for step in steps:
        item = (step.result_payload or {}).get("item")
        if not item:
            continue
        if step.kind == "materialize":
            materialized[step.intent_payload["source"]["path"]] = FileItem(**item)
        elif step.kind == "rename":
            renamed[step.intent_payload["target"]] = FileItem(**item)
    sources, targets, failed = [], [], []
    result.file_list, result.file_list_new = [], []
    for index, item in enumerate(plan.items):
        source = FileItem(**item.source_fileitem)
        target = renamed.get(item.target_path)
        if target is None:
            failed.append(source.path)
            target = materialized.get(source.path)
        if target is not None:
            result.file_list.append(source.path)
            result.file_list_new.append(target.path)
        if index == 0:
            result.target_item = target
        else:
            sources.append(source)
            if target is not None:
                targets.append(target)
    result.fileitem = result.fileitem.model_copy(update={"children": sources})
    if result.target_item is not None:
        result.target_item = result.target_item.model_copy(update={"children": targets})
        result.target_diritem = FileItem(
            storage=plan.target_storage,
            type="dir",
            path=Path(result.target_item.path).parent.as_posix() + "/",
        )
    result.fail_list = failed or result.fail_list


def stage_linked_results(
    original: Callable, writer: Any, *, stage_history: Callable, **kwargs: Any
) -> Any:
    """
    将关联文件历史和完成事件加入原主任务的结算事务
    """
    payload = kwargs["event_payload"]
    result = payload.get("transferinfo")
    settlement = kwargs.get("settlement")
    if not isinstance(result, TransferInfo) or settlement is None:
        return original(writer, stage_history=stage_history, **kwargs)
    source = result.fileitem

    def stage(staging: Any) -> Any:
        _restore_failed_files(staging._repository._db, settlement, result)
        linked = (
            result.fileitem.children
            if result.fileitem and result.fileitem.type == "file"
            else []
        )
        if result.message == LINKED_SKIP:
            prior = staging.get_success_by_src(source.path, source.storage)
            if prior is not None and getattr(prior, "dest", None):
                return prior
        history = stage_history(staging)
        repository = staging._repository
        child_staging = _StagingTransferHistoryRepository(repository)
        outbox = SqlAlchemyOutboxStager(repository._db)
        if (
            not result.success
            and result.target_item is not None
            and source.path not in (result.fail_list or [])
        ):
            main_result = result.model_copy(
                update={
                    "success": True,
                    "fileitem": source.model_copy(update={"children": []}),
                    "target_item": result.target_item.model_copy(
                        update={"children": []}
                    ),
                    "file_list": [source.path],
                    "file_list_new": [result.target_item.path],
                    "fail_list": [],
                    "message": None,
                }
            )
            event_key = f"{TRANSFER_COMPLETED_TOPIC}:{settlement.task_id}:{settlement.execution_fingerprint}:main"
            outbox.stage(
                OutboxIntent(
                    event_key=event_key,
                    topic=TRANSFER_COMPLETED_TOPIC,
                    payload=snapshot_transfer_result(
                        {
                            **payload,
                            "transferinfo": main_result,
                            "transfer_history_id": history.id,
                            "idempotency_key": event_key,
                        }
                    ),
                ),
                datetime.now(timezone.utc),
            )
        if not linked:
            return history
        targets = {
            item.path: item
            for item in (result.target_item.children if result.target_item else [])
        }
        paths = dict(zip(result.file_list or [], result.file_list_new or []))
        for child in linked:
            target = targets.get(paths.get(child.path))
            successful = target is not None and child.path not in (
                result.fail_list or []
            )
            child_result = TransferInfo(
                success=successful,
                fileitem=child,
                target_item=target,
                target_diritem=result.target_diritem,
                transfer_type=result.transfer_type,
                file_list=[child.path],
                file_list_new=[target.path] if target else [],
                fail_list=[] if successful else [child.path],
                file_count=1 if successful else 0,
                total_size=child.size or 0,
                message=None if successful else "关联文件整理失败",
            )
            add = add_transfer_success if successful else add_transfer_fail
            child_history = add(
                fileitem=child,
                mode=result.transfer_type or "",
                downloader=payload.get("downloader"),
                download_hash=payload.get("download_hash"),
                meta=payload["meta"],
                mediainfo=payload["mediainfo"],
                transferinfo=child_result,
                transfer_history_oper=child_staging,
            )
            subtitle = TransferFileTypes._is_subtitle_file(child)
            if subtitle:
                topic = (
                    SUBTITLE_TRANSFER_COMPLETED_TOPIC
                    if successful
                    else SUBTITLE_TRANSFER_FAILED_TOPIC
                )
            else:
                topic = (
                    AUDIO_TRANSFER_COMPLETED_TOPIC
                    if successful
                    else AUDIO_TRANSFER_FAILED_TOPIC
                )
            suffix = sha256(child.path.encode()).hexdigest()
            event_key = f"{topic}:{settlement.task_id}:{settlement.execution_fingerprint}:{suffix}"
            child_payload = {
                **payload,
                "fileitem": child,
                "transferinfo": child_result,
                "transfer_history_id": child_history.id,
                "idempotency_key": event_key,
            }
            outbox.stage(
                OutboxIntent(
                    event_key=event_key,
                    topic=topic,
                    payload=snapshot_transfer_result(child_payload),
                ),
                datetime.now(timezone.utc),
            )
        return history

    return original(writer, stage_history=stage, **kwargs)
