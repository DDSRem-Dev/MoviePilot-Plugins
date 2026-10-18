from queue import Queue
from threading import Lock, Thread, current_thread
from typing import Any, Optional

from app.sdk.logging import logger


class WorkerQueue:
    """
    管理串行工作队列的启动、停止屏障和任务准入

    子类通过 _worker 消费 self._queue，并为任务及哨兵调用 task_done
    停止时拒绝新任务，排空已接受的任务，超时保留原线程及队列
    """

    _SENTINEL = object()

    def __init__(self, thread_name: str, label: str) -> None:
        """
        初始化队列生命周期状态

        :param thread_name (str): 工作线程名称
        :param label (str): 日志标识
        """
        self._thread_name = thread_name
        self._label = label
        self._queue: Optional[Queue] = None
        self._worker_thread: Optional[Thread] = None
        self._lock = Lock()
        self._lifecycle_lock = Lock()
        self._stopping = False
        self._stop_in_progress = False

    def _worker(self) -> None:
        raise NotImplementedError

    def _start_locked(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            if self._stopping:
                raise RuntimeError(f"{self._label} 工作线程尚未退出")
            return
        if self._queue is not None and self._queue.unfinished_tasks:
            raise RuntimeError(f"{self._label} 旧队列仍有未结算任务，不能替换")
        self._queue = Queue()
        self._stopping = False
        self._worker_thread = Thread(
            target=self._worker,
            name=self._thread_name,
            daemon=False,
        )
        self._worker_thread.start()
        logger.debug(f"【{self._label}】worker 已启动")

    def start(self) -> None:
        """
        显式启动队列并开启新任务准入，重复启动保持幂等
        """
        with self._lifecycle_lock, self._lock:
            self._start_locked()

    def _request_stop_locked(self) -> None:
        if (
            self._worker_thread is not None
            and self._worker_thread.is_alive()
            and not self._stopping
        ):
            self._queue.put_nowait(self._SENTINEL)
        self._stopping = True

    def stop(self, timeout: float = 30) -> bool:
        """
        关闭准入并等待已接受任务处理完毕

        :param timeout (float): 等待线程退出的最长秒数

        :return bool: 线程退出且所有已接受任务结算时返回 True
        """
        with self._lock:
            if self._worker_thread is current_thread():
                self._request_stop_locked()
                return False
        with self._lifecycle_lock:
            with self._lock:
                queue = self._queue
                worker = self._worker_thread
                self._request_stop_locked()
                self._stop_in_progress = True
            try:
                if worker is not None and worker.is_alive():
                    worker.join(timeout=max(0, timeout))
                with self._lock:
                    if worker is not None and worker.is_alive():
                        logger.warning(
                            f"【{self._label}】worker 尚未退出，保留队列等待重试"
                        )
                        return False
                    if queue is not None and queue.unfinished_tasks:
                        logger.error(f"【{self._label}】worker 已退出但队列仍有未结算任务")
                        return False
                    self._worker_thread = None
                    self._queue = None
                    return True
            finally:
                with self._lock:
                    self._stop_in_progress = False

    def _enqueue_task(self, task: Any, *, lazy_start: bool = False) -> bool:
        with self._lock:
            if self._stopping:
                if (
                    self._worker_thread is not None
                    and self._worker_thread.is_alive()
                ):
                    logger.warning(f"【{self._label}】队列正在停止，拒绝入队")
                    return False
                if self._stop_in_progress:
                    # 停止流程尚未返回，状态会被其收尾逻辑覆盖，此处不自愈
                    logger.warning(f"【{self._label}】队列正在停止，拒绝入队")
                    return False
                if self._queue is None:
                    # 从未启动或已完整释放的队列，保持显式 start 才受理
                    logger.warning(f"【{self._label}】队列未启动或已停止，拒绝入队")
                    return False
                if self._queue.unfinished_tasks:
                    logger.error(f"【{self._label}】旧队列仍有未结算任务，拒绝入队")
                    return False
                # 停止超时留下的空队列：旧 worker 已退出，自愈重建，避免永久拒收
                logger.warning(f"【{self._label}】检测到已停止的空队列，自动重建 worker")
                self._worker_thread = None
                self._queue = None
                self._stopping = False
            try:
                if (
                    lazy_start
                    or self._worker_thread is None
                    or not self._worker_thread.is_alive()
                ):
                    self._start_locked()
                if (
                    self._queue is None
                    or self._worker_thread is None
                    or not self._worker_thread.is_alive()
                ):
                    logger.warning(f"【{self._label}】队列未就绪，拒绝入队")
                    return False
                self._queue.put_nowait(task)
                return True
            except Exception as e:
                logger.error(f"【{self._label}】入队失败: {e}", exc_info=True)
                return False
