from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Dict, Iterator, Optional, Set, Tuple

from app.sdk.logging import logger

from ..core.config import configer


_context: ContextVar[Optional[Tuple[Any, Any]]] = ContextVar(
    "p115_batch_transfer_context", default=None
)
_selected: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "p115_batch_storage_selection", default=None
)
_linked_request: ContextVar[bool] = ContextVar("p115_linked_request", default=False)


class TransferChainPatcher:
    """
    保留 V3 原任务生命周期，仅替换可合并的文件操作及关联文件计划
    """

    _enabled = False
    _storage_module = ""
    _handler = None
    _originals: Dict[Tuple[Any, str], Any] = {}
    _lock = RLock()
    _path_locks: Dict[Tuple[str, str], Any] = {}

    @classmethod
    def enable(cls, task_manager: Any, handler: Any, storage_module: str) -> None:
        """
        安装与当前 V3 计划、步骤执行和原子结算契约对应的补丁
        """
        from app.chain.transfer import TransferChain
        from app.chain.transfer.request import _TransferCandidatePlanner
        from app.db.adapters.chain import TransactionalChainDurableEventWriter
        from app.db.adapters.transfer.execution import (
            TransactionalTransferExecutionRepository,
        )
        from app.modules.filemanager.transhandler import TransHandler
        from app.application.transfer.workflow import TransferTask
        from app.schemas.types import MediaType

        from ..helper.transfer.linked_candidates import plan_linked_candidates
        from ..helper.transfer.planning import (
            LINKED_SKIP,
            MAIN_ACTION,
            execute_plan,
            extend_plan,
            restore_skipped_plan,
        )
        from ..helper.transfer.recovery import claim_batch_recovery
        from ..helper.transfer.settlement import stage_linked_results
        from ..helper.transfer.validation import validate_batch_intent

        with cls._lock:
            if cls._enabled:
                return
            cls._handler = handler
            cls._storage_module = storage_module
            original_handle = TransferChain._TransferChain__handle_transfer
            original_workflow = TransferChain._run_transfer_workflow
            workflow_signature = signature(original_workflow)
            original_candidates = _TransferCandidatePlanner._plan_file_items
            original_plan = TransHandler.plan_transfer
            original_execute = TransHandler.execute_transfer_plan
            original_step = TransHandler._TransHandler__execute_transfer_with_steps
            original_settle = TransactionalChainDurableEventWriter.transfer_result
            original_recovery = TransferChain._TransferChain__claim_recovery_batch
            original_enqueue = TransferChain._enqueue_transfer_task
            original_message = TransferChain.send_transfer_message
            message_signature = signature(original_message)
            original_terminal = TransferTask.mark_terminal_settled
            original_cleanup = TransferChain._cleanup_successful_transfer
            original_complete = (
                TransferChain._TransferChain__mark_torrent_completed_if_done
            )
            original_validate = (
                TransactionalTransferExecutionRepository._intent_belongs_to_checkpoint
            )

            def validate(checkpoint: Any, **kwargs: Any) -> bool:
                return validate_batch_intent(original_validate, checkpoint, **kwargs)

            @wraps(original_workflow)
            def workflow(chain: Any, *args: Any, **kwargs: Any) -> Any:
                arguments = workflow_signature.bind(chain, *args, **kwargs).arguments
                source = arguments.get("fileitem")
                directory = arguments.get("target_directory")
                target = arguments.get("target_storage") or getattr(
                    directory, "library_storage", None
                )
                mode = arguments.get("transfer_type") or getattr(
                    directory, "transfer_type", None
                )
                enabled = bool(
                    configer.pan_transfer_linked_subtitle_audio
                    and source
                    and source.storage == storage_module
                    and target in (None, storage_module)
                    and mode in (None, "move", "copy")
                )
                token = _linked_request.set(enabled)
                try:
                    return original_workflow(chain, *args, **kwargs)
                finally:
                    _linked_request.reset(token)

            @wraps(original_candidates)
            def candidates(planner: Any, items: Any) -> Any:
                if not _linked_request.get():
                    return original_candidates(planner, items)
                return plan_linked_candidates(original_candidates, planner, items)

            def is_batch_task(task: Any) -> bool:
                checkpoint = task.plan_checkpoint
                return bool(
                    checkpoint
                    and (
                        checkpoint.skip_reason == LINKED_SKIP
                        or checkpoint.items
                        and checkpoint.items[0].action == MAIN_ACTION
                    )
                )

            @wraps(original_message)
            def message(chain: Any, *args: Any, **kwargs: Any) -> Any:
                bound = message_signature.bind(chain, *args, **kwargs)
                result = bound.arguments.get("transferinfo")
                media = bound.arguments.get("mediainfo")
                buttons = bound.arguments.get("buttons")
                if (
                    bound.arguments.get("batch")
                    and buttons
                    and result.fileitem
                    and result.target_item
                    and result.transfer_type in {"move", "copy"}
                    and media.type in {MediaType.MOVIE, MediaType.TV}
                    and cls._should_intercept(
                        result.fileitem.storage, result.target_item.storage
                    )
                ):
                    rows = [
                        [
                            button
                            for button in row
                            if "url" not in button or button.get("url")
                        ]
                        for row in buttons
                    ]
                    bound.arguments["buttons"] = [row for row in rows if row] or None
                return original_message(*bound.args, **bound.kwargs)

            @wraps(original_terminal)
            def terminal_settled(task: Any) -> None:
                original_terminal(task)
                context = _context.get()
                if context and context[1] is task and is_batch_task(task):
                    if task.admission_task_id and task.lease_token:
                        context[0]._TransferChain__forget_owned_lease(
                            task.admission_task_id, task.lease_token
                        )

            @wraps(original_cleanup)
            def cleanup(chain: Any, task: Any, transferhis: Any, history: Any) -> None:
                if not is_batch_task(task):
                    return original_cleanup(chain, task, transferhis, history)
                selected = _selected.get() or {}
                source_oper = selected.get("source")
                if source_oper is None:
                    source_oper = chain._TransferChain__select_storage_oper(
                        task.fileitem.storage
                    )
                handler.cleaner.cleanup(chain, task, source_oper)

            @wraps(original_complete)
            def completed(chain: Any, *args: Any, **kwargs: Any) -> Any:
                context = _context.get()
                if context and is_batch_task(context[1]):
                    return None
                return original_complete(chain, *args, **kwargs)

            @wraps(original_recovery)
            def recovery(chain: Any) -> Any:
                return claim_batch_recovery(
                    chain, handler.workers, original_recovery(chain)
                )

            @wraps(original_enqueue)
            def enqueue(chain: Any, item: Any) -> None:
                original_enqueue(chain, item)
                handler.workers.ensure(chain)

            @wraps(original_handle)
            def handle(chain: Any, task: Any, callback: Any = None) -> Any:
                token = _context.set((chain, task))
                selected_token = _selected.set({})
                try:
                    if (
                        task.fileitem.storage == storage_module
                        and task.fileitem.type == "file"
                    ):
                        with handler.operation():
                            handler.workers.ensure(chain)
                            return original_handle(chain, task, callback)
                    return original_handle(chain, task, callback)
                finally:
                    _selected.reset(selected_token)
                    _context.reset(token)

            @wraps(original_plan)
            def plan(owner: Any, planning_input: Any, **kwargs: Any) -> Any:
                checkpoint = original_plan(owner, planning_input, **kwargs)
                context = _context.get()
                source = planning_input.source_fileitem
                if (
                    context is None
                    or not cls._should_intercept(
                        source.get("storage"), checkpoint.target_storage
                    )
                    or source.get("type") != "file"
                    or checkpoint.resolved_transfer_type not in {"move", "copy"}
                    or kwargs["mediainfo"].type == MediaType.MUSIC
                ):
                    return checkpoint
                return extend_plan(checkpoint)

            @wraps(original_execute)
            def execute(owner: Any, checkpoint: Any, **kwargs: Any) -> Any:
                checkpoint = restore_skipped_plan(checkpoint)
                if not checkpoint.items or checkpoint.items[0].action != MAIN_ACTION:
                    return original_execute(owner, checkpoint, **kwargs)
                context = _context.get()
                if (
                    context is None
                    or not is_batch_task(context[1])
                    or kwargs.get("step_runner") is None
                    and not checkpoint.preview
                ):
                    raise RuntimeError("批量整理缺少原宿主持久任务上下文")
                selected = _selected.get()
                if selected is not None:
                    selected["source"] = kwargs["source_oper"]
                keys = set()
                for item in checkpoint.items:
                    target = Path(item.target_path)
                    keys.add((checkpoint.target_storage, str(target)))
                    keys.add(
                        (
                            item.source_fileitem["storage"],
                            str(Path(item.source_fileitem["path"])),
                        )
                    )
                    keys.add(
                        (
                            checkpoint.target_storage,
                            str(
                                target.parent / Path(item.source_fileitem["path"]).name
                            ),
                        )
                    )
                with cls._lock_paths(keys):
                    return execute_plan(original_execute, owner, checkpoint, **kwargs)

            def step(owner: Any, **kwargs: Any) -> Any:
                context = _context.get()
                source = kwargs["source_fileitem"]
                if (
                    context is None
                    or not is_batch_task(context[1])
                    or kwargs.get("step_runner") is None
                    or not cls._should_intercept(
                        source.get("storage"), kwargs["target_storage"]
                    )
                    or source.get("type") != "file"
                    or kwargs["transfer_type"] not in {"move", "copy"}
                    or not handler.supports(
                        kwargs["source_oper"], kwargs["target_oper"]
                    )
                ):
                    return original_step(**kwargs)
                chain, task = context
                return handler.execute(chain=chain, task=task, **kwargs)

            @wraps(original_settle)
            def settle(writer: Any, **kwargs: Any) -> Any:
                return stage_linked_results(original_settle, writer, **kwargs)

            cls._install(TransferChain, "_TransferChain__handle_transfer", handle)
            cls._install(TransferChain, "_run_transfer_workflow", workflow)
            cls._install(_TransferCandidatePlanner, "_plan_file_items", candidates)
            cls._install(TransferChain, "_enqueue_transfer_task", enqueue)
            cls._install(
                TransferChain, "_TransferChain__claim_recovery_batch", recovery
            )
            cls._install(TransferChain, "_cleanup_successful_transfer", cleanup)
            cls._install(TransferTask, "mark_terminal_settled", terminal_settled)
            cls._install(TransferChain, "send_transfer_message", message)
            cls._install(
                TransferChain,
                "_TransferChain__mark_torrent_completed_if_done",
                completed,
            )
            cls._install(TransHandler, "plan_transfer", plan)
            cls._install(TransHandler, "execute_transfer_plan", execute)
            cls._install(
                TransHandler,
                "_TransHandler__execute_transfer_with_steps",
                classmethod(step),
            )
            cls._install(
                TransactionalChainDurableEventWriter, "transfer_result", settle
            )
            cls._install(
                TransactionalTransferExecutionRepository,
                "_intent_belongs_to_checkpoint",
                staticmethod(validate),
            )
            cls._enabled = True
            logger.info("【整理接管】已启用 V3 持久任务批量执行")

    @classmethod
    def _install(cls, owner: Any, name: str, replacement: Any) -> None:
        from inspect import getattr_static

        cls._originals[(owner, name)] = getattr_static(owner, name)
        setattr(owner, name, replacement)

    @classmethod
    @contextmanager
    def _lock_paths(cls, keys: Set[Tuple[str, str]]) -> Iterator[None]:
        with cls._lock:
            entries = []
            for key in sorted(keys):
                entry = cls._path_locks.setdefault(key, [Lock(), 0])
                entry[1] += 1
                entries.append((key, entry))
        try:
            with ExitStack() as stack:
                for _, entry in entries:
                    stack.enter_context(entry[0])
                yield
        finally:
            with cls._lock:
                for key, entry in entries:
                    entry[1] -= 1
                    if not entry[1]:
                        del cls._path_locks[key]

    @classmethod
    def disable(cls) -> None:
        """
        恢复宿主方法，已经进入批量执行的调用继续持有原执行器
        """
        with cls._lock:
            for (owner, name), original in reversed(list(cls._originals.items())):
                setattr(owner, name, original)
            cls._originals.clear()
            cls._enabled = False
            cls._handler = None
            cls._storage_module = ""
            logger.info("【整理接管】V3 批量补丁已关闭")

    @classmethod
    def _should_intercept(cls, source_storage: str, target_storage: str) -> bool:
        return bool(
            cls._enabled
            and cls._storage_module
            and source_storage == cls._storage_module
            and target_storage == cls._storage_module
        )
