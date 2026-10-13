from contextlib import contextmanager
from pathlib import Path
from threading import Condition
from time import monotonic
from typing import Any, Dict, Iterator, List, Optional, Tuple

from p115client import check_response

from app.application.transfer.execution import (
    TransferOperationObservation,
    TransferOperationObservationState,
    TransferStepResult,
)
from app.schemas import FileItem
from app.sdk.logging import logger

from ...core.config import configer
from .batch import BatchCoordinator, BatchOperation
from .cache_updater import CacheUpdater
from .cleanup import SourceDirectoryCleaner
from .diagnostics import log_batch
from .workers import BatchWorkers


class DurableBatchTransfer:
    """
    在原任务持久步骤内合并网盘操作，分别确认落地和重命名结果
    """

    def __init__(self, delay: float = 0.25, max_size: int = 500) -> None:
        self.coordinator = BatchCoordinator(self._execute_batch, delay, max_size)
        self.workers = BatchWorkers("115网盘Plus", max_size)
        self.cleaner = SourceDirectoryCleaner()
        self._condition = Condition()
        self._active = 0
        self._closing = False

    @contextmanager
    def operation(self) -> Iterator[None]:
        """
        登记整个原任务执行范围，避免批次间隙被误认为已停止
        """
        with self._condition:
            if self._closing:
                raise RuntimeError("批量整理已停止接收任务，等待宿主重新调度")
            self._active += 1
        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    @staticmethod
    def supports(source_oper: Any, target_oper: Any) -> bool:
        """
        仅接管宿主选中的同账号 P115Api 实例
        """
        from app.plugins.p115disk.p115_api import P115Api

        return (
            isinstance(source_oper, P115Api)
            and isinstance(target_oper, P115Api)
            and source_oper.client is target_oper.client
        )

    @staticmethod
    def _list(oper: Any, folder: FileItem) -> List[FileItem]:
        items = oper.list(folder)
        if items is None:
            raise OSError(f"无法确认网盘目录内容：{folder.path}")
        return items

    @staticmethod
    def _sha1(oper: Any, file_id: str) -> str:
        response = oper.client.fs_file_skim(
            file_id, **configer.get_ios_ua_app(app=False)
        )
        check_response(response)
        rows = response.get("data") or []
        if len(rows) != 1 or str(rows[0].get("file_id")) != str(file_id):
            raise OSError(f"无法确认网盘文件身份：{file_id}")
        digest = rows[0].get("sha1")
        if not digest:
            raise OSError(f"网盘文件缺少 SHA1：{file_id}")
        return str(digest).upper()

    @staticmethod
    def _observation(
        state: TransferOperationObservationState,
        item: Optional[FileItem] = None,
        **evidence: Any,
    ) -> TransferOperationObservation:
        return TransferOperationObservation(
            state=state,
            evidence=TransferStepResult(
                payload={
                    "item": item.model_dump(mode="json") if item else None,
                    **evidence,
                }
            ),
        )

    def _observe_materialize(
        self,
        operation: Dict[str, Any],
        items: Optional[List[FileItem]] = None,
        digests: Optional[Dict[str, str]] = None,
    ) -> TransferOperationObservation:
        states = TransferOperationObservationState
        source = operation["source"]
        target_oper = operation["target_oper"]
        baseline = operation["baseline"]
        if items is None:
            items = self._list(target_oper, operation["folder"])
        if operation["kind"] == "move":
            matches = [item for item in items if item.fileid == source.fileid]
        else:
            matches = [
                item
                for item in items
                if item.type == "file"
                and item.name == source.name
                and item.fileid not in baseline["known_ids"]
                and item.size == source.size
                and (
                    digests.get(item.fileid)
                    if digests is not None
                    else self._sha1(target_oper, item.fileid)
                )
                == baseline["sha1"]
            ]
        if len(matches) == 1:
            if not matches[0].fileid or not matches[0].pickcode:
                return self._observation(
                    states.UNKNOWN, reason="目标缺少 ID 或 pickcode"
                )
            return self._observation(states.APPLIED, matches[0])
        if matches:
            return self._observation(states.CONFLICT, reason="存在多个匹配副本")
        source_oper = operation["source_oper"]
        source_folder = source_oper.get_item_strict(Path(source.path).parent)
        if source_folder and any(
            item.fileid == source.fileid and item.path == source.path
            for item in self._list(source_oper, source_folder)
        ):
            return self._observation(states.NOT_APPLIED)
        return self._observation(states.UNKNOWN, reason="源与目标身份无法确认")

    def _observe_rename(
        self,
        operation: Dict[str, Any],
        items: Optional[List[FileItem]] = None,
    ) -> TransferOperationObservation:
        states = TransferOperationObservationState
        if items is None:
            items = self._list(operation["target_oper"], operation["folder"])
        source = operation["source"]
        matches = [item for item in items if item.fileid == source.fileid]
        if len(matches) != 1:
            return self._observation(states.UNKNOWN, reason="无法定位待重命名文件")
        item = matches[0]
        if item.name == operation["target"].name:
            return self._observation(states.APPLIED, item)
        if item.name == source.name:
            return self._observation(states.NOT_APPLIED)
        return self._observation(states.CONFLICT, reason="文件已被改为其他名称")

    def _execute_batch(self, operations: List[BatchOperation]) -> None:
        valid = []
        for operation in operations:
            try:
                operation.validate()
                valid.append(operation)
            except Exception as error:
                operation.future.set_exception(error)
        operations = valid
        if not operations:
            return
        with log_batch(operations) as batch_id:
            self._execute_operations(operations, batch_id)

    def _execute_operations(
        self, operations: List[BatchOperation], batch_id: str
    ) -> None:
        first = operations[0].payload
        client = first["target_oper"].client
        kind = first["kind"]
        if kind == "capture":
            items = self._list(first["target_oper"], first["folder"])
            sources = {}
            errors = {}
            valid = []
            for operation in operations:
                source = operation.payload["source"]
                oper = operation.payload["source_oper"]
                parent = Path(source.path).parent
                key = (id(oper), str(parent))
                try:
                    if key in errors:
                        raise errors[key]
                    if key not in sources:
                        try:
                            folder = oper.get_item_strict(parent)
                            if folder is None:
                                logger.warning(
                                    "【整理接管】批次=%s，源目录不存在：%r",
                                    batch_id,
                                    str(parent),
                                )
                                raise OSError(f"源目录不存在：{parent}")
                            sources[key] = {
                                (str(Path(item.path)), item.fileid)
                                for item in self._list(oper, folder)
                            }
                        except Exception as error:
                            errors[key] = error
                            raise
                    if (str(Path(source.path)), source.fileid) not in sources[key]:
                        logger.warning(
                            "【整理接管】批次=%s，源文件身份不匹配：路径=%r，文件ID=%s",
                            batch_id,
                            source.path,
                            source.fileid,
                        )
                        raise OSError(f"源文件身份已经改变：{source.path}")
                except Exception as error:
                    operation.future.set_exception(error)
                else:
                    valid.append(operation)
            operations = valid
            copy_ids = [
                op.payload["source"].fileid
                for op in operations
                if op.payload["mode"] == "copy"
            ]
            digests = self._digests(client, copy_ids) if copy_ids else {}
            for operation in operations:
                source_id = operation.payload["source"].fileid
                if operation.payload["mode"] == "copy" and source_id not in digests:
                    operation.future.set_exception(
                        OSError(f"源文件缺少 SHA1：{source_id}")
                    )
                else:
                    operation.future.set_result(
                        TransferStepResult(
                            payload={
                                "known_ids": [item.fileid for item in items],
                                "sha1": digests.get(source_id),
                            }
                        )
                    )
            return
        error = None
        try:
            if kind == "rename":
                response = client.fs_rename(
                    [
                        (
                            operation.payload["source"].fileid,
                            operation.payload["target"].name,
                        )
                        for operation in operations
                    ],
                    **configer.get_ios_ua_app(app=False),
                )
            else:
                method = client.fs_move if kind == "move" else client.fs_copy
                response = method(
                    [operation.payload["source"].fileid for operation in operations],
                    pid=int(first["folder"].fileid),
                    **configer.get_ios_ua_app(app=False),
                )
            check_response(response)
        except Exception as failure:
            error = failure
            logger.warning(
                "【整理接管】批次=%s，网盘 %s 请求异常，错误类型=%s；继续核验实际结果，暂不判定失败",
                batch_id,
                kind,
                type(failure).__name__,
            )
        items = self._list(first["target_oper"], first["folder"])
        digests = None
        if kind == "copy":
            names = {operation.payload["source"].name for operation in operations}
            candidates = [
                item.fileid
                for item in items
                if item.type == "file" and item.name in names
            ]
            digests = self._digests(client, candidates) if candidates else {}
        for operation in operations:
            try:
                result = (
                    self._observe_rename(operation.payload, items)
                    if kind == "rename"
                    else self._observe_materialize(operation.payload, items, digests)
                )
                if result.state is not TransferOperationObservationState.APPLIED:
                    logger.warning(
                        "【整理接管】批次=%s，任务=%s，%s 结果未确认：源=%r，状态=%s，原因=%s",
                        batch_id,
                        operation.payload.get("task_id") or "未知",
                        kind,
                        operation.payload["source"].path,
                        result.state.value,
                        result.evidence.payload.get("reason")
                        or "未发现可确认的目标文件",
                    )
                    raise OSError(
                        f"批量 {kind} 尚未确认成功：{result.state.value}"
                    ) from error
                item = FileItem(**result.evidence.payload["item"])
                if kind == "move":
                    CacheUpdater(operation.payload["source_oper"]).remove_cache(
                        int(operation.payload["source"].fileid)
                    )
                CacheUpdater(operation.payload["target_oper"]).update_file_cache(item)
                operation.future.set_result(result.evidence)
            except Exception as failure:
                operation.future.set_exception(failure)

    @staticmethod
    def _digests(client: Any, file_ids: List[str]) -> Dict[str, str]:
        response = client.fs_file_skim(file_ids, **configer.get_ios_ua_app(app=False))
        check_response(response)
        return {
            str(row["file_id"]): str(row["sha1"]).upper()
            for row in response.get("data", [])
            if row.get("file_id") and row.get("sha1")
        }

    def execute(
        self,
        *,
        task: Any,
        chain: Any,
        step_runner: Any,
        source_fileitem: Dict[str, Any],
        target_storage: str,
        source_oper: Any,
        target_oper: Any,
        target_file: Path,
        transfer_type: str,
    ) -> Tuple[Optional[FileItem], str]:
        """
        使用同一宿主任务的快照、落地、重命名步骤执行单文件批量整理
        """
        source = FileItem(**source_fileitem)
        task_id = getattr(task, "admission_task_id", None) or "未知"
        logger.info(
            "【整理接管】执行文件步骤：任务=%s，方式=%s，源=%r，目标=%r",
            task_id,
            transfer_type,
            source.path,
            str(target_file),
        )
        folder = target_oper.get_item_strict(target_file.parent)
        if not folder or folder.type != "dir" or not folder.fileid:
            logger.error(
                "【整理接管】目标目录不可用：任务=%s，路径=%r，无法开始 %s",
                task_id,
                str(target_file.parent),
                transfer_type,
            )
            raise OSError(f"目标目录尚未创建：{target_file.parent}")
        logger.debug(
            "【整理接管】目标目录已就绪：任务=%s，路径=%r，目录ID=%s",
            task_id,
            folder.path,
            folder.fileid,
        )

        def validate() -> None:
            try:
                chain._TransferChain__assert_owned_lease(task)
            except Exception as error:
                logger.warning(
                    "【整理接管】操作被租约校验阻止：任务=%s，源=%r，错误类型=%s",
                    task_id,
                    source.path,
                    type(error).__name__,
                )
                raise

        def snapshot() -> TransferStepResult:
            return self.coordinator.submit(
                (id(source_oper), id(target_oper), "capture", folder.fileid),
                {
                    "kind": "capture",
                    "task_id": task_id,
                    "source": source,
                    "source_oper": source_oper,
                    "target_oper": target_oper,
                    "folder": folder,
                    "mode": transfer_type,
                },
                validate,
            )

        baseline = step_runner.run(
            phase="p115_batch",
            kind="capture_destination",
            payload={"source": source_fileitem, "target": target_file.as_posix()},
            execute=snapshot,
            observe=lambda: TransferOperationObservation(
                state=TransferOperationObservationState.APPLIED, evidence=snapshot()
            ),
        )
        operation = {
            "task_id": task_id,
            "source": source,
            "source_oper": source_oper,
            "target_oper": target_oper,
            "folder": folder,
            "target": target_file,
            "baseline": baseline.payload,
            "kind": transfer_type,
        }

        def submit() -> TransferStepResult:
            return self.coordinator.submit(
                (id(source_oper), id(target_oper), operation["kind"], folder.fileid),
                dict(operation),
                validate,
            )

        materialized = step_runner.run(
            phase="p115_batch",
            kind="materialize",
            payload={
                "source": source_fileitem,
                "target_storage": target_storage,
                "parent": target_file.parent.as_posix(),
                "mode": transfer_type,
                "baseline": baseline.payload,
            },
            execute=submit,
            observe=lambda: self._observe_recovery(operation, task_id),
        )
        materialized_item = FileItem(**materialized.payload["item"])
        operation.update(source=materialized_item, kind="rename")
        if materialized_item.name == target_file.name:
            logger.debug(
                "【整理接管】文件名已符合目标，无需重命名：任务=%s，路径=%r",
                task_id,
                str(target_file),
            )
        renamed = step_runner.run(
            phase="p115_batch",
            kind="rename",
            payload={
                "item": materialized.payload["item"],
                "target": target_file.as_posix(),
            },
            execute=(
                lambda: (
                    materialized
                    if materialized_item.name == target_file.name
                    else submit()
                )
            ),
            observe=lambda: self._observe_recovery(operation, task_id),
        )
        target = FileItem(**renamed.payload["item"])
        CacheUpdater(target_oper).update_file_cache(target)
        logger.info(
            "【整理接管】整理完成：%r -> %r，任务=%s，方式=%s，源ID=%s，目标ID=%s",
            source.path,
            target.path,
            task_id,
            transfer_type,
            source.fileid,
            target.fileid,
        )
        return target, ""

    def _observe_recovery(
        self, operation: Dict[str, Any], task_id: str
    ) -> TransferOperationObservation:
        kind = operation["kind"]
        logger.info(
            "【整理接管】恢复核验：任务=%s，步骤=%s，源=%r，目标=%r",
            task_id,
            kind,
            operation["source"].path,
            str(operation["target"]),
        )
        result = (
            self._observe_rename(operation)
            if kind == "rename"
            else self._observe_materialize(operation)
        )
        logger.info(
            "【整理接管】恢复核验结果：任务=%s，步骤=%s，状态=%s，后续由宿主判定重试或复核",
            task_id,
            kind,
            result.state.value,
        )
        return result

    def shutdown(self, timeout: float = 25.0) -> bool:
        """
        等待在途批量操作完成
        """
        deadline = monotonic() + max(0.0, timeout)
        with self._condition:
            self._closing = True
        if not self.workers.shutdown(timeout):
            return False
        with self._condition:
            while self._active:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return self.coordinator.shutdown(max(0.0, deadline - monotonic()))
