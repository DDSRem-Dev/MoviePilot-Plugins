from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread
from typing import Optional

from app.log import logger
from app.schemas.mediaserver import WebhookEventInfo


@dataclass
class SyncDelWebhookTask:
    """
    单条 Webhook 同步删除任务快照

    :param event_data (WebhookEventInfo): 已 deepcopy 的 Webhook 事件数据
    :param enabled (bool): 是否启用同步删除（入队时快照）
    :param notify (bool): 是否通知
    :param del_source (bool): 是否删除源文件
    :param p115_library_path (str): 115 媒体库路径映射
    :param p115_force_delete_files (bool): 是否强制删除无 TMDB 的文件
    """

    event_data: WebhookEventInfo
    enabled: bool
    notify: bool
    del_source: bool
    p115_library_path: Optional[str]
    p115_force_delete_files: bool


class SyncDelWebhookQueue:
    """
    Webhook 同步删除全局队列
    """

    _SENTINEL = object()

    def __init__(self) -> None:
        self._queue: Optional[Queue] = None
        self._worker_thread: Optional[Thread] = None
        self._lock = Lock()

    def _worker(self) -> None:
        """
        从队列取出任务并调用 MediaSyncDelHelper.sync_del_by_webhook
        """
        q = self._queue
        if q is None:
            return
        while True:
            try:
                task = q.get()
            except Exception as e:
                logger.error(
                    f"【同步删除 Webhook 队列】worker 取任务异常: {e}",
                    exc_info=True,
                )
                continue
            if task is self._SENTINEL:
                q.task_done()
                break
            try:
                # 延迟导入，避免 mediasyncdel 包初始化循环依赖
                from . import MediaSyncDelHelper

                MediaSyncDelHelper().sync_del_by_webhook(
                    event_data=task.event_data,
                    enabled=task.enabled,
                    notify=task.notify,
                    del_source=task.del_source,
                    p115_library_path=task.p115_library_path,
                    p115_force_delete_files=task.p115_force_delete_files,
                )
            except Exception as e:
                logger.error(
                    f"【同步删除 Webhook 队列】处理任务失败: {e}",
                    exc_info=True,
                )
            finally:
                q.task_done()

    def _ensure_started(self) -> None:
        """
        懒启动 worker（首次入队时调用）
        """
        with self._lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._queue = Queue()
            self._worker_thread = Thread(
                target=self._worker,
                name="P115StrmHelper-SyncDelWebhookQueue",
                daemon=False,
            )
            self._worker_thread.start()
            logger.debug("【同步删除 Webhook 队列】worker 已启动")

    def stop(self) -> None:
        """
        停止 worker：发送哨兵并 join，尽量排空已入队任务前的处理
        """
        with self._lock:
            q = self._queue
            th = self._worker_thread
            if q is None or th is None:
                return
            if not th.is_alive():
                self._queue = None
                self._worker_thread = None
                return
        try:
            q.put(self._SENTINEL)
            th.join(timeout=30)
            if th.is_alive():
                logger.warning("【同步删除 Webhook 队列】worker 未在 30 秒内退出")
        except Exception as e:
            logger.error(
                f"【同步删除 Webhook 队列】停止 worker 异常: {e}",
                exc_info=True,
            )
        finally:
            with self._lock:
                if self._worker_thread is th and self._queue is q:
                    self._worker_thread = None
                    self._queue = None

    def enqueue(self, task: SyncDelWebhookTask) -> None:
        """
        将一条同步删除任务加入队列（无界，put_nowait 不阻塞事件线程）

        :param task (SyncDelWebhookTask): 任务快照（event_data 须已在调用方 deepcopy）
        """
        self._ensure_started()
        with self._lock:
            q = self._queue
        if q is None:
            logger.warning("【同步删除 Webhook 队列】队列未就绪，跳过入队")
            return
        try:
            q.put_nowait(task)
        except Exception as e:
            logger.error(f"【同步删除 Webhook 队列】入队失败: {e}", exc_info=True)


sync_del_webhook_queue = SyncDelWebhookQueue()
