from typing import Any, List

from sqlalchemy import select

from app.application.transfer.workflow import TransferAdmissionProjectionError
from app.db.adapters.transfer.admission import TransactionalTransferAdmissionRepository
from app.db.models.transferpending import TransferPending
from app.db.oper.transferpending import TransferPendingOper
from app.sdk.logging import logger

from .planning import LINKED_SKIP, MAIN_ACTION


def claim_batch_recovery(chain: Any, workers: Any, claimed: List[Any]) -> List[Any]:
    """
    在宿主恢复槽位之外领取已冻结的网盘批量计划，仍由宿主 CAS 和原队列执行
    """
    repository = chain._transfer_admissions
    if not isinstance(repository, TransactionalTransferAdmissionRepository):
        return claimed
    with chain._worker_state_lock:
        owned = len(chain._owned_leases)
    capacity = min(workers.limit, chain._RECOVERY_CLAIM_LIMIT) - owned - len(claimed)
    if capacity <= 0 or workers._stopping.is_set():
        return claimed
    after = None
    scanned = 0
    original_count = len(claimed)
    try:
        while capacity > 0 and scanned < repository._MAX_RECOVERY_SCAN_TASKS:
            if workers._stopping.is_set():
                break
            with repository._session_factory() as session:
                candidates = TransferPendingOper(db=session).list_claimable_candidates(
                    states=repository._recoverable_states(),
                    now_time=repository._format_lease_time(repository._lease_now()),
                    limit=min(100, repository._MAX_RECOVERY_SCAN_TASKS - scanned),
                    after_cursor=after,
                )
                if not candidates:
                    break
                payloads = dict(
                    session.execute(
                        select(
                            TransferPending.task_id, TransferPending.checkpoint_payload
                        ).where(
                            TransferPending.task_id.in_(
                                [item[0] for item in candidates]
                            ),
                            TransferPending.storage == workers.storage,
                            TransferPending.state == "planned",
                        )
                    ).all()
                )
            scanned += len(candidates)
            after = (candidates[-1][1], candidates[-1][2])
            for task_id, _, _ in candidates:
                if capacity <= 0 or workers._stopping.is_set():
                    break
                plan = payloads.get(task_id)
                if not isinstance(plan, dict):
                    continue
                items = plan.get("items") or []
                if not (
                    plan.get("target_storage") == workers.storage
                    and plan.get("resolved_transfer_type") in {"move", "copy"}
                    and (
                        plan.get("skip_reason") == LINKED_SKIP
                        or items
                        and isinstance(items[0], dict)
                        and items[0].get("action") == MAIN_ACTION
                    )
                ):
                    continue
                try:
                    admission = repository.claim_task(
                        task_id=task_id,
                        owner_id=chain._worker_owner_id,
                        lease_seconds=chain._WORKER_LEASE_SECONDS,
                    )
                except TransferAdmissionProjectionError as error:
                    repository._record_projection_failure(task_id=task_id, error=error)
                    continue
                if admission is not None:
                    claimed.append(admission)
                    capacity -= 1
    except Exception:
        # 已领取的任务必须交回宿主登记续租，不能因后续扫描失败丢弃
        logger.warning(
            "【整理接管】批量恢复扫描未完成，已领取任务继续交回宿主", exc_info=True
        )
    added = len(claimed) - original_count
    if added:
        logger.info(
            "【整理接管】批量恢复领取：宿主原领取=%s，追加批量计划=%s，当前持有租约=%s，本轮总数=%s",
            original_count,
            added,
            owned,
            len(claimed),
        )
        for admission in claimed[original_count:]:
            logger.info(
                "【整理接管】恢复任务入队候选：任务=%s，源=%r",
                admission.task_id,
                admission.src_path,
            )
    return claimed
