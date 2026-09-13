"""
``app.application.transfer.workflow`` 替身：提供 ``JobManager``。

替身忠实复刻宿主 JobManager 的**状态语义**（这是插件补丁的正确性依赖项）：

* ``add_task`` 返回 ``False`` 表示「任务已存在或无效」
* ``migrate_task`` 返回 ``False`` 表示「迁移失败，调用方应中止」
* ``job_id`` 由 ``mediainfo`` 优先、``meta`` 兜底推导
* 私有名 ``__get_media_id`` 存在，可用 ``_JobManager__get_media_id`` 访问

内部用轻量的 ``TransferJob`` / ``TransferJobTask`` 结构承载状态，方法与宿主同名。
"""

import threading
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = ["JobManager", "job_lock"]

#: 与宿主一致的模块级作业锁
job_lock = threading.Lock()


class TransferJobTask:
    """作业内的单个整理任务。"""

    def __init__(
        self,
        fileitem: Any = None,
        meta: Any = None,
        downloader: Optional[str] = None,
        download_hash: Optional[str] = None,
        state: Optional[str] = "waiting",
    ) -> None:
        self.fileitem = fileitem
        self.meta = meta
        self.downloader = downloader
        self.download_hash = download_hash
        self.state = state

    def __repr__(self) -> str:
        name = getattr(self.fileitem, "name", None)
        return f"TransferJobTask(file={name!r}, state={self.state!r})"


class TransferJob:
    """一个媒体对应的作业。"""

    def __init__(
        self,
        media: Any = None,
        season: Optional[int] = None,
        tasks: Optional[List[TransferJobTask]] = None,
    ) -> None:
        self.media = media
        self.season = season
        self.tasks = tasks or []

    def __repr__(self) -> str:
        return f"TransferJob(season={self.season!r}, tasks={len(self.tasks)})"


class JobManager:
    """作业管理器替身。"""

    _job_view: Dict[Any, TransferJob] = {}
    _season_episodes: Dict[Any, List[int]] = {}
    _meta_to_media_ids: Dict[Any, Set[Any]] = {}
    _task_state_changed_at: Dict[Any, float] = {}
    _active_executions: Set[Any] = set()

    def __init__(self) -> None:
        self._job_view = {}
        self._season_episodes = {}
        self._meta_to_media_ids = {}
        self._task_state_changed_at = {}
        self._active_executions = set()

    # ------------------------------------------------------------------
    # 身份推导（私有名与宿主一致，保证 ``_JobManager__x`` 可访问）
    # ------------------------------------------------------------------
    @staticmethod
    def __get_meta_id(meta: Any = None, season: Optional[int] = None):
        name = getattr(meta, "name", None) or getattr(meta, "title", None)
        return name, season

    @staticmethod
    def __get_media_id(media: Any = None, season: Optional[int] = None):
        if not media:
            return None, season
        source = getattr(media, "media_source", None)
        media_id = getattr(media, "media_id", None)
        return (source, media_id), season

    @staticmethod
    def __get_file_key(fileitem: Any) -> Optional[Tuple[str, str]]:
        if not fileitem or not getattr(fileitem, "path", None):
            return None
        path = str(fileitem.path).replace("\\", "/").rstrip("/") or "/"
        return getattr(fileitem, "storage", None) or "local", path

    def __get_id(self, task: Any = None) -> Any:
        meta = self._task_meta(task)
        if getattr(task, "mediainfo", None):
            return self.__get_media_id(media=task.mediainfo,
                                       season=getattr(meta, "begin_season", None))
        return self.__get_meta_id(meta=meta, season=getattr(meta, "begin_season", None))

    def get_job_id(self, task: Any) -> Any:
        """返回任务当前所属的稳定作业身份。"""
        return self.__get_id(task)

    @staticmethod
    def _task_meta(task: Any) -> Any:
        """取出任务的 meta，兼容 ``meta`` / ``fileitem`` 两种承载方式。"""
        meta = getattr(task, "meta", None)
        if meta is not None:
            return meta
        return getattr(task, "fileitem", None)

    @classmethod
    def _job_tasks(cls, job: TransferJob) -> List[TransferJobTask]:
        return job.tasks

    # ------------------------------------------------------------------
    # 状态流转
    # ------------------------------------------------------------------
    def add_task(self, task: Any, state: Optional[str] = "waiting") -> bool:
        """添加整理任务。

        :return: ``True`` 表示已添加；``False`` 表示任务无效或已存在（重复）
        """
        if not all([task, getattr(task, "meta", None),
                    getattr(task, "fileitem", None)]):
            return False
        file_key = self.__get_file_key(task.fileitem)
        if not file_key:
            return False
        with job_lock:
            job_id = self.__get_id(task)
            # 跨作业去重：同一源文件不得重复入队
            for job in self._job_view.values():
                for existing in self._job_tasks(job):
                    if self.__get_file_key(existing.fileitem) == file_key:
                        return False
            meta = self._task_meta(task)
            job_task = TransferJobTask(
                fileitem=task.fileitem,
                meta=meta,
                downloader=getattr(task, "downloader", None),
                download_hash=getattr(task, "download_hash", None),
                state=state,
            )
            if job_id in self._job_view:
                self._job_view[job_id].tasks.append(job_task)
            else:
                self._job_view[job_id] = TransferJob(
                    media=getattr(task, "mediainfo", None),
                    season=getattr(meta, "begin_season", None),
                    tasks=[job_task],
                )
            episodes = list(getattr(meta, "episode_list", None) or [])
            self._season_episodes[job_id] = sorted(
                set(self._season_episodes.get(job_id, [])) | set(episodes)
            )
            return True

    def migrate_task(self, task: Any) -> bool:
        """把任务从 meta 作业迁移到 media 作业。

        :return: ``False`` 表示迁移失败（如任务已在目标队列中），调用方应中止
        """
        job_id = self.__get_id(task)
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        with job_lock:
            if file_key is None:
                return False
            for existing_id, job in list(self._job_view.items()):
                for existing in list(self._job_tasks(job)):
                    if self.__get_file_key(existing.fileitem) != file_key:
                        continue
                    if existing_id == job_id:
                        # 已在目标作业中，无需迁移
                        return False
                    self._job_view[existing_id].tasks.remove(existing)
            meta = self._task_meta(task)
            job_task = TransferJobTask(
                fileitem=task.fileitem,
                meta=meta,
                downloader=getattr(task, "downloader", None),
                download_hash=getattr(task, "download_hash", None),
                state="waiting",
            )
            if job_id in self._job_view:
                self._job_view[job_id].tasks.append(job_task)
            else:
                self._job_view[job_id] = TransferJob(
                    media=getattr(task, "mediainfo", None),
                    season=getattr(meta, "begin_season", None),
                    tasks=[job_task],
                )
            return True

    def __is_job_done(self, job_id: Any) -> bool:
        if job_id not in self._job_view:
            return True
        return all(
            task.state in ("completed", "failed")
            for task in self._job_tasks(self._job_view[job_id])
        )

    def __pop_job(self, job_id: Any) -> None:
        self._job_view.pop(job_id, None)
        self._season_episodes.pop(job_id, None)

    def start_execution(self, task: Any) -> None:
        """标记任务开始执行。"""
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        if file_key:
            self._active_executions.add(file_key)

    def finish_execution(self, task: Any) -> None:
        """标记任务结束执行。"""
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        if file_key:
            self._active_executions.discard(file_key)

    def running_task(self, task: Any) -> None:
        """把任务状态置为 running。"""
        self._set_state(task, "running")

    def finish_task(self, task: Any, *args: Any, **kwargs: Any) -> None:
        """把任务状态置为 completed。"""
        self._set_state(task, "completed")

    def fail_task(self, task: Any, *args: Any, **kwargs: Any) -> None:
        """把任务状态置为 failed。"""
        self._set_state(task, "failed")

    def fail_unfinished_task(self, *args: Any, **kwargs: Any) -> None:
        """把未完成任务统一置为失败。"""

    def _set_state(self, task: Any, state: str) -> None:
        """按文件键定位任务并改写其状态。"""
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        if not file_key:
            return
        for job in self._job_view.values():
            for existing in self._job_tasks(job):
                if self.__get_file_key(existing.fileitem) == file_key:
                    existing.state = state

    def remove_task(self, task: Any, *args: Any, **kwargs: Any) -> bool:
        """按文件键移除任务。"""
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        if not file_key:
            return False
        removed = False
        for job_id, job in list(self._job_view.items()):
            for existing in list(self._job_tasks(job)):
                if self.__get_file_key(existing.fileitem) == file_key:
                    job.tasks.remove(existing)
                    removed = True
            if not job.tasks:
                self.__pop_job(job_id)
        return removed

    def remove_job(self, job_id: Any) -> bool:
        """按作业 ID 移除整个作业。"""
        if job_id not in self._job_view:
            return False
        self.__pop_job(job_id)
        return True

    def try_remove_job(self, task: Any) -> bool:
        """任务所属作业全部完成时移除该作业。"""
        job_id = self.__get_id(task)
        if self.__is_job_done(job_id):
            return self.remove_job(job_id)
        return False

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def is_done(self, task: Any) -> bool:
        return self.__is_job_done(self.__get_id(task))

    def is_finished(self, task: Any) -> bool:
        return self.is_done(task)

    def is_success(self, task: Any) -> bool:
        file_key = self.__get_file_key(getattr(task, "fileitem", None))
        for job in self._job_view.values():
            for existing in self._job_tasks(job):
                if self.__get_file_key(existing.fileitem) == file_key:
                    return existing.state == "completed"
        return False

    def success_tasks(self, *args: Any, **kwargs: Any) -> List[Any]:
        return [
            task
            for job in self._job_view.values()
            for task in self._job_tasks(job)
            if task.state == "completed"
        ]

    def all_tasks(self, *args: Any, **kwargs: Any) -> List[Any]:
        return [task for job in self._job_view.values() for task in self._job_tasks(job)]

    def count(self, *args: Any, **kwargs: Any) -> int:
        return len(self.all_tasks())

    def size(self, *args: Any, **kwargs: Any) -> int:
        return len(self._job_view)

    def total(self, *args: Any, **kwargs: Any) -> int:
        return self.count()

    def pending_total(self, *args: Any, **kwargs: Any) -> int:
        return sum(
            1
            for task in self.all_tasks()
            if task.state not in ("completed", "failed")
        )

    def has_tasks(self, *args: Any, **kwargs: Any) -> bool:
        return bool(self._job_view)

    def list_jobs(self, *args: Any, **kwargs: Any) -> List[Any]:
        return list(self._job_view.keys())

    def season_episodes(self, mediainfo: Any = None, season: Optional[int] = None):
        """返回已汇总的季集清单。"""
        job_id = self.__get_media_id(media=mediainfo, season=season)
        return self._season_episodes.get(job_id)

    def get_all_torrent_hashes(self, *args: Any, **kwargs: Any) -> List[str]:
        return [
            hash_value
            for task in self.all_tasks()
            if (hash_value := getattr(task, "download_hash", None))
        ]

    def is_torrent_done(self, download_hash: str) -> bool:
        matched = [
            task for task in self.all_tasks() if task.download_hash == download_hash
        ]
        return bool(matched) and all(t.state in ("completed", "failed") for t in matched)

    def is_torrent_success(self, download_hash: str) -> bool:
        return any(
            task.download_hash == download_hash and task.state == "completed"
            for task in self.all_tasks()
        )

    def expire_stale_running_tasks(self, *args: Any, **kwargs: Any):
        """失活清理替身：无操作。"""
        return []

    def __repr__(self) -> str:
        return f"JobManager(jobs={len(self._job_view)}, tasks={self.count()})"
