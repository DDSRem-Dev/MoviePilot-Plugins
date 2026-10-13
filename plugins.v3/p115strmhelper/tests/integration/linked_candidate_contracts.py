from contextlib import ExitStack
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any
from unittest.mock import Mock, patch


class LinkedCandidateContracts:
    """
    对照真实宿主验证关联发现、独立结算及失败恢复
    """

    def _candidate_planner(self, source: Any, **overrides: Any) -> Any:
        from app.chain.transfer import TransferChain
        from app.chain.transfer.request import _TransferCandidatePlanner
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo

        chain = object.__new__(TransferChain)
        with patch.object(TransferChain, "_TransferChain__init", return_value=True):
            TransferChain.__init__(chain)
        self.addCleanup(chain.close_workers)
        chain.download_history_repository = Mock()
        chain._resolve_download_history = Mock(return_value=None)
        chain._get_subscribe_custom_words = Mock(return_value=None)
        options = dict(
            meta=None,
            season=None,
            formater=None,
            batch_mtype=MediaType.MOVIE,
            mediainfo=MediaInfo(title="星际穿越", type=MediaType.MOVIE),
            continue_callback=None,
            has_episode_format_template=False,
            transfer_exclude_words=[],
            download_hash=None,
            sync_extra_files=False,
            fileitem=source,
        )
        options.update(overrides)
        return _TransferCandidatePlanner(chain, **options)

    def _plan_candidates(self, planner: Any, items: Any, linked: bool = True) -> Any:
        from app.chain.storage import StorageChain
        from app.plugins.p115strmhelper.patch.transfer_chain import _linked_request

        token = _linked_request.set(linked)
        try:
            with (
                patch.object(
                    StorageChain,
                    "get_parent_item",
                    side_effect=lambda item: self.storage.get_folder(
                        Path(item.path).parent
                    ),
                ),
                patch.object(
                    StorageChain,
                    "list_files",
                    side_effect=lambda folder, **kwargs: self.storage.list(folder),
                ),
            ):
                return planner._plan_file_items(items)
        finally:
            _linked_request.reset(token)

    def test_linked_candidates_respect_filters_and_identity(self) -> None:
        """
        单视频发现同媒体附件，屏蔽词、隐藏文件及不同年份不被重新加入
        """
        source = self.storage.add("/source/Interstellar.2014.1080p.mkv")
        matching = self.storage.add("/source/Interstellar.2014.720p.zh-cn.srt")
        exact = self.storage.add("/source/Interstellar.2014.1080p.flac")
        blocked = self.storage.add("/source/Interstellar.2014.blocked.srt")
        wrong_year = self.storage.add("/source/Interstellar.2020.srt")
        hidden = self.storage.add("/source/.Interstellar.2014.srt")
        planner = self._candidate_planner(source, transfer_exclude_words=["blocked"])
        planned, inherited = self._plan_candidates(planner, [(source, False)])
        paths = {item.path for item, _ in planned}
        self.assertEqual(paths, {source.path, matching.path, exact.path})
        self.assertIn((matching.storage, matching.path), inherited)
        self.assertFalse(paths & {blocked.path, wrong_year.path, hidden.path})
        independent, _ = self._plan_candidates(planner, [(source, False)], linked=False)
        self.assertNotIn(matching.path, {item.path for item, _ in independent})

    def test_linked_candidates_keep_explicit_orphan_and_episode_rules(self) -> None:
        """
        未归属附件保持独立，归属匹配复用手动季和官方分集模板
        """
        from app.application.formatting import FormatParser
        from app.schemas.types import MediaType

        source = self.storage.add("/source/Show - 01.mkv")
        matching = self.storage.add("/source/Show - 01.srt")
        other = self.storage.add("/source/Show - 02.srt")
        planner = self._candidate_planner(
            source,
            batch_mtype=MediaType.TV,
            season=2,
            formater=FormatParser(eformat="Show - {ep}.{ext}", offset="+3"),
            has_episode_format_template=True,
        )
        planned, inherited = self._plan_candidates(planner, [(source, False)])
        self.assertEqual(
            {item.path for item, _ in planned}, {source.path, matching.path}
        )
        meta = inherited[(matching.storage, matching.path)]
        self.assertEqual(meta.begin_season, 2)
        self.assertEqual(meta.begin_episode, 4)
        standalone, _ = self._plan_candidates(planner, [(other, False)])
        self.assertEqual([item.path for item, _ in standalone], [other.path])

    def test_linked_plans_use_native_subtitle_names(self) -> None:
        """
        关联模式字幕沿用官方繁体标签和不重命名配置
        """
        from app.application.transfer.models import TransferPlanningInput
        from app.modules.filemanager.transhandler import TransHandler
        from app.plugins.p115strmhelper.patch.transfer_chain import _context
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo, MetaInfoPath

        source = self.storage.add("/source/Interstellar.2014.繁体中文.srt")
        token = _context.set((self.chain, object()))
        try:
            for rename in (False, True):
                checkpoint = TransHandler().plan_transfer(
                    TransferPlanningInput(
                        source_fileitem=source.model_dump(mode="json")
                    ),
                    meta=MetaInfoPath(Path(source.path)),
                    mediainfo=MediaInfo(
                        title="星际穿越", year="2014", type=MediaType.MOVIE
                    ),
                    source_oper=self.storage,
                    target_storage=source.storage,
                    target_path=Path("/target"),
                    transfer_type="copy",
                    need_scrape=False,
                    need_rename=rename,
                    need_notify=False,
                    overwrite_mode="always",
                    episodes_info=None,
                    preview=True,
                )
                self.assertIsNone(checkpoint.skip_reason)
                self.assertEqual(len(checkpoint.items), 1)
                if rename:
                    self.assertIn(".zh-tw.srt", checkpoint.final_target_path)
                    self.assertNotIn(".chi.zh-cn", checkpoint.final_target_path)
                else:
                    self.assertEqual(
                        checkpoint.final_target_path, "/target/" + source.name
                    )
        finally:
            _context.reset(token)

    def test_linked_failure_keeps_native_success_and_retry(self) -> None:
        """
        附件失败不污染主视频历史通知刮削，失败历史可直接请求持久重试
        """
        from sqlalchemy import select
        from app.application.transfer.workflow import TransferTask
        from app.chain.media import MediaChain
        from app.chain.transfer import TransferChain
        from app.chain.transfer.retry import _request_durable_transfer_retry
        from app.db.adapters.chain import TransactionalChainDurableEventWriter
        from app.db.adapters.history.transfer import (
            TransactionalTransferHistoryRepository,
        )
        from app.db.adapters.transfer.admission import (
            TransactionalTransferAdmissionRepository,
        )
        from app.db.models.transferhistory import TransferHistory
        from app.db.models.transferpending import TransferPending
        from app.db.models.outbox import OutboxMessage
        from app.modules.filemanager import FileManagerModule
        from app.plugins.p115strmhelper.core.config import configer
        from app.schemas.system import TransferDirectoryConf
        from app.schemas.types import MediaType
        from app.sdk.media import MediaInfo, MetaInfoPath

        source = self.storage.add("/source/Interstellar.2014.mkv")
        subtitle = self.storage.add("/source/Interstellar.2014.srt")
        planner = self._candidate_planner(source)
        planned, inherited = self._plan_candidates(planner, [(source, False)])
        self.assertEqual(len(planned), 2)
        media = MediaInfo(title="星际穿越", year="2014", type=MediaType.MOVIE)
        chain = object.__new__(TransferChain)
        with patch.object(TransferChain, "_TransferChain__init", return_value=True):
            TransferChain.__init__(chain)
        self.addCleanup(chain.close_workers)
        admissions = TransactionalTransferAdmissionRepository(self.factory)
        chain.transfer_admission_repository = admissions
        chain._transfer_admissions = admissions
        chain.transfer_execution_repository = self.repository
        chain._transfer_executions = self.repository
        chain.transfer_history_repository = TransactionalTransferHistoryRepository(
            sync_session=self.factory, async_session=Mock()
        )
        chain.durable_event_writer = TransactionalChainDurableEventWriter(self.factory)
        chain._module_dispatcher = Mock()
        chain._module_dispatcher.freeze_plugin_providers.return_value = ()
        module = FileManagerModule()
        chain.plan_transfer = module.plan_transfer
        chain.run_module = lambda name, **kwargs: getattr(module, name)(**kwargs)
        chain._TransferChain__select_storage_oper = lambda storage: self.storage
        chain.send_transfer_message = Mock()
        chain.queue_failed_transfer_notification = Mock()
        chain.notify_successful_transfer = Mock()
        chain._record_scrape_target = Mock(wraps=chain._record_scrape_target)
        chain._send_metadata_scrape_event = Mock()
        directory = TransferDirectoryConf(
            library_path="/target",
            library_storage=source.storage,
            transfer_type="copy",
            renaming=False,
            notify=True,
            scraping=True,
        )
        self.storage.reject_copy_ids.add(subtitle.fileid)
        tasks = []
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(configer, "pan_transfer_linked_subtitle_audio", True)
            )
            stack.enter_context(
                patch.object(MediaChain, "supplement_tmdb_info", return_value=media)
            )
            stack.enter_context(
                patch.object(self.handler, "supports", return_value=True)
            )
            stack.enter_context(
                patch("app.chain.transfer.execution.max_failed_retries", return_value=0)
            )
            try:
                for item, _ in planned:
                    task = TransferTask(
                        fileitem=item,
                        meta=inherited.get((item.storage, item.path))
                        or MetaInfoPath(Path(item.path)),
                        mediainfo=media,
                        target_directory=directory,
                        target_storage=source.storage,
                        transfer_type="copy",
                        transfer_batch_id="linked-native-parity",
                        scrape=True,
                    )
                    tasks.append(task)
                    self.assertTrue(chain.put_to_queue(task))
                deadline = monotonic() + 60
                while monotonic() < deadline and chain._queue.unfinished_tasks:
                    Event().wait(0.05)
                self.assertEqual(chain._queue.unfinished_tasks, 0)
                self.assertTrue(all(task.terminal_settled for task in tasks))
                with self.factory() as session:
                    histories = {
                        row.src: row for row in session.scalars(select(TransferHistory))
                    }
                    self.assertTrue(histories[source.path].status)
                    self.assertFalse(histories[subtitle.path].status)
                    failed_id = histories[subtitle.path].id
                    self.assertEqual(
                        histories[subtitle.path].transfer_task_id,
                        tasks[1].admission_task_id,
                    )
                    self.assertEqual(
                        len(list(session.scalars(select(TransferPending)))), 1
                    )
                    topics = [
                        row.topic for row in session.scalars(select(OutboxMessage))
                    ]
                    self.assertIn("transfer.completed", topics)
                    self.assertIn("transfer.subtitle.failed", topics)
                    self.assertNotIn("transfer.failed", topics)
                self.assertEqual(chain.notify_successful_transfer.call_count, 1)
                self.assertEqual(
                    chain.notify_successful_transfer.call_args.args[0].fileitem.path,
                    source.path,
                )
                self.assertEqual(chain._record_scrape_target.call_count, 1)
                targets = chain._scrape_batches["linked-native-parity"]["targets"]
                self.assertTrue(targets)
                self.assertTrue(chain.close_workers())
                history = chain.transfer_history_repository.get(failed_id)
                accepted, _ = _request_durable_transfer_retry(
                    history, requested_by="test", repository=self.repository
                )
                self.assertTrue(accepted)
                claims = admissions.claim_recoverable(
                    owner_id="linked-retry", limit=1, lease_seconds=300
                )
                self.assertEqual(len(claims), 1)
                claim = claims[0]
                self.plans[claim.task_id] = claim.checkpoint
                self.leases[claim.task_id] = claim.lease_token
                self.storage.reject_copy_ids.clear()
                previous = list(self.storage.calls)
                recovered = self._execute_plan(claim.task_id)
                self.assertTrue(recovered.success)
                self.assertTrue(recovered.target_item.path.endswith(".srt"))
                self.assertFalse(
                    any(
                        source.fileid in ids
                        for _, ids in self.storage.calls[len(previous) :]
                    )
                )
            finally:
                chain.close_workers()
