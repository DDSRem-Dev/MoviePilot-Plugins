from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Any, Callable, Dict, List

from app.chain.storage import StorageChain
from app.sdk.logging import logger

from ....db_manager.transfer_postprocess import TransferPostprocessStore
from .files import fingerprint, lock_libraries, publish_file, validate_path


def file_identity(item: Any) -> Dict[str, Any]:
    """
    固定事件中的存储、云端路径和文件身份，不将历史 ID 当作版本
    """
    return {
        name: getattr(item, name, None)
        for name in ("storage", "path", "fileid", "pickcode", "size", "modify_time")
    }


def event_key(item: Dict[str, Any], event_type: Any) -> str:
    """
    为持久事件或旧同步事件构造稳定身份，隔离字幕和主媒体的处理
    """
    transfer = item["transferinfo"]
    identity = {
        "event": getattr(event_type, "value", event_type),
        "key": item.get("idempotency_key"),
    }
    if not identity["key"]:
        identity.update(
            target=file_identity(transfer.target_item),
            history=item.get("transfer_history_id"),
            source=file_identity(transfer.fileitem)
            if getattr(transfer, "fileitem", None)
            else None,
            transfer_type=transfer.transfer_type,
        )
    return sha256(
        dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def current_file(identity: Dict[str, Any]) -> Any:
    """
    严格回源查询，查询异常继续抛出，不能当作文件不存在
    """
    return StorageChain().get_file_item_strict(
        storage=identity["storage"], path=Path(identity["path"])
    )


def is_current(identity: Dict[str, Any]) -> bool:
    """
    校验当前云端目标仍是该事件的文件，缺少可比身份则拒绝确认

    移动和重命名会改变云端修改时间，完成事件仍可能携带操作前的时间
    因此使用文件 ID 或 pickcode 及大小核对身份，不以修改时间判断事件过期
    """
    current = current_file(identity)
    if current is None:
        return False
    field = "fileid" if identity.get("fileid") else "pickcode"
    expected = identity.get(field)
    actual = getattr(current, field, None)
    if not expected or not actual:
        raise RuntimeError("整理后处理无法确认云端文件身份，等待重试")
    if str(expected) != str(actual):
        return False
    actual_size = getattr(current, "size", None)
    if (
        identity.get("size") is not None
        and actual_size is not None
        and identity["size"] != actual_size
    ):
        return False
    return True


class TransferPostprocessor:
    """
    持久协调文件发布、清理与后续效果，恢复时使用原固定计划
    """

    def __init__(self) -> None:
        self.store = TransferPostprocessStore()

    def run(
        self,
        key: str,
        roots: List[str],
        build: Callable[[], Dict[str, Any]],
        prepare: Callable[[Dict[str, Any], Path], None],
        effect: Callable[[str, Dict[str, Any]], None],
    ) -> None:
        """
        串行执行事件计划，成功或过期事件重投时直接确认
        """
        existing = self.store.load(key)
        if existing and existing["state"] in {"done", "superseded"}:
            return
        with lock_libraries(existing["plan"]["roots"] if existing else roots):
            record = self.store.load(key)
            if record and record["state"] in {"done", "superseded"}:
                return
            plan = record["plan"] if record else build()
            if not record:
                self.store.save(key, plan)
            if not is_current(plan["identity"]):
                self.store.save(key, plan, "superseded")
                return
            for operation in plan["operations"]:
                if operation.get("done"):
                    continue
                if not is_current(plan["identity"]):
                    self.store.save(key, plan, "superseded")
                    return
                path = Path(operation["path"])
                validate_path(path, plan["roots"])
                if operation["kind"] == "write":
                    if not self._write(key, plan, operation, prepare):
                        self.store.save(key, plan, "superseded")
                        return
                else:
                    output = plan["operations"][0]
                    if fingerprint(Path(output["path"])) != output.get("after"):
                        self.store.save(key, plan, "superseded")
                        return
                    self._delete(key, plan, operation)
            for directory in plan["directories"]:
                if not is_current(plan["identity"]):
                    self.store.save(key, plan, "superseded")
                    return
                path = Path(directory)
                validate_path(path, plan["roots"])
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            for name in plan["effects"]:
                if plan["effects"][name]:
                    continue
                if not is_current(plan["identity"]):
                    self.store.save(key, plan, "superseded")
                    return
                output = plan["operations"][0]
                if fingerprint(Path(output["path"])) != output.get("after"):
                    self.store.save(key, plan, "superseded")
                    return
                effect(name, plan)
                plan["effects"][name] = True
                self.store.save(key, plan)
            self.store.save(key, plan, "done")

    def _write(
        self,
        key: str,
        plan: Dict[str, Any],
        operation: Dict[str, Any],
        prepare: Callable[[Dict[str, Any], Path], None],
    ) -> bool:
        path = Path(operation["path"])
        actual = fingerprint(path)
        if (
            operation.get("prepared")
            and actual == operation["prepared"]
            and self.store.owner(path) == operation["owner"]
        ):
            operation.update(done=True, after=actual)
            self.store.complete_file(key, plan, operation)
            return True
        if (
            actual != operation["before"]
            or self.store.owner(path) != operation["owner"]
        ):
            logger.warning(
                f"【监控整理STRM生成】目标已被其他工作更新，保留当前文件: {path}"
            )
            return False
        staged = path.with_name(f".p115-{key}.part")
        validate_path(staged, plan["roots"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if (
            not operation.get("prepared")
            or fingerprint(staged) != operation["prepared"]
        ):
            staged.unlink(missing_ok=True)
            prepare(plan, staged)
            operation["prepared"] = fingerprint(staged)
            if operation["prepared"] is None:
                raise RuntimeError("整理后处理没有生成暂存文件")
            self.store.save(key, plan)
        if not is_current(plan["identity"]):
            staged.unlink(missing_ok=True)
            return False
        if fingerprint(path) != operation["before"]:
            staged.unlink(missing_ok=True)
            return False
        publish_file(staged, path)
        after = fingerprint(path)
        if after != operation["prepared"]:
            return False
        operation.update(done=True, after=after)
        self.store.complete_file(key, plan, operation)
        return True

    def _delete(
        self, key: str, plan: Dict[str, Any], operation: Dict[str, Any]
    ) -> None:
        path = Path(operation["path"])
        actual = fingerprint(path)
        anchor = Path(operation["anchor"])
        siblings = (
            {entry.name for entry in path.parent.iterdir()}
            if path.parent.is_dir()
            else set()
        )
        if (
            (actual is not None and actual != operation["before"])
            or self.store.owner(path) != operation["owner"]
            or fingerprint(anchor) not in (None, operation["anchor_before"])
            or siblings - set(operation["siblings"])
        ):
            operation["done"] = True
            self.store.save(key, plan)
            return
        for identity in operation["cloud_paths"]:
            if current_file(identity) is not None:
                operation["done"] = True
                self.store.save(key, plan)
                return
        if not is_current(plan["identity"]):
            raise RuntimeError("整理后处理云端目标在清理期间已变化，等待重新确认")
        if fingerprint(path) != actual or self.store.owner(path) != operation["owner"]:
            operation["done"] = True
            self.store.save(key, plan)
            return
        if actual is not None:
            path.unlink()
        operation.update(done=True, after=None)
        self.store.complete_file(key, plan, operation)
