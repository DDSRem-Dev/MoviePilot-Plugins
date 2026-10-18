from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from threading import Barrier, Event, RLock
from time import monotonic
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import TestCase
from unittest.mock import Mock, patch


from batch_recovery_contracts import BatchRecoveryContracts
from linked_candidate_contracts import LinkedCandidateContracts


class BatchTransferContracts(
    BatchRecoveryContracts, LinkedCandidateContracts, TestCase
):
    """
    使用真实 V3 SQLite 步骤账本验证批量整理和恢复，网盘边界使用内存替身
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        创建只含空表的宿主数据库模板，避免每个场景重复建表
        """
        from sqlalchemy import create_engine
        from app.db.base import Base

        temporary = TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.database_template = Path(temporary.name) / "template.db"
        engine = create_engine(f"sqlite:///{cls.database_template}")
        try:
            Base.metadata.create_all(engine)
        finally:
            engine.dispose()

    def setUp(self) -> None:
        """
        每个场景建立独立数据库和云端文件集合
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.adapters.transfer.execution import (
            TransactionalTransferExecutionRepository,
        )
        from app.plugins.p115strmhelper.helper.transfer.durable import (
            DurableBatchTransfer,
        )
        from app.plugins.p115strmhelper.patch.transfer_chain import TransferChainPatcher

        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        database = Path(self.temporary.name) / "batch.db"
        copyfile(self.database_template, database)
        self.engine = create_engine(f"sqlite:///{database}")
        self.addCleanup(self.engine.dispose)
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

    def seed(self, name: str, mode: str = "copy") -> Any:
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

    def run_transfer(self, name: str) -> Any:
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

    def _synchronize_copies(self, count: int) -> Any:
        barrier = Barrier(count, timeout=30)
        submit = self.handler.coordinator.submit

        def synchronized(key: Any, payload: Dict[str, Any], validate: Any) -> Any:
            if payload["kind"] == "copy":
                barrier.wait()
            return submit(key, payload, validate)

        return patch.object(self.handler.coordinator, "submit", synchronized)

    def test_workers_only_claim_resolved_batch_tasks(self) -> None:
        """
        非影视、其他模式和未确认目标的任务保持宿主并发边界
        """
        from app.schemas.types import MediaType

        source = self.seed("worker-scope")
        task = SimpleNamespace(
            fileitem=source,
            target_storage=source.storage,
            transfer_type="copy",
            mediainfo=SimpleNamespace(type=MediaType.MOVIE),
            meta=SimpleNamespace(type=MediaType.TV),
            mtype=None,
            plan_checkpoint=None,
            preview=False,
        )
        eligible = lambda: self.handler.workers._eligible(SimpleNamespace(task=task))
        self.assertTrue(eligible())
        with patch.object(task, "mediainfo", None):
            self.assertTrue(eligible())
            with patch.object(task, "mtype", MediaType.MUSIC):
                self.assertFalse(eligible())
            with patch.object(task, "meta", SimpleNamespace(type=MediaType.MUSIC)):
                self.assertFalse(eligible())
            with patch.object(task, "meta", None):
                self.assertFalse(eligible())
        for change in (
            {"mediainfo": SimpleNamespace(type=MediaType.MUSIC)},
            {"transfer_type": "link"},
            {"target_storage": "local"},
            {"target_storage": None},
            {"preview": True},
        ):
            with patch.multiple(task, **change):
                self.assertFalse(eligible(), change)

    def test_settlement_recovery_resolves_cleanup_storage(self) -> None:
        """
        仅重放结算时重新取得源存储，仍执行成功移动后的清理
        """
        from app.chain.transfer import TransferChain
        from app.plugins.p115strmhelper.patch.transfer_chain import _selected

        source = self.seed("cleanup-recovery", "move")
        task = SimpleNamespace(
            fileitem=source, plan_checkpoint=self.plans["cleanup-recovery"]
        )
        chain = SimpleNamespace(
            _TransferChain__select_storage_oper=Mock(return_value=self.storage),
            jobview=SimpleNamespace(is_success=Mock(return_value=False)),
        )
        token = _selected.set({})
        try:
            TransferChain._cleanup_successful_transfer(chain, task, None, None)
        finally:
            _selected.reset(token)
        chain._TransferChain__select_storage_oper.assert_called_once_with(
            source.storage
        )
        chain.jobview.is_success.assert_called_once_with(task)

    def test_tv_batch_notification_omits_unconfigured_history_button(self) -> None:
        """
        真实宿主剧集汇总在未配置域名时仍生成有效图文通知，有链接时保留按钮
        """
        from app.chain.transfer import TransferChain
        from app.application.transfer.notifications import TransferSuccessNotification
        from app.schemas import FileItem, TransferInfo
        from app.schemas.types import ContentType, MediaType, MessageType
        from app.sdk.media import MediaInfo, MetaInfoPath

        notices = []
        media = MediaInfo(title="小林家的龙女仆", year="2017", type=MediaType.TV)
        for episode in (1, 2):
            source = self.storage.add(f"/source/Dragon.Maid.S01E{episode:02d}.mkv")
            target = self.storage.add(f"/target/Dragon.Maid.S01E{episode:02d}.mkv")
            notices.append(
                TransferSuccessNotification(
                    meta=MetaInfoPath(Path(source.path)),
                    mediainfo=media,
                    transferinfo=TransferInfo(
                        success=True,
                        fileitem=source,
                        target_item=target,
                        target_diritem=FileItem(
                            storage=source.storage, type="dir", path="/target/"
                        ),
                        transfer_type="move",
                        file_list_new=[target.path],
                        file_count=1,
                        total_size=100,
                        need_notify=True,
                    ),
                    episodes_info=None,
                    username=None,
                )
            )
        template = """{
            'title': '自定义 {{ title_year }} {{ season_episode }}',
            'text': '{{ file_count }} 个文件|{{ total_size }}'
                    '|{{ __transferinfo__.target_diritem.path }}'
        }"""
        system_config = Mock()
        system_config.get.return_value = {ContentType.OrganizeSuccess.value: template}
        self.enterContext(
            patch(
                "app.application.messaging.message.get_configured_system_config",
                return_value=system_config,
            )
        )
        chain = SimpleNamespace(
            runtime_config=SimpleNamespace(history_url=None),
            messageoper=Mock(),
            _normalize_notification_for_dispatch=(
                TransferChain._normalize_notification_for_dispatch
            ),
            _dispatch_notification_steps=Mock(),
        )
        chain.post_message = Mock(
            side_effect=lambda *args, **kwargs: TransferChain.post_message(
                chain, *args, **kwargs
            )
        )
        chain.send_transfer_message = lambda **kwargs: (
            TransferChain.send_transfer_message(chain, **kwargs)
        )
        for url in (None, "https://moviepilot.example/history"):
            chain.runtime_config.history_url = url
            chain.post_message.reset_mock()
            chain._dispatch_notification_steps.reset_mock()
            TransferChain._send_transfer_success_notifications(chain, notices)
            chain.post_message.assert_called_once()
            chain._dispatch_notification_steps.assert_called_once()
            message = chain._dispatch_notification_steps.call_args.args[0]
            self.assertEqual(message.title, "自定义 小林家的龙女仆 (2017) S01 E01-E02")
            self.assertEqual(message.text, "2 个文件|200.0B|/target/")
            self.assertEqual(message.ctype, ContentType.OrganizeSuccess)
            self.assertEqual(message.mtype, MessageType.Organize)
            self.assertEqual(message.image, media.get_message_image())
            self.assertEqual(
                message.buttons,
                [[{"text": "查看整理记录", "url": url}]] if url else None,
            )
        chain.post_message.reset_mock()
        buttons = [
            [
                {"text": "详情", "url": "https://moviepilot.example/history"},
                {"text": "操作", "callback_data": "action"},
            ],
            [{"text": "无地址", "url": None}],
        ]
        TransferChain.send_transfer_message(
            chain,
            notices[0].meta,
            media,
            notices[0].transferinfo,
            buttons=buttons,
        )
        self.assertEqual(chain.post_message.call_args.args[0].buttons, [buttons[0]])
        self.assertEqual(len(buttons), 2)
        foreign_result = notices[0].transferinfo.model_copy(
            update={
                "fileitem": notices[0].transferinfo.fileitem.model_copy(
                    update={"storage": "local"}
                )
            }
        )
        TransferChain.send_transfer_message(
            chain, notices[0].meta, media, foreign_result, buttons=buttons
        )
        self.assertEqual(chain.post_message.call_args.args[0].buttons, buttons)

    def test_terminal_marker_releases_only_settled_batch_lease(self) -> None:
        """
        仅批量任务已提交终态后停止本地续租，其他任务仍遵循宿主生命周期
        """
        from app.application.transfer.workflow import TransferTask
        from app.plugins.p115strmhelper.patch.transfer_chain import _context

        source = self.seed("terminal-marker")
        task = TransferTask(fileitem=source)
        task.bind_plan_checkpoint(self.plans["terminal-marker"])
        task.bind_admission_task_id("terminal-marker")
        task.bind_execution_lease(owner_id="batch-test", lease_token="lease")
        chain = SimpleNamespace(_TransferChain__forget_owned_lease=Mock())
        token = _context.set((chain, task))
        try:
            self.assertFalse(task.terminal_settled)
            chain._TransferChain__forget_owned_lease.assert_not_called()
            task.mark_terminal_settled()
            self.assertTrue(task.terminal_settled)
            chain._TransferChain__forget_owned_lease.assert_called_once_with(
                "terminal-marker", "lease"
            )
            chain._TransferChain__forget_owned_lease.reset_mock()
            task.bind_plan_checkpoint(
                replace(
                    self.plans["terminal-marker"],
                    items=(
                        replace(
                            self.plans["terminal-marker"].items[0], action="transfer"
                        ),
                    ),
                )
            )
            task.mark_terminal_settled()
            chain._TransferChain__forget_owned_lease.assert_not_called()
        finally:
            _context.reset(token)

    def test_missing_source_does_not_fail_other_batch_files(self) -> None:
        """
        同批某个源文件已消失时只拒绝该文件，其他文件继续合并复制
        """
        from app.chain.transfer.execution import _TransferManualReviewRequired

        sources = [self.seed(f"missing-{index}") for index in range(3)]
        del self.storage.items[sources[0].fileid]
        barrier = Barrier(3, timeout=10)
        original = self.handler.coordinator.submit
        captured = set()
        lock = RLock()

        def submit(key: Any, payload: Dict[str, Any], validate: Any) -> Any:
            with lock:
                first_capture = (
                    payload["kind"] == "capture"
                    and payload["source"].fileid not in captured
                )
                if first_capture:
                    captured.add(payload["source"].fileid)
            if first_capture:
                barrier.wait()
            return original(key, payload, validate)

        with (
            patch.object(self.handler.coordinator, "submit", submit),
            self._synchronize_copies(2),
        ):
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [
                    pool.submit(self.run_transfer, f"missing-{index}")
                    for index in range(3)
                ]
                with self.assertRaisesRegex(
                    _TransferManualReviewRequired, "源文件身份已经改变"
                ):
                    futures[0].result(timeout=10)
                for future in futures[1:]:
                    self.assertIsNotNone(future.result(timeout=10))
        copies = [ids for kind, ids in self.storage.calls if kind == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(set(copies[0]), {item.fileid for item in sources[1:]})

    def test_copy_batch_and_replay(self) -> None:
        """
        多文件复制合并 API，副本身份正确且重放不重复复制或重命名
        """
        sources = [self.seed(f"copy-{index}") for index in range(4)]
        with self._synchronize_copies(4), ThreadPoolExecutor(max_workers=4) as workers:
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

    def _execute_plan(self, name: str, **changes: Any) -> Any:
        from sqlalchemy import select
        from app.chain.transfer.execution import _DurableTransferStepRunner
        from app.db.models.transferpending import TransferPending
        from app.modules.filemanager.transhandler import TransHandler
        from app.plugins.p115strmhelper.patch.transfer_chain import _context
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo, MetaInfoPath

        plan = replace(self.plans[name], **changes)
        with self.factory() as session:
            pending = session.scalar(
                select(TransferPending).where(TransferPending.task_id == name)
            )
            pending.checkpoint_payload = plan.to_payload()
            pending.planning_input = plan.planning_input.to_payload()
            pending.input_fingerprint = plan.planning_input.fingerprint
            session.commit()
        runner = _DurableTransferStepRunner(
            task_id=name,
            lease_token=self.leases[name],
            checkpoint_fingerprint=plan.fingerprint,
            repository=self.repository,
        )
        token = _context.set((self.chain, SimpleNamespace(plan_checkpoint=plan)))
        try:
            with patch.object(self.handler, "supports", return_value=True):
                return TransHandler().execute_transfer_plan(
                    plan,
                    meta=MetaInfoPath(
                        Path(plan.planning_input.source_fileitem["path"])
                    ),
                    mediainfo=MediaInfo(title="星际穿越", type=MediaType.MOVIE),
                    source_oper=self.storage,
                    target_oper=self.storage,
                    step_runner=None if plan.preview else runner,
                )
        finally:
            _context.reset(token)

    def test_started_copy_recovers_without_duplicate(self) -> None:
        """
        云端复制成功但完成证据入库前崩溃，重建 runner 后只确认副本并续跑
        """
        from app.application.transfer.execution import TransferExecutionCommand

        self.seed("crash-copy")
        complete = TransferExecutionCommand.complete

        def crash(command: Any, **kwargs: Any) -> Any:
            if kwargs["step"].intent.kind == "materialize":
                raise SystemExit("injected process death")
            return complete(command, **kwargs)

        with patch.object(TransferExecutionCommand, "complete", crash):
            with self.assertRaises(SystemExit):
                self.run_transfer("crash-copy")
        self.assertEqual(
            self.repository.get_snapshot(task_id="crash-copy").steps[-1].state.value,
            "started",
        )
        result = self.run_transfer("crash-copy")
        self.assertEqual(result.path, "/target/crash-copy-renamed.mkv")
        self.assertEqual(sum(kind == "copy" for kind, _ in self.storage.calls), 1)

    def test_partial_batch_only_retries_failed_file(self) -> None:
        """
        一次批量请求部分落地时，成功文件完成，失败文件进入原宿主重试
        """
        from app.chain.transfer.execution import _TransferRetryDeferred

        sources = [self.seed(f"partial-{index}") for index in range(3)]
        self.storage.reject_copy_ids.add(sources[1].fileid)
        with self._synchronize_copies(3), ThreadPoolExecutor(max_workers=3) as workers:
            futures = [
                workers.submit(self.run_transfer, f"partial-{index}")
                for index in range(3)
            ]
            self.assertIsNotNone(futures[0].result())
            with self.assertRaises(_TransferRetryDeferred):
                futures[1].result()
            self.assertIsNotNone(futures[2].result())
        self.assertEqual(
            self.repository.get_snapshot(task_id="partial-1").state.value, "retry_wait"
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in self.storage.items.values()
                    if item.path.startswith("/target/")
                ]
            ),
            2,
        )

    def test_native_overwrite_modes_and_preview(self) -> None:
        """
        原生覆盖策略保持生效，预览不查询关联目录、不创建云端文件或步骤
        """
        for mode, size, expected in [
            ("never", 1, False),
            ("size", 2048, False),
            ("size", 1, True),
            ("always", 2048, True),
            ("latest", 2048, True),
        ]:
            name = f"overwrite-{mode}-{size}"
            with self.subTest(mode=mode, size=size):
                self.seed(name)
                old = self.storage.add(f"/target/{name}-renamed.mkv")
                self.storage.items[old.fileid].size = size
                result = self._execute_plan(name, overwrite_mode=mode)
                self.assertEqual(result.success, expected)
                self.assertEqual(old.fileid in self.storage.items, not expected)
                if expected:
                    steps = self.repository.get_snapshot(task_id=name).steps
                    self.assertEqual(
                        [
                            step.kind
                            for step in steps
                            if step.phase in {"transfer", "cleanup"}
                        ],
                        [
                            "stage_overwrite_target",
                            "backup_overwrite_target",
                            "promote_overwrite_target",
                            "delete_overwrite_backup",
                        ],
                    )
        self.seed("preview")
        calls = list(self.storage.calls)
        self.storage.query_failed = True
        result = self._execute_plan("preview", preview=True)
        self.assertTrue(result.success)
        self.assertEqual(calls, self.storage.calls)
        self.assertEqual(self.repository.get_snapshot(task_id="preview").steps, ())

    def test_native_overwrite_rejects_incomplete_stage(self) -> None:
        """
        批量接管下暂存大小校验仍生效，失败时保留源文件及旧目标
        """
        from app.chain.transfer.execution import _TransferManualReviewRequired

        source = self.seed("incomplete-stage", mode="move")
        target_path = Path(self.plans["incomplete-stage"].final_target_path)
        old = self.storage.add(target_path.as_posix())
        copy_item = self.storage.copy_item

        def incomplete(*args: Any) -> Any:
            item = copy_item(*args)
            self.storage.items[item.fileid].size = 1
            return item

        with patch.object(self.storage, "copy_item", side_effect=incomplete):
            with self.assertRaises(_TransferManualReviewRequired):
                self._execute_plan("incomplete-stage", overwrite_mode="always")
        self.assertEqual(self.storage.get_item_strict(target_path).fileid, old.fileid)
        self.assertIn(source.fileid, self.storage.items)
        self.assertFalse(any(kind == "rename" for kind, _ in self.storage.calls))

    def test_native_move_overwrite_recovers_staged_copy(self) -> None:
        """
        暂存凭据入库后中断保留源与旧目标，恢复后不重复复制并完成清理
        """
        from app.application.transfer.execution import TransferExecutionCommand

        name = "overwrite-recovery"
        source = self.seed(name, mode="move")
        target_path = Path(self.plans[name].final_target_path)
        old = self.storage.add(target_path.as_posix())
        complete = TransferExecutionCommand.complete

        def crash(command: Any, **kwargs: Any) -> Any:
            result = complete(command, **kwargs)
            if kwargs["step"].intent.kind == "stage_overwrite_target":
                raise SystemExit("injected process death")
            return result

        with patch.object(TransferExecutionCommand, "complete", crash):
            with self.assertRaises(SystemExit):
                self._execute_plan(name, overwrite_mode="always")
        self.assertIn(source.fileid, self.storage.items)
        self.assertEqual(self.storage.get_item_strict(target_path).fileid, old.fileid)
        result = self._execute_plan(name, overwrite_mode="always")
        self.assertTrue(result.success)
        self.assertNotIn(source.fileid, self.storage.items)
        self.assertNotIn(old.fileid, self.storage.items)
        self.assertEqual(self.storage.get_item_strict(target_path).size, source.size)
        self.assertEqual(sum(kind == "copy" for kind, _ in self.storage.calls), 1)

    def test_interception_rejects_before_cloud_write(self) -> None:
        """
        宿主整理拦截事件拒绝后，不执行复制、移动或删除
        """
        from app.modules.filemanager.transhandler import TransHandler

        self.seed("rejected")
        with patch.object(
            TransHandler,
            "_TransHandler__intercept_transfer",
            return_value=(False, "规则拒绝"),
        ):
            result = self._execute_plan("rejected")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "规则拒绝")
        self.assertEqual(self.storage.calls, [])

    def test_cleanup_protects_roots_and_remaining_media(self) -> None:
        """
        仅清理允许的源目录，保护配置根目录、其他媒体和读取异常的目录
        """
        from app.application.directory import DirectoryHelper

        self.storage.add("/downloads", "dir")
        self.storage.add("/downloads/done", "dir")
        self.storage.add("/downloads/done/poster.jpg")
        self.storage.add("/downloads/pending", "dir")
        self.storage.add("/downloads/pending/remaining.mkv")
        self.storage.add("/unconfigured", "dir")
        self.storage.add("/unconfigured/metadata", "dir")
        self.storage.add("/unconfigured/metadata/poster.jpg")
        tasks = [
            SimpleNamespace(fileitem=SimpleNamespace(storage="115网盘Plus", path=path))
            for path in [
                "/downloads/done/movie.mkv",
                "/downloads/pending/movie.mkv",
                "/unconfigured/metadata/movie.mkv",
            ]
        ]
        task = SimpleNamespace(
            fileitem=tasks[0].fileitem,
            mediainfo=None,
            meta=SimpleNamespace(begin_season=None),
        )
        chain = SimpleNamespace(
            jobview=SimpleNamespace(
                is_success=lambda task: True, success_tasks=lambda *args: tasks
            )
        )
        with patch.object(
            DirectoryHelper,
            "get_dirs",
            return_value=[
                SimpleNamespace(download_path="/downloads", library_path="/target")
            ],
        ):
            self.handler.cleaner.cleanup(chain, task, self.storage)
            self.assertIsNone(self.storage.get_item_strict(Path("/downloads/done")))
            for path in ["/downloads", "/downloads/pending", "/unconfigured/metadata"]:
                self.assertIsNotNone(self.storage.get_item_strict(Path(path)))
            calls = list(self.storage.calls)
            self.storage.query_failed = True
            self.handler.cleaner.cleanup(chain, task, self.storage)
            self.assertEqual(calls, self.storage.calls)

    def _cleanup_context(self, paths: List[str], batch: str = "cleanup") -> Any:
        tasks = [
            SimpleNamespace(fileitem=SimpleNamespace(storage="115网盘Plus", path=path))
            for path in paths
        ]
        task = SimpleNamespace(
            fileitem=tasks[0].fileitem,
            mediainfo=None,
            meta=SimpleNamespace(begin_season=None),
            transfer_batch_id=batch,
        )
        chain = SimpleNamespace(
            jobview=SimpleNamespace(
                is_success=lambda task: True,
                success_tasks=lambda *args: tasks,
            )
        )
        return chain, task

    def test_cleanup_deduplicates_episodes_and_concurrent_seasons(self) -> None:
        """
        百集及跨季并发收尾只扫描各目录两次，重复回调不再读盘
        """
        from collections import Counter
        from app.application.directory import DirectoryHelper

        self.storage.add("/downloads", "dir")
        self.storage.add("/downloads/show", "dir")
        for season in (1, 2):
            self.storage.add(f"/downloads/show/Season {season}", "dir")
        contexts = [
            self._cleanup_context(
                [
                    f"/downloads/show/Season {season}/{episode}.mkv"
                    for episode in range(100)
                ]
            )
            for season in (1, 2)
        ]
        with (
            patch.object(
                DirectoryHelper,
                "get_dirs",
                return_value=[
                    SimpleNamespace(download_path="/downloads", library_path="/target")
                ],
            ),
            patch.object(self.storage, "list", wraps=self.storage.list) as listing,
        ):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [
                    pool.submit(self.handler.cleaner.cleanup, *context, self.storage)
                    for context in contexts * 2
                ]
                for future in futures:
                    future.result(timeout=10)
            counts = Counter(call.args[0].path for call in listing.call_args_list)
            self.assertEqual(sorted(counts.values()), [2, 2, 2])
            self.assertEqual(
                len([call for call in self.storage.calls if call[0] == "delete"]), 1
            )
            self.assertIsNone(self.storage.get_item_strict(Path("/downloads/show")))
            self.assertIsNotNone(self.storage.get_item_strict(Path("/downloads")))

    def test_cleanup_revalidates_new_media_before_delete(self) -> None:
        """
        初次扫描后新出现的媒体必须阻止目录删除
        """
        from app.application.directory import DirectoryHelper

        self.storage.add("/downloads", "dir")
        self.storage.add("/downloads/show", "dir")
        context = self._cleanup_context(["/downloads/show/old.mkv"])
        original = self.storage.list
        reads = 0

        def listing(folder: Any) -> Any:
            nonlocal reads
            reads += 1
            if reads == 2:
                self.storage.add("/downloads/show/new.mkv")
            return original(folder)

        with (
            patch.object(
                DirectoryHelper,
                "get_dirs",
                return_value=[
                    SimpleNamespace(download_path="/downloads", library_path="/target")
                ],
            ),
            patch.object(self.storage, "list", side_effect=listing),
        ):
            self.handler.cleaner.cleanup(*context, self.storage)
        self.assertEqual(self.storage.calls, [])
        self.assertIsNotNone(
            self.storage.get_item_strict(Path("/downloads/show/new.mkv"))
        )

    def test_cleanup_failure_retries_and_new_batch_is_not_cached(self) -> None:
        """
        读取失败不记为已清理，同路径的新整理批次仍重新检查
        """
        from app.application.directory import DirectoryHelper

        self.storage.add("/downloads", "dir")
        self.storage.add("/downloads/show", "dir")
        context = self._cleanup_context(["/downloads/show/old.mkv"])
        with patch.object(
            DirectoryHelper,
            "get_dirs",
            return_value=[
                SimpleNamespace(download_path="/downloads", library_path="/target")
            ],
        ):
            self.storage.query_failed = True
            self.handler.cleaner.cleanup(*context, self.storage)
            self.assertEqual(self.storage.calls, [])
            self.storage.query_failed = False
            self.handler.cleaner.cleanup(*context, self.storage)
            self.assertIsNone(self.storage.get_item_strict(Path("/downloads/show")))
            self.storage.add("/downloads/show", "dir")
            context[1].transfer_batch_id = "new-batch"
            self.handler.cleaner.cleanup(*context, self.storage)
            self.assertIsNone(self.storage.get_item_strict(Path("/downloads/show")))
            self.assertEqual(len(self.storage.calls), 2)

    def test_linked_exhaustion_retains_successful_file_evidence(self) -> None:
        """
        关联文件重试耗尽后从持久步骤恢复逐文件结果，失败结算仍保留实际目标身份
        """
        from sqlalchemy import select
        from app.application.chain.events import TransferResultSettlement
        from app.application.history import add_transfer_fail
        from app.application.outbox import TRANSFER_FAILED_TOPIC
        from app.chain.transfer.execution import _TransferRetryExhausted
        from app.db.adapters.chain import TransactionalChainDurableEventWriter
        from app.db.models.transferhistory import TransferHistory
        from app.db.models.outbox import OutboxMessage
        from legacy_batch_plan import legacy_plan as extend_plan
        from app.schemas import TransferInfo
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo, MetaInfoPath

        name = "Interstellar.2014.failed"
        source = self.seed(name, "move")
        subtitle = self.storage.add(f"/source/{name}.zh-cn.srt")
        audio = self.storage.add(f"/source/{name}.flac")
        self.plans[name] = extend_plan(
            self.plans[name], ((subtitle, ".default.chi.zh-cn.srt"), (audio, ".flac"))
        )
        move = self.storage.fs_move

        def reject_audio(ids: List[str], pid: int, **kwargs: Any) -> Any:
            if audio.fileid in ids:
                raise OSError("injected audio failure")
            return move(ids, pid, **kwargs)

        with (
            patch.object(self.storage, "fs_move", reject_audio),
            patch("app.chain.transfer.execution.max_failed_retries", return_value=0),
        ):
            with self.assertRaises(_TransferRetryExhausted) as failure:
                self._execute_plan(name)
        execution = failure.exception.snapshot.checkpoint
        self.assertIsNotNone(execution)
        result = TransferInfo(
            success=False,
            fileitem=source,
            transfer_type="move",
            fail_list=[source.path],
        )
        media = MediaInfo(title="星际穿越", type=MediaType.MOVIE)
        meta = MetaInfoPath(Path(source.path))
        writer = TransactionalChainDurableEventWriter(self.factory)
        writer.transfer_result(
            topic=TRANSFER_FAILED_TOPIC,
            stage_history=lambda staging: add_transfer_fail(
                fileitem=source,
                mode="move",
                meta=meta,
                mediainfo=media,
                transferinfo=result,
                transfer_history_oper=staging,
            ),
            event_payload=dict(
                fileitem=source, transferinfo=result, meta=meta, mediainfo=media
            ),
            publish=None,
            settlement=TransferResultSettlement(
                task_id=name,
                lease_token="lease",
                execution_fingerprint=execution.fingerprint,
                outcome="failed",
                error="injected audio failure",
            ),
        )
        self.assertEqual(result.target_item.fileid, source.fileid)
        self.assertEqual(result.fail_list, [audio.path])
        self.assertEqual(len(result.fileitem.children), 2)
        with self.factory() as session:
            histories = list(session.scalars(select(TransferHistory)))
            self.assertEqual(len(histories), 3)
            self.assertEqual(len(list(session.scalars(select(OutboxMessage)))), 4)

    def test_expired_lease_cannot_write_cloud(self) -> None:
        """
        数据库租约失效后，旧任务无法开始任何云端副作用
        """
        from sqlalchemy import select
        from app.application.transfer.execution import TransferExecutionLeaseLostError
        from app.db.models.transferpending import TransferPending

        self.seed("expired")
        with self.factory() as session:
            pending = session.scalar(
                select(TransferPending).where(TransferPending.task_id == "expired")
            )
            pending.lease_token = "new-owner"
            session.commit()
        with self.assertRaises(TransferExecutionLeaseLostError):
            self.run_transfer("expired")
        self.assertEqual(self.storage.calls, [])

    def test_standalone_subtitles_execute_in_both_modes(self) -> None:
        """
        独立字幕在关联模式和普通模式均有真实执行结果，不再无条件短路
        """
        from app.plugins.p115strmhelper.helper.transfer.planning import (
            extend_plan,
            LINKED_SKIP,
        )

        self.seed("subtitle")
        source = self.storage.add("/source/Interstellar.zh-cn.srt")
        plan = self.plans["subtitle"]
        data = source.model_dump(mode="json")
        plan = replace(
            plan,
            planning_input=replace(plan.planning_input, source_fileitem=data),
            final_target_path="/target/Interstellar.zh-cn.srt",
            items=(
                replace(
                    plan.items[0],
                    source_fileitem=data,
                    target_path="/target/Interstellar.zh-cn.srt",
                ),
            ),
        )
        self.plans["subtitle"] = extend_plan(plan)
        result = self._execute_plan("subtitle")
        self.assertTrue(result.success)
        self.assertNotEqual(result.message, LINKED_SKIP)
        self.assertIsNotNone(result.target_item)
        self.plans["subtitle"] = extend_plan(plan)
        result = self._execute_plan("subtitle")
        self.assertTrue(result.success)
        self.assertNotEqual(result.target_item.fileid, source.fileid)

    def test_legacy_skipped_attachment_executes_without_false_success(self) -> None:
        """
        升级前尚未执行的附件跳过计划恢复为真实操作，不再写无目标成功
        """
        from legacy_batch_plan import legacy_plan

        self.seed("legacy-subtitle")
        source = self.storage.add("/source/Interstellar.2014.srt")
        plan = self.plans["legacy-subtitle"]
        data = source.model_dump(mode="json")
        plan = replace(
            plan,
            planning_input=replace(plan.planning_input, source_fileitem=data),
            items=(replace(plan.items[0], source_fileitem=data),),
            final_target_path="/target/Interstellar.2014.srt",
        )
        self.plans["legacy-subtitle"] = legacy_plan(plan, skip=True)
        result = self._execute_plan("legacy-subtitle")
        self.assertTrue(result.success)
        self.assertEqual(result.target_item.path, plan.final_target_path)
        self.assertTrue(self.storage.calls)

    def test_shutdown_waits_for_native_task_between_batches(self) -> None:
        """
        批次间隙仍有原宿主任务时停止返回未完成，结束后可再次停止并恢复队列
        """
        with self.handler.operation():
            self.assertFalse(self.handler.shutdown(timeout=0))
        self.assertTrue(self.handler.shutdown(timeout=1))
        with self.assertRaises(RuntimeError):
            with self.handler.operation():
                self.fail("关闭后不应接收新任务")

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
        from legacy_batch_plan import legacy_plan as extend_plan
        from app.plugins.p115strmhelper.patch.transfer_chain import _context
        from app.sdk.media import MediaInfo, MetaInfoPath
        from app.schemas.types import MediaType

        source = self.seed("Interstellar.2014")
        subtitle = self.storage.add("/source/Interstellar.2014.zh-cn.srt")
        audio = self.storage.add("/source/Interstellar.2014.flac")
        plan = extend_plan(
            self.plans["Interstellar.2014"],
            ((subtitle, ".default.chi.zh-cn.srt"), (audio, ".flac")),
        )
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

        from app.db.adapters.outbox import SqlAlchemyOutboxStager

        with patch.object(
            SqlAlchemyOutboxStager,
            "stage",
            side_effect=RuntimeError("injected transaction failure"),
        ):
            with self.assertRaises(RuntimeError):
                write()
        with self.factory() as session:
            self.assertEqual(list(session.scalars(select(TransferHistory))), [])
            self.assertEqual(list(session.scalars(select(OutboxMessage))), [])
            self.assertIsNotNone(session.scalar(select(TransferPending)))
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
        self._check_native_queue(recognized=True)

    def test_unrecognized_video_queue_batches_without_explicit_media_type(self) -> None:
        """
        仅有文件名解析类型的普通整理请求仍能合并真实宿主任务
        """
        self._check_native_queue(recognized=False)

    def test_restarted_queue_recovers_multiple_batch_plans(self) -> None:
        """
        原生恢复入口在单个常规 worker 下仍领取并批量执行多个持久计划
        """
        self._check_native_queue(recognized=True, recovery=True)

    def _check_native_queue(self, recognized: bool, recovery: bool = False) -> None:
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
        from app.application.transfer.workflow import TransferTask
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
        settled_leases = []

        def after_settlement(task: Any, result: Any) -> None:
            settled_leases.append(
                (task.terminal_settled, task.admission_task_id in chain._owned_leases)
            )
            chain._TransferChain__heartbeat_owned_leases()

        chain.notify_successful_transfer = Mock(side_effect=after_settlement)
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
            stack.enter_context(self._synchronize_copies(4))
            stack.enter_context(
                patch.object(configer, "pan_transfer_linked_subtitle_audio", False)
            )
            stack.enter_context(
                patch.object(MediaChain, "supplement_tmdb_info", return_value=media)
            )
            stack.enter_context(
                patch.object(MediaChain, "recognize_by_meta", return_value=media)
            )
            stack.enter_context(
                patch.object(self.handler, "supports", return_value=True)
            )
            try:
                for index in range(4):
                    name = f"Interstellar.2014.part{index}"
                    source = (
                        self.seed(name)
                        if recovery
                        else self.storage.add(f"/source/{name}.mkv")
                    )
                    task = TransferTask(
                        fileitem=source,
                        meta=MetaInfoPath(Path(source.path)),
                        mediainfo=media if recognized else None,
                        target_directory=directory,
                        target_storage="115网盘Plus",
                        transfer_type="copy",
                        transfer_batch_id="native-batch",
                    )
                    tasks.append(task)
                    if recovery:
                        task.bind_admission_task_id(name)
                        plan = replace(
                            self.plans[name],
                            resolved_meta=chain._TransferChain__json_snapshot(
                                task.meta
                            ),
                            resolved_meta_kind=type(task.meta).__name__,
                            resolved_mediainfo=chain._TransferChain__json_snapshot(
                                media
                            ),
                            resolved_mediainfo_kind=type(media).__name__,
                        )
                        with self.factory() as session:
                            row = session.scalar(
                                select(TransferPending).where(
                                    TransferPending.task_id == name
                                )
                            )
                            row.checkpoint_payload = plan.to_payload()
                            row.lease_expires_at = "2000-01-01 00:00:00.000000"
                            session.commit()
                    else:
                        self.assertTrue(chain.put_to_queue(task))
                if recovery:
                    chain._TransferChain__replay_pending()
                deadline = monotonic() + 60
                while monotonic() < deadline and chain._queue.unfinished_tasks:
                    Event().wait(0.05)
                self.assertEqual(chain._queue.unfinished_tasks, 0)
                if not recovery:
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
                self.assertEqual(chain.notify_successful_transfer.call_count, 4)
                self.assertEqual(settled_leases, [(True, False)] * 4)
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
        self.reject_copy_ids = set()
        self.add("/source", "dir")
        self.add("/target", "dir")

    def add(self, path: str, kind: str = "file") -> Any:
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
                modify_time=1700000000,
            )
            self.items[item.fileid] = item
            return item.model_copy(deep=True)

    def get_item_strict(self, path: Path) -> Optional[Any]:
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
                    if item.path == path.as_posix()
                ),
                None,
            )

    def list(self, folder: Any) -> List[Any]:
        """
        返回目录的云端实时内容
        """
        with self.lock:
            if self.query_failed:
                raise ConnectionError("injected query failure")
            return [
                item.model_copy(deep=True)
                for item in self.items.values()
                if Path(item.path).parent.as_posix() == folder.path
            ]

    def get_folder(self, path: Path) -> Any:
        """
        获取或创建测试目录
        """
        return self.get_item_strict(path) or self.add(path.as_posix(), "dir")

    @staticmethod
    def is_support_transtype(transfer_type: str) -> bool:
        """
        声明宿主可执行的同存储整理方式
        """
        return transfer_type in {"copy", "move"}

    def copy_item(self, item: Any, path: Path, name: str) -> Any:
        """
        模拟宿主存储适配器复制并返回新文件身份
        """
        with self.lock:
            self.calls.append(("copy", [item.fileid]))
            copied = self.add((path / name).as_posix())
            self.items[copied.fileid].size = item.size
            return self.items[copied.fileid].model_copy(deep=True)

    def rename(self, item: Any, name: str) -> bool:
        """
        模拟宿主存储适配器同目录重命名
        """
        return self.fs_rename([(item.fileid, name)])["state"]

    def delete(self, item: Any) -> bool:
        """
        删除测试目标文件
        """
        with self.lock:
            self.items.pop(item.fileid, None)
        return True

    def fs_file_skim(self, file_id: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        返回稳定内容摘要
        """
        ids = file_id if isinstance(file_id, list) else [file_id]
        return {
            "state": True,
            "data": [{"file_id": value, "sha1": "A" * 40} for value in ids],
        }

    def fs_copy(self, ids: List[str], pid: int, **kwargs: Any) -> Dict[str, Any]:
        """
        复制后分配新的 ID 和 pickcode
        """
        with self.lock:
            self.calls.append(("copy", list(ids)))
            folder = self.items[str(pid)]
            for file_id in ids:
                if file_id in self.reject_copy_ids:
                    continue
                source = self.items[file_id]
                self.add((Path(folder.path) / source.name).as_posix())
            if self.fail_observation_after_copy:
                self.query_failed = True
            if self.timeout_after_copy:
                raise TimeoutError("injected response loss")
            return {"state": True}

    def fs_delete(self, ids: List[str], **kwargs: Any) -> Dict[str, Any]:
        """
        删除指定目录及其子文件
        """
        self.calls.append(("delete", list(ids)))
        roots = [Path(self.items[file_id].path) for file_id in ids]
        for file_id, item in list(self.items.items()):
            if any(Path(item.path).is_relative_to(root) for root in roots):
                del self.items[file_id]
        return {"state": True}

    def fs_move(self, ids: List[str], pid: int, **kwargs: Any) -> Dict[str, Any]:
        """
        批量移动时保留文件身份
        """
        with self.lock:
            self.calls.append(("move", list(ids)))
            folder = self.items[str(pid)]
            for file_id in ids:
                item = self.items[file_id]
                item.path = (Path(folder.path) / item.name).as_posix()
            return {"state": True}

    def fs_rename(self, pairs: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        批量重命名，可在修改前注入失败
        """
        with self.lock:
            self.calls.append(("rename", [file_id for file_id, _ in pairs]))
            if self.fail_rename:
                raise ConnectionError("injected rename failure")
            for file_id, name in pairs:
                item = self.items[file_id]
                item.path = (Path(item.path).parent / name).as_posix()
                item.name = name
            return {"state": True}


def run_contracts() -> int:
    """
    在已初始化的隔离宿主内运行批量执行契约
    """
    import unittest

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BatchTransferContracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("批量整理持久执行契约失败")
    return result.testsRun
