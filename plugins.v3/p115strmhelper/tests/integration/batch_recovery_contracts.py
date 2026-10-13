from dataclasses import replace
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch


class BatchRecoveryContracts:
    """
    验证批量恢复容量和宿主原子租约边界
    """

    def test_recovery_claims_batch_plans_without_expanding_native_tasks(self) -> None:
        """
        单个宿主槽位之外只增加批量任务，跳过有效租约、人工复核和未到期重试
        """
        from sqlalchemy import select
        from app.chain.transfer import TransferChain
        from app.db.adapters.transfer.admission import (
            TransactionalTransferAdmissionRepository,
        )
        from app.db.models.transferpending import TransferPending

        names = [
            "native-0",
            "native-1",
            "batch-0",
            "batch-1",
            "owned",
            "review",
            "later",
        ]
        for name in names:
            self.seed(name)
        with self.factory() as session:
            for row in session.scalars(select(TransferPending)):
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                if row.task_id.startswith("native"):
                    plan = self.plans[row.task_id]
                    row.checkpoint_payload = replace(
                        plan, items=(replace(plan.items[0], action="transfer"),)
                    ).to_payload()
                elif row.task_id == "owned":
                    row.lease_token = "active"
                    row.lease_owner = "another-process"
                    row.lease_expires_at = "2099-01-01 00:00:00.000000"
                elif row.task_id == "review":
                    row.execution_state = "manual_review"
                elif row.task_id == "later":
                    row.execution_state = "retry_wait"
                    row.retry_due_at = "2099-01-01 00:00:00.000000"
            session.commit()
        repository = TransactionalTransferAdmissionRepository(self.factory)
        chain = SimpleNamespace(
            runtime_config=SimpleNamespace(transfer_threads=1),
            _worker_state_lock=RLock(),
            _owned_leases={},
            _transfer_admissions=repository,
            _worker_owner_id="recovered",
            _RECOVERY_CLAIM_LIMIT=100,
            _WORKER_LEASE_SECONDS=120,
        )
        claimed = TransferChain._TransferChain__claim_recovery_batch(chain)
        self.assertEqual(
            {item.task_id for item in claimed}, {"native-0", "batch-0", "batch-1"}
        )
        self.assertTrue(
            all(
                item.lease_owner == "recovered" and item.lease_token for item in claimed
            )
        )
        with self.factory() as session:
            rows = {
                row.task_id: row for row in session.scalars(select(TransferPending))
            }
            self.assertIsNone(rows["native-1"].lease_token)
            self.assertEqual(rows["owned"].lease_token, "active")
            self.assertIsNone(rows["review"].lease_token)
            self.assertIsNone(rows["later"].lease_token)
        chain._owned_leases = {str(index): ("lease", 0) for index in range(100)}
        self.assertEqual(TransferChain._TransferChain__claim_recovery_batch(chain), [])

    def test_recovery_scan_failure_retains_claimed_tasks(self) -> None:
        """
        追加恢复扫描失败时已领取任务仍交回宿主，未领取任务保留原状态
        """
        from sqlalchemy import select
        from app.chain.transfer import TransferChain
        from app.db.adapters.transfer.admission import (
            TransactionalTransferAdmissionRepository,
        )
        from app.db.models.transferpending import TransferPending

        for name in ("first", "second", "third"):
            self.seed(name)
        with self.factory() as session:
            for row in session.scalars(select(TransferPending)):
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
            session.commit()
        repository = TransactionalTransferAdmissionRepository(self.factory)
        chain = SimpleNamespace(
            runtime_config=SimpleNamespace(transfer_threads=1),
            _worker_state_lock=RLock(),
            _owned_leases={},
            _transfer_admissions=repository,
            _worker_owner_id="recovered",
            _RECOVERY_CLAIM_LIMIT=100,
            _WORKER_LEASE_SECONDS=120,
        )
        original = repository.claim_task

        def claim(**kwargs):
            if kwargs["task_id"] == "third":
                raise OSError("injected database failure")
            return original(**kwargs)

        with patch.object(repository, "claim_task", side_effect=claim):
            claimed = TransferChain._TransferChain__claim_recovery_batch(chain)
        self.assertEqual([item.task_id for item in claimed], ["first", "second"])
