from dataclasses import dataclass
from typing import Optional

from app.sdk.logging import logger
from app.schemas.mediaserver import WebhookEventInfo

from ...core.worker_queue import WorkerQueue


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


class SyncDelWebhookQueue(WorkerQueue):
    """
    Webhook 同步删除全局队列
    """

    def __init__(self) -> None:
        super().__init__("P115StrmHelper-SyncDelWebhookQueue", "同步删除 Webhook 队列")

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

    def enqueue(self, task: SyncDelWebhookTask) -> bool:
        """
        将一条同步删除任务加入队列（无界，put_nowait 不阻塞事件线程）

        :param task (SyncDelWebhookTask): 任务快照（event_data 须已在调用方 deepcopy）

        :return bool: 入队成功返回 True，停止后拒绝自动恢复
        """
        return self._enqueue_task(task, lazy_start=True)


sync_del_webhook_queue = SyncDelWebhookQueue()
