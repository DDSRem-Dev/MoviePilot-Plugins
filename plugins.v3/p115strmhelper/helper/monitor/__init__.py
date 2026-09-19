from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from re import search as re_search, IGNORECASE
from shutil import rmtree
from threading import Event, Lock, Thread
from time import monotonic, sleep
from traceback import format_exc
from typing import Dict, List, Optional, Set, Tuple

from p115client import P115Client
from p115client.tool import get_attr, get_id_to_path

from app.chain.storage import StorageChain
from app.log import logger
from app.schemas import FileItem
from app.utils.system import SystemUtils

from ...core.config import configer
from ...helper.strm import MonitorStrmHelper
from ...utils.sentry import sentry_manager
from .directory_upload_queue import DirectoryUploadTask, directory_upload_queue


class _KeyedLock:
    """
    按 key 串行化的锁集合，使用引用计数在无人持有时回收锁对象
    """

    def __init__(self) -> None:
        self._locks: Dict[str, Lock] = {}
        self._counts: Dict[str, int] = {}
        self._guard = Lock()

    @contextmanager
    def acquire(self, key: str):
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = Lock()
                self._locks[key] = lock
                self._counts[key] = 0
            self._counts[key] += 1
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                self._counts[key] -= 1
                if self._counts[key] <= 0:
                    self._locks.pop(key, None)
                    self._counts.pop(key, None)


directory_upload_keyed_lock = _KeyedLock()

FileSignature = Tuple[int, int, int]
DirectoryFingerprintEntry = Tuple[str, str, FileSignature]
DirectoryFingerprint = Tuple[DirectoryFingerprintEntry, ...]
DirectoryScanResult = Tuple[DirectoryFingerprint, List[Tuple[str, FileSignature]], bool]

directory_upload_processed: "OrderedDict[Tuple[str, str], Tuple[int, int, int, float]]" = OrderedDict()
directory_upload_processed_lock = Lock()
DIRECTORY_UPLOAD_PROCESSED_MAX = 4096
DIRECTORY_UPLOAD_PROCESSED_TTL = 600

DIRECTORY_STABLE_INTERVAL = 2.0
DIRECTORY_STABLE_CHECKS = 3
DIRECTORY_UNSTABLE_WARN_INTERVAL = 300.0
DIRECTORY_EMPTY_SCAN_TTL = 300.0


def _path_signature(path: Path) -> Optional[FileSignature]:
    """
    获取路径的签名（size, mtime_ns, ctime_ns），用于稳定性比对

    :param path (Path): 文件或目录路径
    :return Tuple: 文件签名，stat 失败时返回 None
    """
    try:
        st = path.stat()
        return st.st_size, st.st_mtime_ns, st.st_ctime_ns
    except OSError:
        return None


def _file_signature(file_path: Path) -> Optional[FileSignature]:
    """
    获取文件的签名（size, mtime_ns, ctime_ns），用于去重比对

    :param file_path (Path): 文件路径
    :return Tuple: 文件签名，stat 失败时返回 None
    """
    return _path_signature(file_path)


def _upload_key(file_path: Path, mon_path: str) -> Tuple[str, str]:
    """
    生成目录上传去重身份

    :param file_path (Path): 文件路径
    :param mon_path (str): 监控根目录

    :return Tuple: 去重身份
    """
    return str(file_path.absolute()), str(Path(mon_path).absolute())


def _is_directory_upload_ignored_path(path: Path) -> bool:
    """
    判断目录上传是否应忽略指定路径

    :param path (Path): 文件或目录路径

    :return bool: 应忽略时返回 True
    """
    event_path = str(path)
    if (
        event_path.find("/@Recycle/") != -1
        or event_path.find("/#recycle/") != -1
        or event_path.find("/.") != -1
        or event_path.find("/@eaDir") != -1
    ):
        return True
    if configer.directory_upload_skip_bdmv_stream and re_search(
        r"BDMV[/\\]STREAM", event_path, IGNORECASE
    ):
        return True
    return False


def _directory_upload_extensions(config_key: str) -> Optional[List[str]]:
    """
    读取目录上传扩展名配置

    配置值为空或 * 时表示匹配任意后缀

    :param config_key (str): 配置项名称

    :return List: 扩展名列表，None 表示不限制后缀
    """
    value = configer.get_config(config_key) or ""
    value = value.replace("，", ",").strip()
    if not value or value == "*":
        return None
    return [
        f".{ext.strip().lower().lstrip('.')}" for ext in value.split(",") if ext.strip()
    ]


def _is_directory_upload_candidate(file_path: Path) -> bool:
    """
    判断文件是否需要进入目录上传稳定性跟踪

    :param file_path (Path): 文件路径

    :return bool: 需要后续上传或复制处理时返回 True
    """
    if not file_path.exists() or not file_path.is_file():
        return False

    if _is_directory_upload_ignored_path(file_path):
        return False

    upload_extensions = _directory_upload_extensions("directory_upload_uploadext")
    copy_extensions = _directory_upload_extensions("directory_upload_copyext")
    if upload_extensions is None or copy_extensions is None:
        return True
    return file_path.suffix.lower() in set(upload_extensions + copy_extensions)


def _is_directory_scan_candidate(directory_path: Path) -> bool:
    """
    判断目录是否需要进入补偿扫描

    :param directory_path (Path): 目录路径

    :return bool: 需要补偿扫描时返回 True
    """
    if not directory_path.exists() or not directory_path.is_dir():
        return False

    return not _is_directory_upload_ignored_path(directory_path)


def _is_recently_processed(
    upload_key: Tuple[str, str],
    signature: FileSignature,
) -> bool:
    """
    判断文件是否在 TTL 时间窗内已按相同签名处理过

    :param upload_key (Tuple): 去重身份
    :param signature (Tuple): 文件签名
    :return bool: 处理时间未过期且签名一致返回 True
    """
    now = monotonic()
    with directory_upload_processed_lock:
        cached = directory_upload_processed.get(upload_key)
        if cached is None:
            return False
        size, mtime, ctime, processed_at = cached
        if now - processed_at > DIRECTORY_UPLOAD_PROCESSED_TTL:
            del directory_upload_processed[upload_key]
            return False
        return (size, mtime, ctime) == signature


def _mark_processed(upload_key: Tuple[str, str], signature: FileSignature) -> None:
    """
    记录文件已处理签名与处理时刻，超出容量时按 LRU 淘汰最旧条目

    :param upload_key (Tuple): 去重身份
    :param signature (Tuple): 文件签名
    """
    with directory_upload_processed_lock:
        directory_upload_processed[upload_key] = (
            signature[0],
            signature[1],
            signature[2],
            monotonic(),
        )
        directory_upload_processed.move_to_end(upload_key)
        while len(directory_upload_processed) > DIRECTORY_UPLOAD_PROCESSED_MAX:
            directory_upload_processed.popitem(last=False)


@dataclass
class _StabilityState:
    """
    单个文件的稳定性跟踪状态

    Attributes:
        client: 115 客户端
        file_path: 文件路径
        mon_path: 监控根目录
        signature: 最近一次观测的文件签名
        stable_count: 连续观测到签名不变的次数
        first_seen: 首次提交时刻 monotonic，用于等待时长统计
        last_warned: 最近一次未稳定告警时刻 monotonic
    """

    client: P115Client
    file_path: str
    mon_path: str
    signature: Optional[FileSignature]
    stable_count: int
    first_seen: float
    last_warned: float


@dataclass
class _DirectoryScanState:
    """
    单个目录的补偿扫描状态

    Attributes:
        client: 115 客户端
        dir_path: 目录路径
        mon_path: 监控根目录
        fingerprint: 最近一次观测的目录树指纹
        stable_count: 连续观测到目录指纹不变的次数
        seen_candidate: 是否已发现过需要上传或复制的候选文件
        first_seen: 首次提交时刻 monotonic，用于等待时长统计
        last_warned: 最近一次未稳定告警时刻 monotonic
    """

    client: P115Client
    dir_path: str
    mon_path: str
    fingerprint: Optional[DirectoryFingerprint]
    stable_count: int
    seen_candidate: bool
    first_seen: float
    last_warned: float


class DirectoryStabilityTracker:
    """
    文件稳定性异步跟踪器

    目录补偿扫描发现的文件先提交到此跟踪器，由独立线程周期性复查 size/mtime，
    待文件稳定后再交给上传队列，从而不在上传 worker 内阻塞等待，
    也不受目录事件先后顺序影响；文件未稳定时持续等待并周期告警，
    避免上传仍在写入的半文件
    """

    def __init__(
        self,
        interval: float = DIRECTORY_STABLE_INTERVAL,
        stable_checks: int = DIRECTORY_STABLE_CHECKS,
        unstable_warn_interval: float = DIRECTORY_UNSTABLE_WARN_INTERVAL,
    ) -> None:
        self._interval = interval
        self._stable_checks = stable_checks
        self._unstable_warn_interval = unstable_warn_interval
        self._pending: Dict[Tuple[str, str], _StabilityState] = {}
        self._pending_directories: Dict[Tuple[str, str], _DirectoryScanState] = {}
        self._queued: "OrderedDict[Tuple[str, str], Tuple[int, int, int, float]]" = (
            OrderedDict()
        )
        self._lock = Lock()
        self._thread: Optional[Thread] = None
        self._stop_event: Optional[Event] = None

    def _is_recently_queued_locked(
        self,
        upload_key: Tuple[str, str],
        signature: FileSignature,
    ) -> bool:
        """
        判断文件是否已在近期按相同签名投递到上传队列

        :param upload_key (Tuple): 去重身份
        :param signature (Tuple): 文件签名

        :return bool: 已投递且签名一致返回 True
        """
        now = monotonic()
        cached = self._queued.get(upload_key)
        if cached is None:
            return False
        size, mtime, ctime, queued_at = cached
        if now - queued_at > DIRECTORY_UPLOAD_PROCESSED_TTL:
            del self._queued[upload_key]
            return False
        return (size, mtime, ctime) == signature

    def _mark_queued_locked(
        self,
        upload_key: Tuple[str, str],
        signature: FileSignature,
    ) -> None:
        """
        记录文件已投递到上传队列，避免目录扫描重复投递

        :param upload_key (Tuple): 去重身份
        :param signature (Tuple): 文件签名
        """
        self._queued[upload_key] = (
            signature[0],
            signature[1],
            signature[2],
            monotonic(),
        )
        self._queued.move_to_end(upload_key)
        while len(self._queued) > DIRECTORY_UPLOAD_PROCESSED_MAX:
            self._queued.popitem(last=False)

    def clear_queued(
        self,
        file_path: str,
        mon_path: str,
        signature: Optional[FileSignature] = None,
    ) -> None:
        """
        清理文件的近期入队记录，允许失败后重新投递

        :param file_path (str): 文件路径
        :param mon_path (str): 监控根目录
        :param signature (Tuple): 仅清理匹配签名的入队记录
        """
        upload_key = _upload_key(Path(file_path), mon_path)
        with self._lock:
            if signature is None:
                self._queued.pop(upload_key, None)
                return
            cached = self._queued.get(upload_key)
            if cached is None:
                return
            if (cached[0], cached[1], cached[2]) == signature:
                del self._queued[upload_key]

    def _restore_pending_after_enqueue_failure(self, state: _StabilityState) -> None:
        """
        入队失败后恢复待稳定任务，避免服务停止窗口丢失处理

        :param state (_StabilityState): 文件稳定性跟踪状态
        """
        path = Path(state.file_path)
        if not _is_directory_upload_candidate(path):
            return
        upload_key = _upload_key(path, state.mon_path)
        signature = _file_signature(path)
        if signature is None or _is_recently_processed(upload_key, signature):
            return
        with self._lock:
            if upload_key in self._pending:
                return
            state.signature = signature
            state.stable_count = 0
            state.first_seen = monotonic()
            state.last_warned = 0.0
            self._pending[upload_key] = state

    def _submit_file_locked(
        self,
        client: P115Client,
        file_path: str,
        mon_path: str,
        signature: Optional[FileSignature] = None,
    ) -> bool:
        """
        在锁内提交一个待稳定确认的文件

        :param client (P115Client): 115 客户端
        :param file_path (str): 文件路径
        :param mon_path (str): 监控根目录
        :param signature (Tuple): 已知文件签名

        :return bool: 成功加入待处理集合时返回 True
        """
        path = Path(file_path)
        if not _is_directory_upload_candidate(path):
            return False
        upload_key = _upload_key(path, mon_path)
        current_signature = signature or _file_signature(path)
        if current_signature is None:
            return False
        if _is_recently_processed(upload_key, current_signature):
            return False
        if self._is_recently_queued_locked(upload_key, current_signature):
            return False
        if upload_key in self._pending:
            return False
        self._pending[upload_key] = _StabilityState(
            client=client,
            file_path=file_path,
            mon_path=mon_path,
            signature=current_signature,
            stable_count=0,
            first_seen=monotonic(),
            last_warned=0.0,
        )
        return True

    def submit(self, client: P115Client, file_path: str, mon_path: str) -> None:
        """
        提交一个待稳定确认的文件，已在跟踪中或近期已处理则忽略

        :param client (P115Client): 115 客户端
        :param file_path (str): 文件路径
        :param mon_path (str): 监控根目录
        """
        with self._lock:
            self._submit_file_locked(client, file_path, mon_path)

    def submit_directory(
        self,
        client: P115Client,
        dir_path: str,
        mon_path: str,
    ) -> None:
        """
        提交一个待补偿扫描的目录，持续扫描直到目录候选文件稳定

        :param client (P115Client): 115 客户端
        :param dir_path (str): 目录路径
        :param mon_path (str): 监控根目录
        """
        path = Path(dir_path)
        if not _is_directory_scan_candidate(path):
            return
        upload_key = _upload_key(path, mon_path)
        with self._lock:
            if upload_key in self._pending_directories:
                self._pending_directories[upload_key].client = client
                return
            self._pending_directories[upload_key] = _DirectoryScanState(
                client=client,
                dir_path=dir_path,
                mon_path=mon_path,
                fingerprint=None,
                stable_count=0,
                seen_candidate=False,
                first_seen=monotonic(),
                last_warned=0.0,
            )

    def _scan_directory(
        self,
        dir_path: str,
    ) -> Optional[DirectoryScanResult]:
        """
        扫描目录树并生成目录指纹

        :param dir_path (str): 目录路径

        :return Tuple: 目录指纹、候选文件列表与是否存在扫描错误，目录不可扫描时返回 None
        """
        path = Path(dir_path)
        if not _is_directory_scan_candidate(path):
            return None
        candidates: List[Tuple[str, FileSignature]] = []
        fingerprint_entries: List[DirectoryFingerprintEntry] = []
        pending_directories: List[Path] = [path]
        visited_directories: Set[str] = set()
        scan_failed = False
        while pending_directories:
            current_dir = pending_directories.pop()
            try:
                resolved_dir = str(current_dir.resolve())
            except (OSError, RuntimeError) as e:
                logger.debug(f"【目录上传】解析目录 {current_dir} 失败: {e}")
                scan_failed = True
                continue
            if resolved_dir in visited_directories:
                continue
            visited_directories.add(resolved_dir)
            try:
                for sub in current_dir.iterdir():
                    if _is_directory_upload_ignored_path(sub):
                        continue
                    if sub.is_symlink():
                        continue
                    signature = _path_signature(sub)
                    if signature is None:
                        scan_failed = True
                        continue
                    if sub.is_dir():
                        fingerprint_entries.append(
                            (str(sub.absolute()), "dir", signature)
                        )
                        pending_directories.append(sub)
                        continue
                    if not sub.is_file():
                        continue
                    fingerprint_entries.append((str(sub.absolute()), "file", signature))
                    if not _is_directory_upload_candidate(sub):
                        continue
                    candidates.append((str(sub), signature))
            except OSError as e:
                logger.debug(f"【目录上传】扫描目录 {current_dir} 失败: {e}")
                scan_failed = True
                continue
        fingerprint = tuple(sorted(fingerprint_entries))
        return fingerprint, candidates, scan_failed

    def _tick(self) -> None:
        """
        复查所有待处理文件，稳定者交给上传队列
        """
        ready: List[_StabilityState] = []
        directories: List[Tuple[Tuple[str, str], _DirectoryScanState]] = []
        # 先在锁内取待处理文件快照，stat 在锁外执行，避免持锁做 I/O 阻塞 submit
        with self._lock:
            pending_snapshot = [
                (upload_key, state.file_path)
                for upload_key, state in self._pending.items()
            ]
        file_signatures = {
            upload_key: _file_signature(Path(file_path))
            for upload_key, file_path in pending_snapshot
        }
        with self._lock:
            now = monotonic()
            for upload_key, signature in file_signatures.items():
                state = self._pending.get(upload_key)
                if state is None:
                    continue
                if signature is None:
                    # 文件已被处理/删除/移动，停止跟踪
                    del self._pending[upload_key]
                    continue
                if _is_recently_processed(upload_key, signature):
                    del self._pending[upload_key]
                    continue
                if signature == state.signature:
                    state.stable_count += 1
                else:
                    state.signature = signature
                    state.stable_count = 0
                if state.stable_count >= self._stable_checks:
                    if state.signature is not None:
                        self._mark_queued_locked(upload_key, state.signature)
                    ready.append(state)
                    del self._pending[upload_key]
                    continue
                waited = now - state.first_seen
                should_warn = (
                    waited >= self._unstable_warn_interval
                    and now - state.last_warned >= self._unstable_warn_interval
                )
                if should_warn:
                    logger.warning(
                        f"【目录上传】{state.file_path} 已等待 "
                        f"{int(waited)}s 仍未稳定，继续等待"
                    )
                    state.last_warned = now
            directories = list(self._pending_directories.items())
        directory_results: List[
            Tuple[Tuple[str, str], Optional[DirectoryScanResult]]
        ] = []
        for upload_key, state in directories:
            directory_results.append((upload_key, self._scan_directory(state.dir_path)))
        with self._lock:
            now = monotonic()
            for upload_key, result in directory_results:
                state = self._pending_directories.get(upload_key)
                if state is None:
                    continue
                if result is None:
                    del self._pending_directories[upload_key]
                    continue
                fingerprint, candidates, scan_failed = result
                if candidates:
                    state.seen_candidate = True
                for candidate_path, signature in candidates:
                    self._submit_file_locked(
                        state.client,
                        candidate_path,
                        state.mon_path,
                        signature,
                    )
                if scan_failed:
                    state.stable_count = 0
                elif fingerprint == state.fingerprint:
                    state.stable_count += 1
                else:
                    state.fingerprint = fingerprint
                    state.stable_count = 0
                waited = now - state.first_seen
                can_stop_without_candidate = waited >= DIRECTORY_EMPTY_SCAN_TTL
                if state.stable_count >= self._stable_checks and (
                    state.seen_candidate or can_stop_without_candidate
                ):
                    del self._pending_directories[upload_key]
                    continue
                should_warn = (
                    waited >= self._unstable_warn_interval
                    and now - state.last_warned >= self._unstable_warn_interval
                )
                if should_warn:
                    logger.warning(
                        f"【目录上传】目录 {state.dir_path} 已等待 "
                        f"{int(waited)}s 仍未稳定，继续扫描"
                    )
                    state.last_warned = now
        for state in ready:
            enqueued = directory_upload_queue.enqueue(
                DirectoryUploadTask(
                    state.client,
                    state.file_path,
                    state.mon_path,
                    stable_ready=True,
                    stable_signature=state.signature,
                )
            )
            if not enqueued:
                self.clear_queued(state.file_path, state.mon_path, state.signature)
                self._restore_pending_after_enqueue_failure(state)

    def _run(self, stop_event: Event) -> None:
        """
        跟踪线程主循环

        :param stop_event (Event): 当前线程专属停止事件
        """
        while not stop_event.wait(self._interval):
            try:
                self._tick()
            except Exception as e:
                logger.error(f"【目录上传】稳定性跟踪异常: {e}", exc_info=True)

    def start(
        self,
        client: Optional[P115Client] = None,
        active_mon_paths: Optional[List[str]] = None,
    ) -> None:
        """
        启动跟踪线程（幂等）

        :param client (P115Client): 当前 115 客户端，用于刷新重启前保留的待处理任务
        :param active_mon_paths (List): 当前配置中的有效监控根目录
        """
        active_mon_path_set: Optional[Set[str]] = None
        if active_mon_paths is not None:
            active_mon_path_set = {
                str(Path(path).absolute()) for path in active_mon_paths if path
            }
        with self._lock:
            if active_mon_path_set is not None:
                stale_keys = [
                    upload_key
                    for upload_key, state in self._pending.items()
                    if upload_key[1] not in active_mon_path_set
                    or not _is_directory_upload_candidate(Path(state.file_path))
                ]
                for upload_key in stale_keys:
                    del self._pending[upload_key]
                stale_directory_keys = [
                    upload_key
                    for upload_key, state in self._pending_directories.items()
                    if upload_key[1] not in active_mon_path_set
                    or not _is_directory_scan_candidate(Path(state.dir_path))
                ]
                for upload_key in stale_directory_keys:
                    del self._pending_directories[upload_key]
                stale_queued_keys = [
                    upload_key
                    for upload_key in self._queued
                    if upload_key[1] not in active_mon_path_set
                ]
                for upload_key in stale_queued_keys:
                    del self._queued[upload_key]
                if stale_keys:
                    logger.debug(
                        f"【目录上传】已清理 {len(stale_keys)} 个失效监控目录待处理任务"
                    )
            if client is not None:
                for state in self._pending.values():
                    state.client = client
                for state in self._pending_directories.values():
                    state.client = client
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event is None or not self._stop_event.is_set():
                    return
                logger.warning("【目录上传】旧稳定性跟踪线程仍在退出中，启动新线程接管")
            stop_event = Event()
            self._stop_event = stop_event
            self._thread = Thread(
                target=self._run,
                args=(stop_event,),
                name="P115StrmHelper-DirectoryStability",
                daemon=True,
            )
            self._thread.start()
            logger.debug("【目录上传】稳定性跟踪线程已启动")

    def stop(self) -> None:
        """
        停止跟踪线程并保留待处理集合
        """
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
            if stop_event is not None:
                stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning("【目录上传】稳定性跟踪线程未在 10 秒内退出")
                return
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._stop_event = None


directory_upload_stability_tracker = DirectoryStabilityTracker()


@sentry_manager.capture_plugin_exceptions
def process_file_change(
    client: P115Client,
    file_path: str,
    mon_path: str,
    stable_ready: bool = False,
    stable_signature: Optional[FileSignature] = None,
) -> None:
    """
    处理 watchfiles 产生的文件变更

    :param client (P115Client): 115 客户端
    :param file_path (str): 事件文件路径
    :param mon_path (str): 监控目录
    :param stable_ready (bool): 文件是否已完成稳定性确认
    :param stable_signature (Tuple): 稳定性确认时的文件签名
    """
    p = Path(file_path)
    if stable_ready:
        try:
            if p.exists() and p.is_dir():
                logger.debug(f"【目录上传】目录 创建: {file_path}，加入补偿扫描")
                directory_upload_stability_tracker.submit_directory(
                    client, file_path, mon_path
                )
                return
            logger.debug(f"【目录上传】文件 创建: {file_path}")
            current_signature = _file_signature(p)
            if stable_signature is None or current_signature != stable_signature:
                logger.debug(f"【目录上传】{file_path} 稳定后再次变化，重新等待稳定")
                directory_upload_stability_tracker.submit(client, file_path, mon_path)
                return
            handle_file(client, file_path, mon_path, stable_signature)
            return
        finally:
            directory_upload_stability_tracker.clear_queued(
                file_path, mon_path, stable_signature
            )
    if p.exists() and p.is_dir():
        # 性能模式下新建子目录与递归 watcher 接管之间存在竞态，目录需要持续补偿扫描
        logger.debug(f"【目录上传】目录 创建: {file_path}，加入补偿扫描")
        directory_upload_stability_tracker.submit_directory(client, file_path, mon_path)
        return
    logger.debug(f"【目录上传】文件 创建: {file_path}")
    directory_upload_stability_tracker.submit(client, file_path, mon_path)


@sentry_manager.capture_plugin_exceptions
def handle_file(
    client: P115Client,
    event_path: str,
    mon_path: str,
    expected_signature: Optional[FileSignature] = None,
) -> None:
    """
    同步一个文件

    :param client (P115Client): 115 客户端
    :param event_path (str): 事件文件路径
    :param mon_path (str): 监控目录
    :param expected_signature (Tuple): 期望处理的文件签名
    """
    file_path = Path(event_path)
    storage_chain = StorageChain()
    try:
        if not file_path.exists():
            return
        # 全程加锁
        with directory_upload_keyed_lock.acquire(str(file_path.absolute())):
            # 回收站隐藏文件不处理
            if (
                event_path.find("/@Recycle/") != -1
                or event_path.find("/#recycle/") != -1
                or event_path.find("/.") != -1
                or event_path.find("/@eaDir") != -1
            ):
                logger.debug(f"【目录上传】{event_path} 是回收站或隐藏的文件")
                return

            # 蓝光目录不处理
            if configer.directory_upload_skip_bdmv_stream and re_search(
                r"BDMV[/\\]STREAM", event_path, IGNORECASE
            ):
                return

            # 去重：目录补偿扫描与单文件事件可能针对同一文件
            # 签名一致则跳过避免重复处理
            upload_key = _upload_key(file_path, mon_path)
            signature = _file_signature(file_path)
            if expected_signature is not None and signature != expected_signature:
                logger.debug(f"【目录上传】{event_path} 处理前再次变化，重新等待稳定")
                directory_upload_stability_tracker.submit(client, event_path, mon_path)
                return
            if signature is not None and _is_recently_processed(upload_key, signature):
                logger.debug(f"【目录上传】{event_path} 近期已处理，跳过重复事件")
                return

            # 先判断文件是否存在
            file_item = storage_chain.get_file_item(storage="local", path=file_path)
            if not file_item:
                logger.warning(f"【目录上传】{event_path} 未找到对应的文件")
                return

            delete = False
            dest_remote = ""
            dest_local = ""
            dest_strm = ""
            for item in configer.get_config("directory_upload_path") or []:
                if not item:
                    continue
                if mon_path == item.get("src", ""):
                    delete = item.get("delete", False)
                    dest_remote = item.get("dest_remote", "")
                    dest_local = item.get("dest_local", "")
                    dest_strm = item.get("dest_strm", "") or ""
                    break

            upload_extensions = _directory_upload_extensions(
                "directory_upload_uploadext"
            )
            copy_extensions = _directory_upload_extensions("directory_upload_copyext")
            if (
                upload_extensions is None
                or file_path.suffix.lower() in upload_extensions
            ):
                # 处理上传
                if not dest_remote:
                    logger.error(f"【目录上传】{file_path} 未找到对应的上传网盘目录")
                    return

                rel = Path(file_path).relative_to(mon_path)
                if configer.directory_upload_clouddrive2_config.enabled:
                    upload_storage = "CloudDrive储存"
                    target_file_path = (
                        Path(configer.directory_upload_clouddrive2_config.prefix)
                        / dest_remote.strip("/")
                        / rel
                    )
                else:
                    upload_storage = configer.storage_module
                    target_file_path = Path(dest_remote) / rel

                # 网盘目录创建流程
                def __find_dir(_fileitem: FileItem, _name: str) -> Optional[FileItem]:
                    """
                    查找下级目录中匹配名称的目录
                    """
                    for sub_folder in storage_chain.list_files(_fileitem):
                        if sub_folder.type != "dir":
                            continue
                        if sub_folder.name == _name:
                            return sub_folder
                    return None

                target_fileitem = storage_chain.get_file_item(
                    storage=upload_storage, path=target_file_path.parent
                )
                if not target_fileitem:
                    # 逐级查找和创建目录
                    target_fileitem = FileItem(storage=upload_storage, path="/")
                    for part in target_file_path.parent.parts[1:]:
                        dir_file = __find_dir(target_fileitem, part)
                        if dir_file:
                            target_fileitem = dir_file
                        else:
                            dir_file = storage_chain.create_folder(
                                target_fileitem, part
                            )
                            if not dir_file:
                                logger.error(
                                    f"【目录上传】创建目录 {target_fileitem.path}{part} 失败！"
                                )
                                return
                            target_fileitem = dir_file

                # 上传流程
                storage_chain.upload_file(target_fileitem, file_path, file_path.name)
                uploaded_file_item = None
                for attempt in range(3):
                    sleep(5 * (2**attempt))
                    uploaded_file_item = storage_chain.get_file_item(
                        storage=upload_storage, path=target_file_path
                    )
                    if uploaded_file_item:
                        break
                if not uploaded_file_item and upload_storage != "CloudDrive储存":
                    try:
                        fid = get_id_to_path(
                            client,
                            target_file_path.as_posix(),
                            **configer.get_ios_ua_app(app=False),
                        )
                        attr = get_attr(
                            client, fid, **configer.get_ios_ua_app(app=False)
                        )
                        uploaded_file_item = FileItem(
                            storage=upload_storage,
                            fileid=str(attr["id"]),
                            path=target_file_path.as_posix(),
                            type="file",
                            name=attr["name"],
                            basename=Path(attr["name"]).stem,
                            extension=Path(attr["name"]).suffix[1:]
                            if Path(attr["name"]).suffix
                            else None,
                            pickcode=attr["pickcode"],
                            size=attr["size"],
                            modify_time=attr["mtime"],
                        )
                    except Exception:
                        pass
                if uploaded_file_item:
                    logger.info(
                        f"【目录上传】{file_path} 上传到网盘 {target_file_path} 成功 "
                    )
                    if dest_strm:
                        if upload_storage == "CloudDrive储存":
                            setattr(
                                uploaded_file_item,
                                "pickcode",
                                client.to_pickcode(int(uploaded_file_item.fileid)),
                            )
                        MonitorStrmHelper.generate_strm_after_upload(
                            uploaded_file_item=uploaded_file_item,
                            dest_strm=dest_strm,
                            mon_path=mon_path,
                            local_file_path=file_path,
                        )
                else:
                    logger.error(f"【目录上传】{file_path} 上传网盘失败")
                    return

            elif copy_extensions is None or file_path.suffix.lower() in copy_extensions:
                # 处理非上传文件
                if dest_local:
                    target_file_path = Path(dest_local) / Path(file_path).relative_to(
                        mon_path
                    )
                    # 创建本地目录
                    target_file_path.parent.mkdir(parents=True, exist_ok=True)
                    # 复制文件
                    status, msg = SystemUtils.copy(file_path, target_file_path)
                    if status == 0:
                        logger.info(
                            f"【目录上传】{file_path} 复制到 {target_file_path} 成功 "
                        )
                    else:
                        logger.error(f"【目录上传】{file_path} 复制失败: {msg}")
                        return
            else:
                # 未匹配后缀的文件直接跳过
                return

            # 处理源文件是否删除
            if delete:
                logger.info(f"【目录上传】删除源文件：{file_path}")
                file_path.unlink(missing_ok=True)
                for file_dir in file_path.parents:
                    if len(str(file_dir)) <= len(str(Path(mon_path))):
                        break
                    files = SystemUtils.list_files(file_dir)
                    if not files:
                        logger.warning(f"【目录上传】删除空目录：{file_dir}")
                        rmtree(file_dir, ignore_errors=True)

            # 处理成功后记录签名，供后续重复事件去重
            if signature is not None:
                _mark_processed(upload_key, signature)

    except Exception as e:
        logger.error(f"【目录上传】目录监控发生错误：{str(e)} - {format_exc()}")
        return
