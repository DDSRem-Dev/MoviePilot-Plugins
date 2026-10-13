from concurrent.futures import Future
from dataclasses import dataclass
from threading import Condition, Thread, current_thread
from time import monotonic
from typing import Any, Callable, Dict, Hashable, List, Optional


@dataclass
class BatchOperation:
    """
    已由宿主持久步骤登记的单文件操作

    Attributes:
        key: 可合并操作的账号、存储实例、动作与目标目录
        payload: 执行器需要的文件操作参数
        validate: 发起云端操作前再次校验任务租约
        future: 向原宿主工作线程交还结果或异常
    """

    key: Hashable
    payload: Dict[str, Any]
    validate: Callable[[], None]
    future: Future


class BatchCoordinator:
    """
    合并在途持久步骤，原宿主线程等待真实结果后继续结算
    """

    def __init__(
        self,
        execute: Callable[[List[BatchOperation]], None],
        delay: float = 0.25,
        max_size: int = 500,
    ) -> None:
        self._execute = execute
        self._delay = max(0.0, delay)
        self._max_size = max(1, max_size)
        self._condition = Condition()
        self._pending: List[BatchOperation] = []
        self._closing = False
        self._deadline = 0.0
        self._worker: Optional[Thread] = None

    def submit(
        self,
        key: Hashable,
        payload: Dict[str, Any],
        validate: Callable[[], None],
    ) -> Any:
        """
        登记操作并等待逐文件结果，异常沿原调用栈交回宿主恢复流程
        """
        operation = BatchOperation(key, payload, validate, Future())
        with self._condition:
            if self._closing:
                raise RuntimeError("批量整理正在停止，操作未执行")
            if not self._pending:
                self._deadline = monotonic() + self._delay
            self._pending.append(operation)
            if self._worker is None or not self._worker.is_alive():
                self._worker = Thread(
                    target=self._run, name="p115-transfer-batch", daemon=True
                )
                self._worker.start()
            self._condition.notify_all()
        return operation.future.result()

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._pending:
                    self._worker = None
                    self._condition.notify_all()
                    return
                remaining = self._deadline - monotonic()
                if (
                    remaining > 0
                    and len(self._pending) < self._max_size
                    and not self._closing
                ):
                    self._condition.wait(remaining)
                    continue
                pending = self._pending[: self._max_size]
                del self._pending[: self._max_size]
                self._deadline = monotonic() + self._delay
            groups: Dict[Hashable, List[BatchOperation]] = {}
            for operation in pending:
                try:
                    operation.validate()
                except Exception as error:
                    operation.future.set_exception(error)
                else:
                    groups.setdefault(operation.key, []).append(operation)
            for operations in groups.values():
                try:
                    self._execute(operations)
                except Exception as error:
                    for operation in operations:
                        if not operation.future.done():
                            operation.future.set_exception(error)
                finally:
                    for operation in operations:
                        if not operation.future.done():
                            operation.future.set_exception(
                                RuntimeError("批量执行器未返回文件结果")
                            )

    def shutdown(self, timeout: float = 25.0) -> bool:
        """
        拒绝新操作并完成已登记批次，超时保留运行中的执行器

        :return bool: 已无批量工作线程时返回 True
        """
        with self._condition:
            self._closing = True
            worker = self._worker
            self._condition.notify_all()
        if worker is current_thread():
            return False
        if worker is not None:
            worker.join(max(0.0, timeout))
            return not worker.is_alive()
        return True
