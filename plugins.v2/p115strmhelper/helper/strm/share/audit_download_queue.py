from __future__ import annotations

from json import JSONDecodeError, dumps, loads
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import time
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from uuid import uuid4

from app.chain.transfer import TransferChain
from app.log import logger
from app.schemas import FileItem, NotificationType

from ....core.cache import rename_media_fields_cacher
from ....core.config import configer
from ....core.i18n import i18n
from ....core.message import post_message
from ....utils.limiter import RateLimiter
from ....utils.rename_dict import RenameDictUtils

if TYPE_CHECKING:
    from ...mediainfo_download import MediaInfoDownloader


class ShareAuditDownloadQueue:
    """
    分享文件审核等待下载队列

    将处于审核状态的分享文件批次持久化，审核通过后复用媒体信息下载器完成下载
    对需要 MoviePilot 整理的字幕和外挂音轨继续执行原有整理链
    """

    _share_state_limiter = RateLimiter(qps=0.5)
    _minimum_valid_download_size = 100

    def __init__(self) -> None:
        self._downloader: Optional[MediaInfoDownloader] = None
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        self._wake_event = Event()
        self._stop_event = Event()
        self._worker_thread: Optional[Thread] = None
        self._persist_path: Optional[Path] = None

    def bind_downloader(self, downloader: MediaInfoDownloader) -> None:
        """
        绑定媒体信息下载器

        :param downloader (MediaInfoDownloader): 媒体信息下载器实例
        """
        self._downloader = downloader

    def start(self) -> None:
        """
        启动审核等待队列并恢复持久化任务
        """
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                self._stop_event.clear()
                self._wake_event.set()
                return
            self._load_tasks_locked()
            self._stop_event.clear()
            self._wake_event.clear()
            self._worker_thread = Thread(
                target=self._worker,
                name="P115ShareAuditDownloadQueue",
                daemon=True,
            )
            self._worker_thread.start()
        logger.info(
            f"【分享审核下载】队列已启动，恢复 {self.pending_item_count()} 个文件"
        )

    def stop(self) -> None:
        """
        停止审核等待队列
        """
        self._stop_event.set()
        self._wake_event.set()
        worker = self._worker_thread
        if worker and worker.is_alive() and worker is not current_thread():
            worker.join(timeout=10)
        if not worker or not worker.is_alive():
            self._worker_thread = None

    def partition_downloads(
        self, downloads_list: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int, List[str]]:
        """
        按分享审核状态分流待下载文件

        :param downloads_list (List): 分享文件下载项

        :return Tuple: 可立即下载项、进入等待队列数量、永久失败路径
        """
        if not configer.share_audit_queue_enabled:
            return downloads_list, 0, []

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        immediate: List[Dict[str, Any]] = []
        terminal_failures: List[str] = []
        queued_count = 0
        for item in downloads_list:
            share_code = str(item.get("share_code") or "")
            receive_code = str(item.get("receive_code") or "")
            if not share_code:
                immediate.append(item)
                continue
            grouped.setdefault((share_code, receive_code), []).append(item)

        for (share_code, receive_code), items in grouped.items():
            state = self.get_share_state(share_code, receive_code)
            if state == 0:
                queued_count += self.enqueue(share_code, receive_code, items)
            elif state == 7:
                paths = [Path(item["path"]).as_posix() for item in items]
                terminal_failures.extend(paths)
                logger.error(
                    f"【分享审核下载】分享已失效，跳过 {len(items)} 个文件: "
                    f"{share_code}"
                )
            else:
                immediate.extend(items)
        return immediate, queued_count, terminal_failures

    def enqueue(
        self,
        share_code: str,
        receive_code: str,
        items: List[Dict[str, Any]],
    ) -> int:
        """
        将审核中的分享文件加入等待队列

        :param share_code (str): 分享码
        :param receive_code (str): 接收码
        :param items (List): 分享文件下载项

        :return int: 实际新增文件数量
        """
        new_items, _ = self._enqueue_items(share_code, receive_code, items)
        return len(new_items)

    def _enqueue_items(
        self,
        share_code: str,
        receive_code: str,
        items: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        now = time()
        deadline_at = now + configer.share_audit_max_wait_seconds
        normalized_items = [self._serialize_item(item) for item in items]
        with self._lock:
            pending_items = {
                self._item_key(item): item
                for task in self._tasks.values()
                for item in task.get("items", [])
            }
            upgraded_items = []
            protected_items = []
            already_protected_items = []
            for item in normalized_items:
                pending_item = pending_items.get(self._item_key(item))
                if pending_item and item.get("download_required"):
                    protected_items.append(pending_item)
                    if pending_item.get("download_required"):
                        already_protected_items.append(pending_item)
                    else:
                        pending_item["download_required"] = True
                        upgraded_items.append(pending_item)
            new_items = [
                item
                for item in normalized_items
                if self._item_key(item) not in pending_items
            ]
            if not new_items and not upgraded_items:
                return [], already_protected_items
            task_id = None
            if new_items:
                task_id = str(uuid4())
                self._tasks[task_id] = {
                    "task_id": task_id,
                    "share_code": share_code,
                    "receive_code": receive_code,
                    "items": new_items,
                    "created_at": now,
                    "deadline_at": deadline_at,
                    "next_retry_at": min(
                        now + configer.share_audit_retry_interval_seconds,
                        deadline_at,
                    ),
                    "attempt_count": 0,
                    "last_error": "分享文件审核中",
                }
            if not self._save_tasks_locked():
                if task_id:
                    self._tasks.pop(task_id, None)
                for upgraded_item in upgraded_items:
                    upgraded_item.pop("download_required", None)
                return [], already_protected_items
        self._wake_event.set()
        if not new_items:
            return [], protected_items
        logger.info(
            f"【分享审核下载】{len(new_items)} 个文件已进入等待队列，"
            f"分享码: {share_code}，将在 "
            f"{configer.share_audit_retry_interval_seconds // 60} 分钟后检查"
        )
        self._notify(
            share_code=share_code,
            count=len(new_items),
            status="queued",
        )
        return new_items, protected_items

    def enqueue_failed_auditing_downloads(
        self, items: List[Dict[str, Any]]
    ) -> List[str]:
        """
        将下载期间再次进入审核状态的失败文件加入队列

        :param items (List): 本轮下载失败的分享文件项

        :return List: 已转入等待队列的文件路径
        """
        if not configer.share_audit_queue_enabled:
            return []
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for item in items:
            share_code = str(item.get("share_code") or "")
            receive_code = str(item.get("receive_code") or "")
            if share_code:
                grouped.setdefault((share_code, receive_code), []).append(item)

        queued_paths: List[str] = []
        queued_path_set: Set[str] = set()
        for (share_code, receive_code), grouped_items in grouped.items():
            if self.get_share_state(share_code, receive_code) != 0:
                continue
            pending_items = []
            for item in grouped_items:
                pending_item = dict(item)
                pending_item["download_required"] = True
                pending_items.append(pending_item)
            new_items, protected_items = self._enqueue_items(
                share_code,
                receive_code,
                pending_items,
            )
            for queued_item in new_items + protected_items:
                path = Path(queued_item["path"])
                path_str = path.as_posix()
                if path_str in queued_path_set:
                    continue
                self._remove_invalid_download(path)
                queued_paths.append(path_str)
                queued_path_set.add(path_str)
        return queued_paths

    def get_share_state(self, share_code: str, receive_code: str) -> Optional[int]:
        """
        查询分享审核状态

        :param share_code (str): 分享码
        :param receive_code (str): 接收码

        :return int: 0 为审核中，1 为正常，7 为失效，查询失败返回 None
        """
        if not self._downloader:
            return None
        try:
            self._share_state_limiter.acquire()
            resp = self._downloader.client.share_snap_app(
                {
                    "share_code": share_code,
                    "receive_code": receive_code,
                    "cid": 0,
                    "limit": 1,
                },
                app="android",
                **configer.get_ios_ua_app(app=False),
            )
            data = resp.get("data") or {}
            share_info = data.get("shareinfo") or data.get("share_info") or {}
            state = data.get(
                "share_state",
                share_info.get("share_state", share_info.get("status")),
            )
            return int(state) if state is not None else None
        except Exception as e:
            logger.warning(f"【分享审核下载】查询分享状态失败: {share_code}，原因: {e}")
            return None

    def pending_item_count(self) -> int:
        """
        获取等待队列中的文件数量

        :return int: 待处理文件数量
        """
        with self._lock:
            return sum(len(task.get("items", [])) for task in self._tasks.values())

    def prepare_media_fields(self, item: Dict[str, Any]) -> bool:
        """
        根据持久化主视频上下文恢复伴随文件媒体字段

        :param item (Dict): 分享文件下载项

        :return bool: 是否准备好媒体字段
        """
        if not configer.rename_dict_supplement_enabled:
            return False
        relation_key = str(item.get("media_relation_key") or "")
        context = item.get("related_media")
        if not relation_key or not isinstance(context, dict):
            return False
        cached = rename_media_fields_cacher.get(relation_key)
        if isinstance(cached, dict) and cached:
            return True

        media_info: Dict[str, Any] = {}
        sha1 = str(context.get("sha1") or "")
        size = context.get("size")
        if sha1 and self._downloader:
            try:
                resp = self._downloader.p115_center.download_emby_mediainfo_data(
                    [(sha1, size)]
                )
                payload = None
                if isinstance(resp, dict):
                    payload = resp.get(sha1.upper()) or resp.get(sha1)
                if payload:
                    media_info = (
                        RenameDictUtils.emby_mediainfo_to_rename_fields(payload) or {}
                    )
            except Exception as e:
                logger.warning(f"【分享审核下载】中心化恢复主视频媒体字段失败: {e}")

        if not media_info and context.get("strm_url"):
            media_info, error_message = RenameDictUtils.ffprobe_get_media_info(
                url=str(context["strm_url"])
            )
            if not media_info:
                logger.warning(
                    f"【分享审核下载】探测主视频媒体字段失败: {error_message}"
                )
                return False

        if not media_info:
            return False
        rename_media_fields_cacher.set(relation_key, media_info)
        logger.info(
            f"【分享审核下载】已恢复伴随文件的主视频媒体字段: {item.get('path')}"
        )
        return True

    def transfer_local_file(
        self, path: Path, item: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        将已下载本地文件提交给 MoviePilot 整理

        :param path (Path): 本地文件路径
        :param item (Dict): 分享文件下载项

        :return bool: 是否成功提交整理
        """
        try:
            if item:
                self.prepare_media_fields(item)
            stat = path.stat()
            TransferChain().do_transfer(
                fileitem=FileItem(
                    storage="local",
                    type="file",
                    path=path.as_posix(),
                    name=path.name,
                    basename=path.stem,
                    extension=path.suffix[1:].lower(),
                    size=stat.st_size,
                    modify_time=stat.st_mtime,
                )
            )
            logger.info(f"【分享审核下载】已提交 MoviePilot 整理: {path}")
            return True
        except Exception as e:
            logger.error(
                f"【分享审核下载】提交 MoviePilot 整理失败: {path}，原因: {e}",
                exc_info=True,
            )
            return False

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            task = self._next_due_task()
            if task:
                self._process_task(task)
                continue
            self._wake_event.wait(timeout=60)
            self._wake_event.clear()

    def _next_due_task(self) -> Optional[Dict[str, Any]]:
        now = time()
        with self._lock:
            due_tasks = [
                task
                for task in self._tasks.values()
                if float(task.get("next_retry_at") or 0) <= now
            ]
            if not due_tasks:
                return None
            task = min(due_tasks, key=lambda item: item.get("next_retry_at") or 0)
            return dict(task)

    def _process_task(self, task: Dict[str, Any]) -> None:
        task_id = str(task["task_id"])
        share_code = str(task["share_code"])
        receive_code = str(task.get("receive_code") or "")
        now = time()
        deadline_reached = now >= float(task.get("deadline_at") or 0)
        state = self.get_share_state(share_code, receive_code)
        if state == 0 or state is None:
            if deadline_reached:
                self._finish_task(
                    task_id,
                    i18n.translate(
                        "share_audit_notify_reason_timeout",
                        hours=configer.share_audit_max_wait_seconds // 3600,
                    ),
                )
                return
            reason = "分享文件仍在审核中" if state == 0 else "分享状态查询失败"
            self._reschedule_task(task_id, reason)
            return
        if state == 7:
            self._finish_task(
                task_id,
                i18n.translate("share_audit_notify_reason_expired"),
            )
            return
        if not self._downloader:
            self._reschedule_task(task_id, "媒体信息下载器未初始化")
            return

        serialized_items = task.get("items", [])
        items = [self._deserialize_item(item) for item in serialized_items]
        logger.info(
            f"【分享审核下载】审核已通过，开始下载 {len(items)} 个文件: {share_code}"
        )
        download_items = [
            item
            for item in items
            if item.get("download_required")
            or not self._is_downloaded(Path(item["path"]))
        ]
        reported_failure_paths: Set[str] = set()
        if download_items:
            try:
                _, _, failure_paths = self._downloader.batch_auto_share_downloader(
                    download_items
                )
                reported_failure_paths = {
                    Path(path).as_posix() for path in (failure_paths or [])
                }
            except Exception as e:
                reported_failure_paths = {
                    Path(item["path"]).as_posix() for item in download_items
                }
                logger.error(
                    f"【分享审核下载】延迟下载异常: {share_code}，原因: {e}",
                    exc_info=True,
                )

        download_failures: List[Dict[str, Any]] = []
        post_action_failures: List[Dict[str, Any]] = []
        for serialized_item, item in zip(serialized_items, items):
            path = Path(item["path"])
            if path.as_posix() in reported_failure_paths or not self._is_downloaded(
                path
            ):
                self._remove_invalid_download(path)
                download_failures.append(serialized_item)
                continue
            serialized_item.pop("download_required", None)
            if item.get("mp_transfer_after_download"):
                if not self.transfer_local_file(path, item):
                    post_action_failures.append(serialized_item)

        if not download_failures and not post_action_failures:
            self._remove_task(task_id)
            logger.info(
                f"【分享审核下载】延迟任务完成，共 {len(items)} 个文件: {share_code}"
            )
            self._notify(
                share_code=share_code,
                count=len(items),
                status="success",
            )
            return

        completed_count = (
            len(items) - len(download_failures) - len(post_action_failures)
        )
        if completed_count:
            self._notify(
                share_code=share_code,
                count=completed_count,
                status="success",
            )

        if download_failures:
            latest_state = self.get_share_state(share_code, receive_code)
            if latest_state != 0:
                reason = i18n.translate("share_audit_notify_reason_download_failed")
                logger.error(
                    f"【分享审核下载】审核通过后仍有 {len(download_failures)} "
                    f"个文件下载失败，分享码: {share_code}"
                )
                self._notify(
                    share_code=share_code,
                    count=len(download_failures),
                    status="failure",
                    detail=reason,
                )
                if post_action_failures:
                    self._replace_items_and_reschedule(
                        task_id,
                        post_action_failures,
                        f"{len(post_action_failures)} 个文件提交 MoviePilot 整理失败",
                    )
                else:
                    self._remove_task(task_id)
                return
            self._replace_items_and_reschedule(
                task_id,
                download_failures + post_action_failures,
                "下载时分享再次进入审核状态",
            )
            return
        self._replace_items_and_reschedule(
            task_id,
            post_action_failures,
            f"{len(post_action_failures)} 个文件提交 MoviePilot 整理失败",
        )

    def _reschedule_task(self, task_id: str, reason: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
            task["last_error"] = reason
            task["next_retry_at"] = min(
                time() + configer.share_audit_retry_interval_seconds,
                float(task.get("deadline_at") or 0),
            )
            self._save_tasks_locked()
        logger.info(
            f"【分享审核下载】{reason}，将在 "
            f"{configer.share_audit_retry_interval_seconds // 60} 分钟后重试"
        )

    def _replace_items_and_reschedule(
        self, task_id: str, items: List[Dict[str, Any]], reason: str
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["items"] = items
            task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
            task["last_error"] = reason
            task["next_retry_at"] = min(
                time() + configer.share_audit_retry_interval_seconds,
                float(task.get("deadline_at") or 0),
            )
            self._save_tasks_locked()

    def _finish_task(self, task_id: str, reason: str) -> None:
        with self._lock:
            task = self._tasks.pop(task_id, None)
            self._save_tasks_locked()
        if task:
            item_count = len(task.get("items", []))
            logger.error(
                f"【分享审核下载】任务终止，共 {item_count} 个文件，"
                f"分享码: {task.get('share_code')}，原因: {reason}"
            )
            self._notify(
                share_code=str(task.get("share_code") or ""),
                count=item_count,
                status="failure",
                detail=reason,
            )

    def _remove_task(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
            self._save_tasks_locked()

    @staticmethod
    def _notify(
        share_code: str,
        count: int,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        if not configer.notify or count <= 0:
            return
        if status == "queued":
            title = i18n.translate("share_audit_notify_queued_title")
            count_line = i18n.translate("share_audit_notify_queued_count", count=count)
        elif status == "success":
            title = i18n.translate("share_audit_notify_success_title")
            count_line = i18n.translate("share_audit_notify_success_count", count=count)
        else:
            title = i18n.translate("share_audit_notify_failure_title")
            count_line = i18n.translate("share_audit_notify_failure_count", count=count)
        lines = [
            i18n.translate("share_audit_notify_share_code", share_code=share_code),
            count_line,
        ]
        if status == "queued":
            lines.append(
                i18n.translate(
                    "share_audit_notify_retry",
                    minutes=configer.share_audit_retry_interval_seconds // 60,
                )
            )
        elif detail:
            lines.append(i18n.translate("share_audit_notify_reason", reason=detail))
        try:
            post_message(
                mtype=NotificationType.Plugin,
                title=title,
                text="\n" + "\n".join(lines),
            )
        except Exception as e:
            logger.error(f"【分享审核下载】发送通知失败: {e}", exc_info=True)

    @staticmethod
    def _serialize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        serialized = dict(item)
        serialized["path"] = Path(item["path"]).as_posix()
        return serialized

    @staticmethod
    def _deserialize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        deserialized = dict(item)
        deserialized["path"] = Path(item["path"])
        return deserialized

    @staticmethod
    def _item_key(item: Dict[str, Any]) -> str:
        return (
            f"{item.get('share_code')}:{item.get('file_id')}:"
            f"{Path(item['path']).as_posix()}"
        )

    @classmethod
    def _is_downloaded(cls, path: Path) -> bool:
        try:
            return (
                path.is_file()
                and path.stat().st_size > cls._minimum_valid_download_size
            )
        except OSError:
            return False

    @staticmethod
    def _remove_invalid_download(path: Path) -> None:
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            logger.warning(f"【分享审核下载】清理下载失败文件异常: {path}，原因: {e}")

    def _get_persist_path(self) -> Path:
        if self._persist_path is None:
            self._persist_path = (
                configer.PLUGIN_CONFIG_PATH / "share_audit_download_queue.json"
            )
        return self._persist_path

    def _load_tasks_locked(self) -> None:
        path = self._get_persist_path()
        if not path.exists():
            self._tasks = {}
            return
        try:
            data = loads(path.read_text(encoding="utf-8"))
            self._tasks = {
                str(task["task_id"]): task
                for task in data
                if isinstance(task, dict) and task.get("task_id")
            }
        except (OSError, JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"【分享审核下载】读取持久化任务失败，将使用空队列: {e}")
            self._tasks = {}

    def _save_tasks_locked(self) -> bool:
        path = self._get_persist_path()
        temp_path = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                dumps(
                    list(self._tasks.values()),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temp_path.replace(path)
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"【分享审核下载】保存持久化任务失败: {e}")
            return False


share_audit_download_queue = ShareAuditDownloadQueue()
