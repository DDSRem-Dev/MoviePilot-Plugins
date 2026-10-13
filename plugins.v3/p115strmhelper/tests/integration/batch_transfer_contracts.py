from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, RLock
from time import monotonic
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


class BatchTransferContracts(TestCase):
    """
    使用真实 V3 SQLite 步骤账本验证批量整理和恢复，网盘边界使用内存替身
    """

    def setUp(self) -> None:
        """
        每个场景建立独立数据库和云端文件集合
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.base import Base
        from app.db.adapters.transfer.execution import (
            TransactionalTransferExecutionRepository,
        )
        from app.plugins.p115strmhelper.helper.transfer.durable import (
            DurableBatchTransfer,
        )
        from app.plugins.p115strmhelper.patch.transfer_chain import TransferChainPatcher

        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(f"sqlite:///{self.temporary.name}/batch.db")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.repository = TransactionalTransferExecutionRepository(self.factory)
        self.storage = MemoryDrive()
        self.handler = DurableBatchTransfer(delay=0.05)
        self.addCleanup(self.handler.shutdown)
        self.patcher = TransferChainPatcher
        self.patcher.enable(self.handler, self.handler, "115网盘Plus")
        self.addCleanup(self.patcher.disable)
        self.chain = SimpleNamespace(
            _TransferChain__assert_owned_lease=lambda task: None
        )
        self.plans = {}
        self.leases = {}

    def seed(self, name: str, mode: str = "copy"):
        """
        创建源文件并保存匹配的宿主准入、冻结计划和有效租约
        """
        from app.application.transfer.models import (
            TransferPlanningInput,
            TransferPlanCheckpoint,
            TransferPlanItem,
        )
        from app.db.models.transferpending import TransferPending
        from app.plugins.p115strmhelper.helper.transfer.planning import MAIN_ACTION

        source = self.storage.add(f"/source/{name}.mkv")
        target = f"/target/{name}-renamed.mkv"
        source_data = source.model_dump(mode="json")
        planning = TransferPlanningInput(
            source_fileitem=source_data, requested_transfer_type=mode
        )
        plan = TransferPlanCheckpoint(
            planning_input=planning,
            target_storage=source.storage,
            root_target_path="/target",
            final_target_path=target,
            resolved_transfer_type=mode,
            items=(
                TransferPlanItem(
                    sequence=0,
                    source_fileitem=source_data,
                    target_storage=source.storage,
                    target_path=target,
                    action=MAIN_ACTION,
                ),
            ),
        )
        self.plans[name] = plan
        self.leases[name] = "lease"
        with self.factory() as session:
            session.add(
                TransferPending(
                    task_id=name,
                    storage=source.storage,
                    src_path=source.path,
                    created_at="2026-10-13 00:00:00",
                    updated_at="2026-10-13 00:00:00",
                    state="planned",
                    input_version=1,
                    planning_input=planning.to_payload(),
                    input_fingerprint=planning.fingerprint,
                    checkpoint_version=plan.schema_version,
                    checkpoint_payload=plan.to_payload(),
                    planned_at="2026-10-13 00:00:00",
                    lease_owner="batch-test",
                    lease_token="lease",
                    lease_expires_at="2099-01-01 00:00:00.000000",
                    heartbeat_at="2026-10-13 00:00:00",
                    attempt_count=1,
                    execution_state="not_started",
                    retry_generation=0,
                    retry_count=0,
                    settlement_revision=0,
                )
            )
            session.commit()
        return source

    def run_transfer(self, name: str):
        """
        重建 runner 模拟任务恢复，并执行原计划对应的批量文件步骤
        """
        from app.chain.transfer.execution import _DurableTransferStepRunner

        plan = self.plans[name]
        runner = _DurableTransferStepRunner(
            task_id=name,
            lease_token=self.leases[name],
            checkpoint_fingerprint=plan.fingerprint,
            repository=self.repository,
        )
        return self.handler.execute(
            chain=self.chain,
            task=SimpleNamespace(admission_task_id=name),
            step_runner=runner,
            source_fileitem=plan.planning_input.source_fileitem,
            target_storage=plan.target_storage,
            source_oper=self.storage,
            target_oper=self.storage,
            target_file=Path(plan.final_target_path),
            transfer_type=plan.resolved_transfer_type,
        )[0]

    def test_copy_batch_and_replay(self) -> None:
        """
        多文件复制合并 API，副本身份正确且重放不重复复制或重命名
        """
        sources = [self.seed(f"copy-{index}") for index in range(4)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(
                workers.map(self.run_transfer, [f"copy-{index}" for index in range(4)])
            )
        self.assertTrue(
            any(kind == "copy" and len(ids) > 1 for kind, ids in self.storage.calls)
        )
        for index, (source, target) in enumerate(zip(sources, results)):
            self.assertNotEqual(source.fileid, target.fileid)
            self.assertNotEqual(source.pickcode, target.pickcode)
            self.assertEqual(self.storage.get_item_strict(Path(source.path)), source)
            calls = list(self.storage.calls)
            self.assertEqual(self.run_transfer(f"copy-{index}"), target)
            self.assertEqual(self.storage.calls, calls)

    def test_move_preserves_identity(self) -> None:
        """
        移动保留 ID 与 pickcode，重放时源路径不存在也能恢复目标
        """
        source = self.seed("move", "move")
        target = self.run_transfer("move")
        self.assertEqual(
            (source.fileid, source.pickcode), (target.fileid, target.pickcode)
        )
        self.assertIsNone(self.storage.get_item_strict(Path(source.path)))
        self.assertEqual(self.run_transfer("move"), target)
        self.assertEqual([kind for kind, _ in self.storage.calls], ["move", "rename"])

    def test_rename_failure_keeps_materialized_file(self) -> None:
        """
        重命名失败后由宿主保存待重试状态，重试不重复移动
        """
        from app.chain.transfer.execution import _TransferRetryDeferred

        source = self.seed("rename-retry", "move")
        self.storage.fail_rename = True
        with self.assertRaises(_TransferRetryDeferred):
            self.run_transfer("rename-retry")
        snapshot = self.repository.get_snapshot(task_id="rename-retry")
        self.assertEqual(snapshot.state.value, "retry_wait")
        self.assertEqual(
            [step.state.value for step in snapshot.steps],
            ["succeeded", "succeeded", "failed"],
        )
        self.storage.fail_rename = False
        from app.db.adapters.transfer.admission import (
            TransactionalTransferAdmissionRepository,
        )

        admissions = TransactionalTransferAdmissionRepository(self.factory)
        with patch.object(
            admissions,
            "_lease_now",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=60),
        ):
            claim = admissions.claim_task(
                task_id="rename-retry", owner_id="recovery", lease_seconds=600
            )
        self.assertIsNotNone(claim)
        self.leases["rename-retry"] = claim.lease_token
        target = self.run_transfer("rename-retry")
        self.assertEqual(target.fileid, source.fileid)
        self.assertEqual(sum(kind == "move" for kind, _ in self.storage.calls), 1)

    def test_cloud_timeout_after_copy_is_observed(self) -> None:
        """
        复制已生效但响应丢失时确认新增副本，不重复复制
        """
        self.seed("copy-timeout")
        self.storage.timeout_after_copy = True
        target = self.run_transfer("copy-timeout")
        self.assertEqual(target.path, "/target/copy-timeout-renamed.mkv")
        self.assertEqual(sum(kind == "copy" for kind, _ in self.storage.calls), 1)

    def test_unknown_copy_result_requires_review(self) -> None:
        """
        查询失败时保留未知结果，不将其作为未复制而自动重试
        """
        from app.chain.transfer.execution import _TransferManualReviewRequired

        self.seed("unknown")
        self.storage.fail_observation_after_copy = True
        with self.assertRaises(_TransferManualReviewRequired):
            self.run_transfer("unknown")
        self.assertEqual(
            self.repository.get_snapshot(task_id="unknown").state.value, "manual_review"
        )
        self.assertEqual(sum(kind == "copy" for kind, _ in self.storage.calls), 1)

    def test_unplanned_operation_is_rejected(self) -> None:
        """
        批量扩展不接受冻结计划以外的目标或未确认的重命名 ID
        """
        from app.chain.transfer.execution import _DurableTransferStepRunner
        from app.application.transfer.execution import TransferExecutionConflictError

        self.seed("fenced")
        runner = _DurableTransferStepRunner(
            task_id="fenced",
            lease_token="lease",
            checkpoint_fingerprint=self.plans["fenced"].fingerprint,
            repository=self.repository,
        )
        with self.assertRaises(TransferExecutionConflictError):
            runner.run(
                phase="p115_batch",
                kind="rename",
                payload={"item": {"fileid": "unrelated"}, "target": "/other.mkv"},
                execute=lambda: self.fail("不应执行"),
                observe=lambda: self.fail("不应探测"),
            )

    def test_linked_plan_atomic_history_and_outbox(self) -> None:
        """
        关联文件计划可恢复，主文件与字幕音轨历史、事件在同一事务提交且不重复
        """
        from sqlalchemy import select
        from app.application.chain.events import TransferResultSettlement
        from app.application.history import add_transfer_success
        from app.application.outbox import TRANSFER_COMPLETED_TOPIC
        from app.chain.transfer.execution import _DurableTransferStepRunner
        from app.db.adapters.chain import TransactionalChainDurableEventWriter
        from app.db.models.transferpending import TransferPending
        from app.db.models.transferhistory import TransferHistory
        from app.db.models.outbox import OutboxMessage
        from app.modules.filemanager.transhandler import TransHandler
        from app.plugins.p115strmhelper.helper.transfer.planning import extend_plan
        from app.plugins.p115strmhelper.patch.transfer_chain import _context
        from app.sdk.media import MediaInfo, MetaInfoPath
        from app.schemas.types import MediaType

        source = self.seed("Interstellar.2014")
        self.storage.add("/source/Interstellar.2014.zh-cn.srt")
        self.storage.add("/source/Interstellar.2014.flac")
        plan = extend_plan(self.plans["Interstellar.2014"], self.storage, linked=True)
        self.assertEqual(len(plan.items), 3)
        meta = MetaInfoPath(Path(source.path))
        media = MediaInfo(
            media_source="bangumi",
            media_id="42",
            title="星际穿越",
            year="2014",
            type=MediaType.MOVIE,
        )
        with self.factory() as session:
            pending = session.scalar(
                select(TransferPending).where(
                    TransferPending.task_id == "Interstellar.2014"
                )
            )
            pending.checkpoint_payload = plan.to_payload()
            session.commit()
        runner = _DurableTransferStepRunner(
            task_id="Interstellar.2014",
            lease_token="lease",
            checkpoint_fingerprint=plan.fingerprint,
            repository=self.repository,
        )
        token = _context.set(
            (
                self.chain,
                SimpleNamespace(
                    admission_task_id="Interstellar.2014", plan_checkpoint=plan
                ),
            )
        )
        try:
            with patch.object(self.handler, "supports", return_value=True):
                result = TransHandler().execute_transfer_plan(
                    plan,
                    meta=meta,
                    mediainfo=media,
                    source_oper=self.storage,
                    target_oper=self.storage,
                    step_runner=runner,
                )
        finally:
            _context.reset(token)
        self.assertTrue(result.success)
        self.assertEqual(len(result.file_list_new), 3)
        self.assertEqual(len(result.target_item.children), 2)
        execution = runner.checkpoint(result)
        writer = TransactionalChainDurableEventWriter(self.factory)
        payload = dict(fileitem=source, transferinfo=result, meta=meta, mediainfo=media)
        settlement = TransferResultSettlement(
            task_id="Interstellar.2014",
            lease_token="lease",
            execution_fingerprint=execution.fingerprint,
            outcome="succeeded",
        )

        def write():
            return writer.transfer_result(
                topic=TRANSFER_COMPLETED_TOPIC,
                stage_history=lambda staging: add_transfer_success(
                    fileitem=source,
                    mode="copy",
                    meta=meta,
                    mediainfo=media,
                    transferinfo=result,
                    transfer_history_oper=staging,
                ),
                event_payload=payload,
                publish=None,
                settlement=settlement,
            )

        receipt = write()
        self.assertFalse(receipt.already_settled)
        self.assertTrue(write().already_settled)
        with self.factory() as session:
            histories = list(session.scalars(select(TransferHistory)))
            events = list(session.scalars(select(OutboxMessage)))
            self.assertEqual(len(histories), 3)
            self.assertEqual(len(events), 3)
            self.assertTrue(all(history.media_id == "42" for history in histories))
            self.assertEqual(len({event.event_key for event in events}), 3)
            self.assertIsNone(session.scalar(select(TransferPending)))

    def test_native_queue_keeps_original_tasks_until_settlement(self) -> None:
        """
        从真实宿主入队到原子终态，批量 worker 保留原任务身份与完整执行回调
        """
        from sqlalchemy import select
        from app.chain.transfer import TransferChain
        from app.chain.media import MediaChain
        from app.db.adapters.chain import TransactionalChainDurableEventWriter
        from app.db.adapters.transfer.admission import (
            TransactionalTransferAdmissionRepository,
        )
        from app.db.models.transferpending import TransferPending
        from app.db.models.transfersettlementreceipt import TransferSettlementReceipt
        from app.modules.filemanager.module import FileManagerModule
        from app.plugins.p115strmhelper.core.config import configer
        from app.schemas import TransferTask
        from app.schemas.system import TransferDirectoryConf
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo, MetaInfoPath

        media = MediaInfo(
            media_source="bangumi",
            media_id="42",
            title="星际穿越",
            year="2014",
            type=MediaType.MOVIE,
        )
        chain = object.__new__(TransferChain)
        with patch.object(TransferChain, "_TransferChain__init", return_value=True):
            TransferChain.__init__(chain)
        self.addCleanup(chain.close_workers)
        admissions = TransactionalTransferAdmissionRepository(self.factory)
        chain.transfer_admission_repository = admissions
        chain._transfer_admissions = admissions
        chain.transfer_execution_repository = self.repository
        chain._transfer_executions = self.repository
        chain.transfer_history_repository = Mock()
        chain.durable_event_writer = TransactionalChainDurableEventWriter(self.factory)
        chain._module_dispatcher = Mock()
        chain._module_dispatcher.freeze_plugin_providers.return_value = ()
        module = FileManagerModule()
        chain.plan_transfer = module.plan_transfer
        chain.run_module = lambda name, **kwargs: getattr(module, name)(**kwargs)
        chain._TransferChain__select_storage_oper = lambda storage: self.storage
        chain.send_transfer_message = Mock()
        chain._send_metadata_scrape_event = Mock()
        directory = TransferDirectoryConf(
            library_path="/target",
            library_storage="115网盘Plus",
            transfer_type="copy",
            renaming=False,
            notify=False,
            scraping=False,
        )
        tasks = []
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(configer, "pan_transfer_linked_subtitle_audio", False)
            )
            stack.enter_context(
                patch.object(MediaChain, "supplement_tmdb_info", return_value=media)
            )
            stack.enter_context(
                patch.object(self.handler, "supports", return_value=True)
            )
            try:
                for index in range(4):
                    source = self.storage.add(
                        f"/source/Interstellar.2014.part{index}.mkv"
                    )
                    task = TransferTask(
                        fileitem=source,
                        meta=MetaInfoPath(Path(source.path)),
                        mediainfo=media,
                        target_directory=directory,
                        target_storage="115网盘Plus",
                        transfer_type="copy",
                        transfer_batch_id="native-batch",
                    )
                    tasks.append(task)
                    self.assertTrue(chain.put_to_queue(task))
                deadline = monotonic() + 10
                while monotonic() < deadline and chain._queue.unfinished_tasks:
                    Event().wait(0.05)
                self.assertEqual(chain._queue.unfinished_tasks, 0)
                self.assertTrue(all(task.terminal_settled for task in tasks))
                self.assertTrue(
                    any(
                        kind == "copy" and len(ids) > 1
                        for kind, ids in self.storage.calls
                    )
                )
                with self.factory() as session:
                    self.assertEqual(list(session.scalars(select(TransferPending))), [])
                    receipts = list(session.scalars(select(TransferSettlementReceipt)))
                    self.assertEqual(
                        {row.task_id for row in receipts},
                        {task.admission_task_id for task in tasks},
                    )
                    self.assertTrue(all(row.outcome == "succeeded" for row in receipts))
                self.assertEqual(chain._owned_leases, {})
            finally:
                self.assertTrue(chain.close_workers())


class MemoryDrive:
    """
    支持批量操作和故障注入的网盘替身，保留真实 FileItem 与变更后的文件身份
    """

    def __init__(self) -> None:
        self.client = self
        self.items = {}
        self.calls = []
        self.lock = RLock()
        self.next_id = 100
        self.fail_rename = False
        self.timeout_after_copy = False
        self.fail_observation_after_copy = False
        self.query_failed = False
        self.add("/source", "dir")
        self.add("/target", "dir")

    def add(self, path: str, kind: str = "file"):
        """
        创建测试文件或目录
        """
        from app.schemas import FileItem

        with self.lock:
            self.next_id += 1
            item = FileItem(
                storage="115网盘Plus",
                path=path,
                type=kind,
                name=Path(path).name,
                extension=Path(path).suffix.lstrip("."),
                fileid=str(self.next_id),
                pickcode=f"pc{self.next_id}",
                size=1024,
            )
            self.items[item.fileid] = item
            return item.model_copy(deep=True)

    def get_item_strict(self, path: Path):
        """
        严格查询测试文件
        """
        with self.lock:
            if self.query_failed:
                raise ConnectionError("injected query failure")
            return next(
                (
                    item.model_copy(deep=True)
                    for item in self.items.values()
                    if item.path == str(path)
                ),
                None,
            )

    def list(self, folder):
        """
        返回目录的云端实时内容
        """
        with self.lock:
            if self.query_failed:
                raise ConnectionError("injected query failure")
            return [
                item.model_copy(deep=True)
                for item in self.items.values()
                if str(Path(item.path).parent) == folder.path
            ]

    def get_folder(self, path: Path):
        """
        获取或创建测试目录
        """
        return self.get_item_strict(path) or self.add(str(path), "dir")

    def delete(self, item) -> bool:
        """
        删除测试目标文件
        """
        with self.lock:
            self.items.pop(item.fileid, None)
        return True

    def fs_file_skim(self, file_id, **kwargs):
        """
        返回稳定内容摘要
        """
        ids = file_id if isinstance(file_id, list) else [file_id]
        return {
            "state": True,
            "data": [{"file_id": value, "sha1": "A" * 40} for value in ids],
        }

    def fs_copy(self, ids, pid, **kwargs):
        """
        复制后分配新的 ID 和 pickcode
        """
        with self.lock:
            self.calls.append(("copy", list(ids)))
            folder = self.items[str(pid)]
            for file_id in ids:
                source = self.items[file_id]
                self.add(str(Path(folder.path) / source.name))
            if self.fail_observation_after_copy:
                self.query_failed = True
            if self.timeout_after_copy:
                raise TimeoutError("injected response loss")
            return {"state": True}

    def fs_move(self, ids, pid, **kwargs):
        """
        批量移动时保留文件身份
        """
        with self.lock:
            self.calls.append(("move", list(ids)))
            folder = self.items[str(pid)]
            for file_id in ids:
                item = self.items[file_id]
                item.path = str(Path(folder.path) / item.name)
            return {"state": True}

    def fs_rename(self, pairs, **kwargs):
        """
        批量重命名，可在修改前注入失败
        """
        with self.lock:
            self.calls.append(("rename", [file_id for file_id, _ in pairs]))
            if self.fail_rename:
                raise ConnectionError("injected rename failure")
            for file_id, name in pairs:
                item = self.items[file_id]
                item.path = str(Path(item.path).parent / name)
                item.name = name
            return {"state": True}


def run_contracts():
    """
    在已初始化的隔离宿主内运行批量执行契约
    """
    import unittest

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BatchTransferContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("批量整理持久执行契约失败")
    return result.testsRun
