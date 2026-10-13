from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Iterator, List
from uuid import uuid4

from app.sdk.logging import logger

from .batch import BatchOperation


@contextmanager
def log_batch(operations: List[BatchOperation]) -> Iterator[str]:
    """
    关联批次文件明细和核验结果，不输出客户端、请求头或完整异常载荷
    """
    batch_id = uuid4().hex[:12]
    first = operations[0].payload
    kind = first["kind"]
    folder = first["folder"]
    log = logger.debug if kind == "capture" else logger.info
    started = monotonic()
    log(
        "【整理接管】批量 %s：%s 个文件，批次=%s，存储=%s，目标目录=%r，目录ID=%s",
        kind,
        len(operations),
        batch_id,
        folder.storage,
        folder.path,
        folder.fileid,
    )
    for index, operation in enumerate(operations, 1):
        data = operation.payload
        source = data["source"]
        destination = (
            data.get("target") if kind == "rename" else Path(folder.path) / source.name
        )
        log(
            "【整理接管】批次=%s，文件[%s/%s]，任务=%s，文件ID=%s，%r -> %r",
            batch_id,
            index,
            len(operations),
            data.get("task_id") or "未知",
            source.fileid,
            source.path,
            str(destination),
        )
    try:
        yield batch_id
    except Exception as error:
        logger.warning(
            "【整理接管】批次=%s，%s 阶段中断，错误类型=%s，未确认项交回宿主持久步骤处理",
            batch_id,
            kind,
            type(error).__name__,
        )
        raise
    finally:
        confirmed = 0
        for operation in operations:
            future = operation.future
            failure = (
                future.exception() if future.done() and not future.cancelled() else None
            )
            if future.done() and not future.cancelled() and failure is None:
                confirmed += 1
            else:
                data = operation.payload
                logger.warning(
                    "【整理接管】批次=%s，未确认项：任务=%s，源=%r，错误类型=%s",
                    batch_id,
                    data.get("task_id") or "未知",
                    data["source"].path,
                    type(failure).__name__ if failure else "结果未返回",
                )
        log(
            "【整理接管】批次=%s，%s 核验结束：已确认=%s，未确认=%s，耗时=%.2f秒",
            batch_id,
            kind,
            confirmed,
            len(operations) - confirmed,
            monotonic() - started,
        )
