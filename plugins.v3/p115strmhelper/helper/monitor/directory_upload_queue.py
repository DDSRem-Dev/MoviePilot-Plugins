from dataclasses import dataclass
from typing import Optional, Tuple

from p115client import P115Client

from app.sdk.logging import logger

from ...core.worker_queue import WorkerQueue


@dataclass
class DirectoryUploadTask:
    """
    单条目录上传处理任务

    Attributes:
        client: 115 客户端
        file_path: 事件文件路径
        mon_path: 监控根目录
        stable_ready: 是否已完成稳定性确认
        stable_signature: 稳定性确认时的文件签名
    """

    client: P115Client
    file_path: str
    mon_path: str
    stable_ready: bool = False
    stable_signature: Optional[Tuple[int, int, int]] = None


class DirectoryUploadQueue(WorkerQueue):
    """
    目录上传全局处理队列
    """

    def __init__(self) -> None:
        super().__init__("P115StrmHelper-DirectoryUploadQueue", "目录上传")

    def _worker(self) -> None:
        """
        从队列取任务并调用 process_file_change
        """
        q = self._queue
        if q is None:
            return
        while True:
            try:
                task = q.get()
            except Exception as e:
                logger.error(
                    f"【目录上传】worker 取任务异常: {e}",
                    exc_info=True,
                )
                continue
            if task is self._SENTINEL:
                q.task_done()
                break
            try:
                # 延迟导入，避免与 monitor 包初始化循环依赖
                from . import process_file_change

                process_file_change(
                    task.client,
                    task.file_path,
                    task.mon_path,
                    task.stable_ready,
                    task.stable_signature,
                )
            except Exception as e:
                logger.error(
                    f"【目录上传】处理任务失败: {e}",
                    exc_info=True,
                )
            finally:
                q.task_done()

    def enqueue(self, task: DirectoryUploadTask) -> bool:
        """
        将一条处理任务加入队列

        :param task (DirectoryUploadTask): 任务参数

        :return bool: 入队成功返回 True
        """
        return self._enqueue_task(task)


directory_upload_queue = DirectoryUploadQueue()
