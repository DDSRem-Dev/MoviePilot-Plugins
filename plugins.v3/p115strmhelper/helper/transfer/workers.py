from queue import Empty
from threading import Event, RLock, Thread, current_thread, local
from time import monotonic
from typing import Any, Dict, List


class _WorkerStop:
    def __init__(self, host_event: Event, retiring: Event) -> None:
        self.host_event = host_event
        self.retiring = retiring

    def is_set(self) -> bool:
        return self.host_event.is_set() or self.retiring.is_set()


class BatchWorkers:
    """
    为批量任务临时增加宿主原生 worker，保留准入、续租、进度和结算流程
    """

    def __init__(self, storage: str, limit: int = 500) -> None:
        self.storage = storage
        self.limit = max(1, limit)
        self._lock = RLock()
        self._local = local()
        self._queues: Dict[Any, Any] = {}
        self._threads: List[Thread] = []
        self._stopping = Event()

    def _eligible(self, item: Any) -> bool:
        from app.schemas.types import MediaType
        from app.sdk.media import MetaAnime, MetaVideo

        task = getattr(item, "task", None)
        if task is None:
            return False
        source = task.fileitem
        directory = getattr(task, "target_directory", None)
        target = task.target_storage or getattr(directory, "library_storage", None)
        mode = getattr(task, "transfer_type", None) or getattr(
            directory, "transfer_type", None
        )
        media = getattr(task, "mediainfo", None)
        meta = getattr(task, "meta", None)
        media_type = (
            getattr(media, "type", None)
            or getattr(task, "mtype", None)
            or getattr(meta, "type", None)
        )
        checkpoint = task.plan_checkpoint
        if checkpoint is not None:
            target = checkpoint.target_storage
            mode = checkpoint.resolved_transfer_type
            media_type = (checkpoint.resolved_mediainfo or {}).get("type") or media_type
        return bool(
            source.type == "file"
            and source.storage == self.storage
            and target == self.storage
            and mode in {"move", "copy"}
            and (
                media_type
                in {
                    MediaType.MOVIE,
                    MediaType.TV,
                    MediaType.MOVIE.value,
                    MediaType.TV.value,
                }
                or media_type in {None, MediaType.UNKNOWN, MediaType.UNKNOWN.value}
                and isinstance(meta, (MetaVideo, MetaAnime))
            )
            and not task.preview
        )

    def _install_queue(self, queue: Any) -> None:
        if queue in self._queues:
            return
        original = queue.get
        self._queues[queue] = original

        def get(block: bool = True, timeout: Any = None) -> Any:
            stop = getattr(self._local, "stop", None)
            if stop is None:
                return original(block=block, timeout=timeout)
            deadline = monotonic() + min(timeout if timeout is not None else 1.0, 1.0)
            with queue.not_empty:
                while not stop.is_set() and not self._stopping.is_set():
                    for index, item in enumerate(queue.queue):
                        if self._eligible(item):
                            del queue.queue[index]
                            queue.not_full.notify()
                            return item
                    remaining = deadline - monotonic()
                    if remaining <= 0 or not block:
                        break
                    queue.not_empty.wait(remaining)
            stop.retiring.set()
            raise Empty

        queue.get = get

    def ensure(self, chain: Any) -> None:
        """
        仅领取匹配的网盘文件，每个辅助线程运行完整的宿主原生队列循环
        """
        with self._lock, chain._worker_state_lock:
            if (
                self._stopping.is_set()
                or chain._closing
                or chain._worker_stop_event.is_set()
            ):
                return
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            queue = chain._queue
            self._install_queue(queue)
            with queue.mutex:
                pending = sum(self._eligible(item) for item in queue.queue)
            count = min(pending, max(0, self.limit - len(self._threads)))
            for _ in range(count):
                stop = _WorkerStop(chain._worker_stop_event, Event())

                def run(stop: _WorkerStop = stop) -> None:
                    self._local.stop = stop
                    try:
                        chain._TransferChain__start_transfer(stop)
                    finally:
                        with chain._worker_state_lock:
                            if current_thread() in chain._threads:
                                chain._threads.remove(current_thread())
                        del self._local.stop

                thread = Thread(
                    target=run, name="p115-transfer-host-worker", daemon=True
                )
                self._threads.append(thread)
                chain._threads.append(thread)
                thread.start()

    def shutdown(self, timeout: float = 25.0) -> bool:
        """
        停止扩充 worker，等待其在宿主流程内完成任务后恢复队列读取方法
        """
        self._stopping.set()
        deadline = monotonic() + max(0.0, timeout)
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            if thread is current_thread():
                return False
            thread.join(max(0.0, deadline - monotonic()))
        with self._lock:
            if any(thread.is_alive() for thread in self._threads):
                return False
            for queue, original in self._queues.items():
                queue.get = original
            self._queues.clear()
            self._threads.clear()
        return True
