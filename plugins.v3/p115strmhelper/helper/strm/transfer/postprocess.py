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
            logger.debug(
                "【监控整理STRM生成】事件已处理，跳过重复执行: %s，状态: %s",
                key,
                existing["state"],
            )
            return
        with lock_libraries(existing["plan"]["roots"] if existing else roots):
            record = self.store.load(key)
            if record and record["state"] in {"done", "superseded"}:
                logger.debug(
                    "【监控整理STRM生成】事件已处理，跳过重复执行: %s，状态: %s",
                    key,
                    record["state"],
                )
                return
            plan = record["plan"] if record else build()
            if not record:
                self.store.save(key, plan)
            else:
                logger.info("【监控整理STRM生成】恢复未完成的后处理: %s", key)
            if not is_current(plan["identity"]):
                self._supersede(key, plan, "云端目标已不存在或文件身份已变化")
                return
            for operation in plan["operations"]:
                if operation.get("done"):
                    continue
                if not is_current(plan["identity"]):
                    self._supersede(key, plan, "云端目标已不存在或文件身份已变化")
                    return
                path = Path(operation["path"])
                validate_path(path, plan["roots"])
                if operation["kind"] == "write":
                    try:
                        written = self._write(key, plan, operation, prepare)
                    except Exception as error:
                        if operation.get("done"):
                            logger.error(
                                "【监控整理STRM生成】文件已发布但检查点保存失败: %s, %s",
                                str(path),
                                error,
                                exc_info=True,
                            )
                        elif plan["kind"] == "strm":
                            logger.error(
                                "【监控整理STRM生成】生成 %s 文件失败: %s",
                                str(path),
                                error,
                                exc_info=True,
                            )
                        else:
                            logger.error(
                                "【监控整理STRM生成】媒体信息文件下载出现未知错误: %s，目标: %s",
                                error,
                                str(path),
                                exc_info=True,
                            )
                        raise
                    if not written:
                        self._supersede(key, plan, "文件发布期间云端目标或本地文件已变化")
                        return
                else:
                    output = plan["operations"][0]
                    if fingerprint(Path(output["path"])) != output.get("after"):
                        self._supersede(key, plan, "已生成的本地文件被其他工作修改")
                        return
                    self._delete(key, plan, operation)
            for directory in plan["directories"]:
                if not is_current(plan["identity"]):
                    self._supersede(key, plan, "云端目标已不存在或文件身份已变化")
                    return
                path = Path(directory)
                validate_path(path, plan["roots"])
                if path.is_dir() and not any(path.iterdir()):
                    try:
                        path.rmdir()
                    except Exception as error:
                        logger.error(
                            "【监控整理STRM生成】删除本地空目录失败: %s, %s",
                            path,
                            error,
                            exc_info=True,
                        )
                        raise
                    logger.warning("【监控整理STRM生成】本地空目录 %s 已删除", path)
            for name in plan["effects"]:
                if plan["effects"][name]:
                    continue
                if not is_current(plan["identity"]):
                    self._supersede(key, plan, "云端目标已不存在或文件身份已变化")
                    return
                output = plan["operations"][0]
                if fingerprint(Path(output["path"])) != output.get("after"):
                    self._supersede(key, plan, "已生成的本地文件被其他工作修改")
                    return
                try:
                    effect(name, plan)
                except Exception as error:
                    if name == "mediainfo":
                        logger.error(
                            "【监控整理STRM生成】入队媒体信息提取失败: %s",
                            error,
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            "【监控整理STRM生成】后处理步骤 %s 失败: %s",
                            name,
                            error,
                            exc_info=True,
                        )
                    raise
                plan["effects"][name] = True
                self.store.save(key, plan)
            self.store.save(key, plan, "done")

    def _supersede(self, key: str, plan: Dict[str, Any], reason: str) -> None:
        self.store.save(key, plan, "superseded")
        logger.warning(
            "【监控整理STRM生成】%s，停止该事件后处理: %s，目标: %s",
            reason,
            key,
            plan["operations"][0]["path"],
        )

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
            logger.info("【监控整理STRM生成】恢复确认文件已发布，补记检查点: %s", path)
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
        if plan["kind"] == "strm":
            logger.info("【监控整理STRM生成】生成 STRM 文件成功: %s", str(path))
        else:
            logger.info("【监控整理STRM生成】媒体信息文件下载成功: %s", str(path))
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
            logger.debug(
                "【监控整理STRM生成】旧文件、归属或同目录内容已变化，跳过清理: %s", path
            )
            operation["done"] = True
            self.store.save(key, plan)
            return
        for identity in operation["cloud_paths"]:
            if current_file(identity) is not None:
                logger.debug(
                    "【监控整理STRM生成】对应云端文件仍存在，保留本地文件: %s", path
                )
                operation["done"] = True
                self.store.save(key, plan)
                return
        if not is_current(plan["identity"]):
            raise RuntimeError("整理后处理云端目标在清理期间已变化，等待重新确认")
        if fingerprint(path) != actual or self.store.owner(path) != operation["owner"]:
            logger.debug("【监控整理STRM生成】删除前文件或归属已变化，跳过清理: %s", path)
            operation["done"] = True
            self.store.save(key, plan)
            return
        if actual is not None:
            if path == anchor:
                if operation.get("cleanup_reason") == "latest":
                    label = "旧版本 STRM 文件"
                    logger.info(
                        "【监控整理STRM生成】latest 模式：删除旧版本 STRM 文件: %s", path
                    )
                else:
                    label = "旧 STRM 文件"
                    if operation.get("cleanup_reason") == "move":
                        logger.info(
                            "【监控整理STRM生成】检测到重新整理，清理旧 STRM 文件: %s", path
                        )
                    else:
                        logger.info("【监控整理STRM生成】清理旧 STRM 文件: %s", path)
            else:
                label = "关联文件" if anchor.stem in path.stem else "刮削文件"
            try:
                path.unlink()
            except Exception as error:
                logger.error(
                    "【监控整理STRM生成】删除%s失败: %s, %s",
                    label,
                    path,
                    error,
                    exc_info=True,
                )
                raise
            if path == anchor:
                logger.info("【监控整理STRM生成】已删除%s: %s", label, path)
            else:
                logger.warning("【监控整理STRM生成】已删除%s: %s", label, path)
        operation.update(done=True, after=None)
        self.store.complete_file(key, plan, operation)
