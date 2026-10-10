from datetime import datetime
from pathlib import Path
from tarfile import open as tarfile_open
from threading import Event as ThreadEvent, Thread
from time import perf_counter, sleep
from typing import Deque, List, Optional, Tuple
from collections import deque

from httpx import Client as HttpxClient
from p115client import P115Client, check_response

from app.chain.storage import StorageChain
from app.log import logger

from ...core.config import configer
from ...schemas.backup import BackupHistory, BackupTargetType, StrmBackupItem
from ...utils.string import StringUtils

from .constants import BackupPhaseWeight, BackupProgress


class _BackupProgressTracker:
    """
    备份各阶段整体进度追踪与自适应日志节流
    """

    def __init__(
        self,
        phase_weight_start: float,
        phase_weight_end: float,
        *,
        total_bytes: int = 0,
        total_files: int = 0,
    ) -> None:
        self.phase_weight_start = phase_weight_start
        self.phase_weight_end = phase_weight_end
        self.total_bytes = total_bytes
        self.total_files = total_files
        self._phase_start_time = 0.0
        self._last_log_time = 0.0
        self._last_log_sub_ratio = -1.0
        self._last_log_bytes = 0
        self._upload_log_interval = BackupProgress.UPLOAD_MIN_INTERVAL_SEC
        self._speed_samples: Deque[Tuple[float, int]] = deque(
            maxlen=BackupProgress.TARGET_LOG_LINES + 4,
        )

    def begin_phase(self, now: float) -> None:
        """
        标记阶段开始时间

        :param now (float): perf_counter 时间戳
        """
        self._phase_start_time = now
        self._last_log_time = 0.0
        self._last_log_sub_ratio = -1.0
        self._last_log_bytes = 0
        self._speed_samples.clear()
        self._record_speed_sample(now, 0)

    def overall_ratio(self, sub_ratio: float) -> float:
        """
        将阶段内子进度映射为整体 0–1 比例

        :param sub_ratio (float): 阶段内完成比例

        :return float: 整体进度比例
        """
        sub_ratio = max(0.0, min(1.0, sub_ratio))
        span = self.phase_weight_end - self.phase_weight_start
        return self.phase_weight_start + span * sub_ratio

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _record_speed_sample(self, now: float, processed_bytes: int) -> None:
        """
        记录速度采样点并裁剪超出时间窗口的历史样本

        仅在输出进度日志时调用，避免高频文件循环导致 deque 膨胀

        :param now (float): perf_counter 时间戳
        :param processed_bytes (int): 已处理字节数
        """
        self._speed_samples.append((now, processed_bytes))
        window_start = now - BackupProgress.SPEED_WINDOW_SEC
        while len(self._speed_samples) > 2 and self._speed_samples[0][0] < window_start:
            self._speed_samples.popleft()

    def _compute_speed_bps(self, now: float, processed_bytes: int) -> float:
        """
        根据已有采样点计算当前阶段的处理速度（B/s）

        预热期内使用累计均值，之后使用最近 SPEED_WINDOW_SEC 的滑动窗口均值；
        不修改采样队列，可安全用于高频节流判断

        :param now (float): perf_counter 时间戳
        :param processed_bytes (int): 已处理字节数

        :return float: 速度（B/s），无法计算返回 0
        """
        elapsed = now - self._phase_start_time
        if elapsed <= 0:
            return 0.0

        if elapsed < BackupProgress.SPEED_WARMUP_SEC:
            return processed_bytes / elapsed

        if not self._speed_samples:
            return processed_bytes / elapsed

        oldest_t, oldest_b = self._speed_samples[0]
        dt = now - oldest_t
        db = processed_bytes - oldest_b
        if dt <= 0 or db <= 0:
            return processed_bytes / elapsed
        return db / dt

    def should_log_scan(self, now: float, force: bool = False) -> bool:
        """
        扫描阶段是否应输出进度日志（仅时间步进）

        :param now (float): 当前时间戳
        :param force (bool): 是否强制输出

        :return bool: 是否应输出
        """
        if force or self._last_log_time == 0.0:
            return True
        return (now - self._last_log_time) >= BackupProgress.SCAN_MIN_LOG_INTERVAL_SEC

    def should_log_pack(
        self,
        now: float,
        processed_bytes: int,
        sub_ratio: float,
        force: bool = False,
    ) -> bool:
        """
        打包阶段是否应输出进度日志

        :param now (float): 当前时间戳
        :param processed_bytes (int): 已处理字节数
        :param sub_ratio (float): 阶段内完成比例
        :param force (bool): 是否强制输出

        :return bool: 是否应输出
        """
        if force or self._last_log_time == 0.0:
            return True

        sub_pct_step = max(
            BackupProgress.MIN_PCT_STEP / 100.0,
            1.0 / BackupProgress.TARGET_LOG_LINES,
        )
        if sub_ratio - self._last_log_sub_ratio >= sub_pct_step:
            return True

        if self.total_bytes > 0:
            byte_step = max(
                BackupProgress.MIN_BYTE_STEP,
                self.total_bytes // BackupProgress.TARGET_LOG_LINES,
            )
            if processed_bytes - self._last_log_bytes >= byte_step:
                return True

        speed_bps = self._compute_speed_bps(now, processed_bytes)
        if speed_bps > 0 and self.total_bytes > 0:
            remaining_bytes = max(0, self.total_bytes - processed_bytes)
            eta_remaining = remaining_bytes / speed_bps
            time_step = self._clamp(
                eta_remaining / BackupProgress.TARGET_LOG_LINES,
                BackupProgress.MIN_LOG_INTERVAL_SEC,
                BackupProgress.MAX_LOG_INTERVAL_SEC,
            )
        else:
            time_step = BackupProgress.MIN_LOG_INTERVAL_SEC

        return (now - self._last_log_time) >= time_step

    def should_log_upload(self, now: float, force: bool = False) -> bool:
        """
        上传阶段是否应输出进度日志（仅时间步进）

        :param now (float): 当前时间戳
        :param force (bool): 是否强制输出

        :return bool: 是否应输出
        """
        if force or self._last_log_time == 0.0:
            return True
        return (now - self._last_log_time) >= self._upload_log_interval

    def set_upload_log_interval(self, estimated_upload_sec: float) -> None:
        """
        设置上传阶段日志间隔

        :param estimated_upload_sec (float): 预估上传秒数
        """
        self._upload_log_interval = self._clamp(
            estimated_upload_sec / 20.0,
            BackupProgress.UPLOAD_MIN_INTERVAL_SEC,
            BackupProgress.UPLOAD_MAX_INTERVAL_SEC,
        )

    @property
    def upload_log_interval(self) -> float:
        """
        上传阶段日志输出间隔（秒）
        """
        return self._upload_log_interval

    def mark_logged(
        self,
        now: float,
        sub_ratio: float,
        processed_bytes: int = 0,
    ) -> None:
        """
        记录最近一次进度日志状态

        :param now (float): 当前时间戳
        :param sub_ratio (float): 阶段内完成比例
        :param processed_bytes (int): 已处理字节数
        """
        self._last_log_time = now
        self._last_log_sub_ratio = sub_ratio
        self._last_log_bytes = processed_bytes
        self._record_speed_sample(now, processed_bytes)


class BackupStrmHelper:
    """
    STRM 备份核心逻辑
    """

    def __init__(self):
        self._storage_chain = StorageChain()

    @property
    def _storage_name(self) -> str:
        """
        获取当前存储模块名称
        """
        return configer.storage_module

    @staticmethod
    def _format_log_progress_bar(ratio: float, width: int = 20) -> str:
        """
        将 0–1 比例格式化为日志用 ASCII 进度条

        :param ratio (float): 完成比例
        :param width (int): 进度条宽度（字符数）

        :return str: 形如 ``[████████░░░░] 42.5%`` 的字符串
        """
        ratio = max(0.0, min(1.0, ratio))
        filled = int(ratio * width)
        if filled >= width:
            bar = "=" * width
        elif ratio > 0:
            bar = "=" * filled + ">" + " " * (width - filled - 1)
        else:
            bar = " " * width
        return f"[{bar}] {ratio * 100:.1f}%"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """
        将秒数格式化为简短耗时

        :param seconds (float): 秒数

        :return str: 如 ``34m`` 或 ``1h 12m``
        """
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        remain_m = minutes % 60
        if remain_m:
            return f"{hours}h {remain_m}m"
        return f"{hours}h"

    @staticmethod
    def _log_backup_progress(
        stage: str, overall_ratio: float, detail: str = ""
    ) -> None:
        """
        输出带整体进度条的备份日志

        :param stage (str): 阶段名称
        :param overall_ratio (float): 整体进度 0–1
        :param detail (str): 附加详情
        """
        bar = BackupStrmHelper._format_log_progress_bar(overall_ratio)
        if detail:
            logger.info(f"【STRM备份】{stage} {bar} {detail}")
        else:
            logger.info(f"【STRM备份】{stage} {bar}")

    @staticmethod
    def _safe_task_name(task_name: str) -> str:
        """
        将备份任务名称转为文件名安全前缀

        :param task_name (str): 备份任务名称

        :return str: 安全前缀
        """
        return task_name.replace("/", "_").replace("\\", "_").replace(" ", "_")

    @staticmethod
    def _generate_filename(task_name: str) -> str:
        """
        生成备份文件名

        :param task_name (str): 备份任务名称

        :return str: 备份文件名
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = BackupStrmHelper._safe_task_name(task_name)
        return f"{safe_name}_{timestamp}.tar.gz"

    @classmethod
    def _collect_backup_entries(
        cls,
        source_paths: List[str],
    ) -> Tuple[List[Tuple[Path, str, int]], float]:
        """
        扫描源目录并收集待打包文件

        :param source_paths (List): 要打包的源目录列表

        :return Tuple: (条目列表, 扫描耗时秒数)
        """
        valid_sources: List[Path] = []
        for source_path in source_paths:
            source = Path(source_path)
            if not source.exists():
                logger.warning(f"【STRM备份】源目录不存在，跳过: {source_path}")
                continue
            if not source.is_dir():
                logger.warning(f"【STRM备份】源路径不是目录，跳过: {source_path}")
                continue
            valid_sources.append(source)

        if not valid_sources:
            return [], 0.0

        scan_t0 = perf_counter()
        tracker = _BackupProgressTracker(
            BackupPhaseWeight.SCAN_START,
            BackupPhaseWeight.SCAN_END,
        )
        tracker.begin_phase(scan_t0)

        entries: List[Tuple[Path, str, int]] = []
        total_discovered_files = 0
        total_discovered_bytes = 0
        source_count = len(valid_sources)

        for source_idx, source in enumerate(valid_sources):
            arc_root = source.name
            cls._log_backup_progress(
                "扫描",
                tracker.overall_ratio(source_idx / source_count),
                f"目录 {source_idx + 1}/{source_count} 开始 {source}",
            )
            tracker.mark_logged(perf_counter(), source_idx / source_count)

            for path in source.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                rel = path.relative_to(source)
                arcname = str(Path(arc_root) / rel)
                entries.append((path, arcname, size))
                total_discovered_files += 1
                total_discovered_bytes += size

                now = perf_counter()
                mid_sub_ratio = (source_idx + 0.5) / source_count
                if tracker.should_log_scan(now):
                    cls._log_backup_progress(
                        "扫描",
                        tracker.overall_ratio(mid_sub_ratio),
                        f"目录 {source_idx + 1}/{source_count} "
                        f"已发现 {total_discovered_files} 文件 "
                        f"{StringUtils.format_size(total_discovered_bytes)}",
                    )
                    tracker.mark_logged(now, mid_sub_ratio)

            done_now = perf_counter()
            done_sub_ratio = (source_idx + 1) / source_count
            cls._log_backup_progress(
                "扫描",
                tracker.overall_ratio(done_sub_ratio),
                f"目录 {source_idx + 1}/{source_count} 完成 "
                f"已发现 {total_discovered_files} 文件 "
                f"{StringUtils.format_size(total_discovered_bytes)}",
            )
            tracker.mark_logged(done_now, done_sub_ratio)

        scan_elapsed = perf_counter() - scan_t0
        summary = (
            f"共 {total_discovered_files} 个文件，"
            f"合计 {StringUtils.format_size(total_discovered_bytes)}"
        )
        if scan_elapsed >= 3.0:
            summary += f"，耗时 {scan_elapsed:.1f}s"
        cls._log_backup_progress(
            "扫描",
            tracker.overall_ratio(1.0),
            summary,
        )
        return entries, scan_elapsed

    @classmethod
    def _create_tar_gz(
        cls,
        source_paths: List[str],
        output_path: Path,
        pack_phase_end: float = BackupPhaseWeight.PACK_END_LOCAL,
    ) -> Tuple[bool, Optional[str]]:
        """
        将多个源目录打包为 tar.gz 文件

        :param source_paths (List): 要打包的源目录列表
        :param output_path (Path): 输出文件路径
        :param pack_phase_end (float): 打包阶段整体进度终点

        :return Tuple: (是否成功, 错误信息)
        """
        try:
            entries, _scan_elapsed = cls._collect_backup_entries(source_paths)
            total_files = len(entries)
            total_bytes = sum(size for _, _, size in entries)

            output_path.parent.mkdir(parents=True, exist_ok=True)

            if total_files == 0:
                with tarfile_open(output_path, "w:gz"):
                    pass
                cls._log_backup_progress(
                    "打包", BackupPhaseWeight.PACK_START, "无文件可打包"
                )
                cls._log_backup_progress("打包", pack_phase_end, "完成")
                return True, None

            tracker = _BackupProgressTracker(
                BackupPhaseWeight.PACK_START,
                pack_phase_end,
                total_bytes=total_bytes,
                total_files=total_files,
            )
            pack_t0 = perf_counter()
            tracker.begin_phase(pack_t0)

            processed_files = 0
            processed_bytes = 0

            with tarfile_open(output_path, "w:gz") as tar:
                for file_path, arcname, size in entries:
                    tar.add(file_path, arcname=arcname)
                    processed_files += 1
                    processed_bytes += size
                    now = perf_counter()
                    sub_ratio = (
                        processed_bytes / total_bytes if total_bytes > 0 else 1.0
                    )
                    force = processed_files == 1 or processed_files == total_files
                    if tracker.should_log_pack(
                        now, processed_bytes, sub_ratio, force=force
                    ):
                        speed_bps = (
                            processed_bytes / (now - pack_t0) if now > pack_t0 else 0.0
                        )
                        detail_parts = [
                            f"{StringUtils.format_size(processed_bytes)}/"
                            f"{StringUtils.format_size(total_bytes)}",
                            f"({processed_files}/{total_files})",
                        ]
                        if speed_bps > 0:
                            detail_parts.append(
                                f"速度 {StringUtils.format_size(int(speed_bps))}/s"
                            )
                            remaining = total_bytes - processed_bytes
                            if remaining > 0:
                                eta = remaining / speed_bps
                                detail_parts.append(
                                    f"剩余约 {cls._format_duration(eta)}"
                                )
                        cls._log_backup_progress(
                            "打包",
                            tracker.overall_ratio(sub_ratio),
                            " ".join(detail_parts),
                        )
                        tracker.mark_logged(now, sub_ratio, processed_bytes)

            pack_elapsed = perf_counter() - pack_t0

            cls._log_backup_progress(
                "打包",
                pack_phase_end,
                f"{StringUtils.format_size(total_bytes)}/{StringUtils.format_size(total_bytes)} "
                f"({total_files}/{total_files}) "
                f"耗时 {cls._format_duration(pack_elapsed)}",
            )
            return True, None
        except Exception as e:
            error_msg = f"创建 tar.gz 失败: {str(e)}"
            logger.error(f"【STRM备份】{error_msg}", exc_info=True)
            return False, error_msg

    @staticmethod
    def _extract_tar_gz(
        archive_path: Path,
        target_dir: Path,
    ) -> Tuple[bool, Optional[str]]:
        """
        解压 tar.gz 文件到目标目录

        :param archive_path (Path): 备份文件路径
        :param target_dir (Path): 解压目标目录

        :return Tuple: (是否成功, 错误信息)
        """
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with tarfile_open(archive_path, "r:gz") as tar:
                tar.extractall(path=target_dir, filter="data")
            return True, None
        except Exception as e:
            error_msg = f"解压 tar.gz 失败: {str(e)}"
            logger.error(f"【STRM备份】{error_msg}", exc_info=True)
            return False, error_msg

    @staticmethod
    def _clean_old_backups(
        backup_dir: Path,
        task_name: str,
        retain_count: int,
    ) -> int:
        """
        清理旧的备份文件，保留最新的 N 个

        :param backup_dir (Path): 备份目录
        :param task_name (str): 备份任务名称
        :param retain_count (int): 保留数量

        :return int: 删除的文件数量
        """
        safe_name = BackupStrmHelper._safe_task_name(task_name)
        prefix = f"{safe_name}_"
        backup_files = sorted(
            [
                f
                for f in backup_dir.iterdir()
                if f.name.startswith(prefix) and f.name.endswith(".tar.gz")
            ],
            key=lambda f: f.name,
            reverse=True,
        )
        deleted_count = 0
        for old_file in backup_files[retain_count:]:
            try:
                old_file.unlink()
                deleted_count += 1
                logger.info(f"【STRM备份】已删除旧备份: {old_file.name}")
            except Exception as e:
                logger.error(f"【STRM备份】删除旧备份失败: {old_file.name}, {str(e)}")
        return deleted_count

    def _log_clean_progress(self, detail: str, overall_ratio: float) -> None:
        """
        输出清理阶段进度

        :param detail (str): 详情
        :param overall_ratio (float): 整体进度
        """
        self._log_backup_progress("清理旧备份", overall_ratio, detail)

    def _log_complete(self) -> None:
        """
        输出备份完成日志
        """
        self._log_backup_progress("完成", 1.0)

    def backup_to_local(
        self,
        task: StrmBackupItem,
    ) -> BackupHistory:
        """
        执行本地备份

        :param task (StrmBackupItem): 备份任务配置

        :return BackupHistory: 备份历史记录
        """
        filename = self._generate_filename(task.name)
        target_dir = Path(task.local_target_path)
        output_path = target_dir / filename

        success, error_msg = self._create_tar_gz(
            source_paths=task.source_paths,
            output_path=output_path,
            pack_phase_end=BackupPhaseWeight.PACK_END_LOCAL,
        )

        file_size = (
            output_path.stat().st_size if success and output_path.exists() else 0
        )

        if success:
            self._log_clean_progress("开始", BackupPhaseWeight.CLEAN_START)
            self._clean_old_backups(
                backup_dir=target_dir,
                task_name=task.name,
                retain_count=task.retain_count,
            )
            self._log_clean_progress("完成", BackupPhaseWeight.CLEAN_END)
            self._log_complete()

        return BackupHistory(
            task_name=task.name,
            filename=filename,
            target_type=BackupTargetType.LOCAL,
            target_path=str(output_path),
            file_size=file_size,
            source_paths=task.source_paths,
            status="success" if success else "error",
            error_msg=error_msg,
        )

    def _upload_with_progress(
        self,
        client: P115Client,
        temp_file: Path,
        pid: int,
        filename: str,
        archive_size: int,
    ) -> None:
        """
        上传备份文件并输出进度心跳

        :param client (P115Client): P115Client 实例
        :param temp_file (Path): 本地临时文件
        :param pid (int): 115 目录 ID
        :param filename (str): 上传文件名
        :param archive_size (int): 归档大小

        :raises Exception: 上传失败时抛出
        """
        estimated_upload_sec = archive_size / BackupProgress.DEFAULT_UPLOAD_BPS

        tracker = _BackupProgressTracker(
            BackupPhaseWeight.UPLOAD_START,
            BackupPhaseWeight.UPLOAD_END,
        )
        tracker.set_upload_log_interval(estimated_upload_sec)
        upload_t0 = perf_counter()
        tracker.begin_phase(upload_t0)
        upload_done = ThreadEvent()
        log_interval = tracker.upload_log_interval

        self._log_backup_progress(
            "上传",
            BackupPhaseWeight.UPLOAD_START,
            f"开始 ({StringUtils.format_size(archive_size)})",
        )
        tracker.mark_logged(upload_t0, 0.0)

        def _heartbeat() -> None:
            while not upload_done.wait(log_interval):
                now = perf_counter()
                elapsed = now - upload_t0
                sub_ratio = min(0.99, elapsed / estimated_upload_sec)
                if tracker.should_log_upload(now):
                    self._log_backup_progress(
                        "上传",
                        tracker.overall_ratio(sub_ratio),
                        f"已等待 {self._format_duration(elapsed)} / "
                        f"预估 {self._format_duration(estimated_upload_sec)} "
                        f"({StringUtils.format_size(archive_size)})",
                    )
                    tracker.mark_logged(now, sub_ratio)

        heartbeat_thread = Thread(target=_heartbeat, daemon=True)
        heartbeat_thread.start()

        try:
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    resp = client.upload_file(temp_file, pid=pid, filename=filename)
                    check_response(resp)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"【STRM备份】上传失败，第 {attempt + 1}/{max_retries} 次重试: {e}"
                    )
                    if attempt < max_retries - 1:
                        sleep(2 * (attempt + 1))
            if last_error:
                raise last_error
            upload_elapsed = perf_counter() - upload_t0
            self._log_backup_progress(
                "上传",
                BackupPhaseWeight.UPLOAD_END,
                f"完成 耗时 {self._format_duration(upload_elapsed)}",
            )
        finally:
            upload_done.set()
            heartbeat_thread.join(timeout=2.0)

    def backup_to_cloud(
        self,
        task: StrmBackupItem,
        client: P115Client,
    ) -> BackupHistory:
        """
        执行 115 网盘备份

        :param task (StrmBackupItem): 备份任务配置
        :param client (P115Client): P115Client 实例

        :return BackupHistory: 备份历史记录
        """
        filename = self._generate_filename(task.name)
        temp_dir = configer.PLUGIN_TEMP_PATH / "backup"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / filename

        success, error_msg = self._create_tar_gz(
            source_paths=task.source_paths,
            output_path=temp_file,
            pack_phase_end=BackupPhaseWeight.PACK_END_CLOUD,
        )

        if not success:
            return BackupHistory(
                task_name=task.name,
                filename=filename,
                target_type=BackupTargetType.CLOUD_115,
                target_path=f"{task.cloud_target_path}/{filename}",
                file_size=0,
                source_paths=task.source_paths,
                status="error",
                error_msg=error_msg,
            )

        file_size = temp_file.stat().st_size
        cloud_path = f"{task.cloud_target_path}/{filename}"

        try:
            target_dir_item = self._storage_chain.get_file_item(
                storage=self._storage_name, path=Path(task.cloud_target_path)
            )
            if not target_dir_item:
                raise Exception(f"115 网盘目标目录不存在: {task.cloud_target_path}")

            pid = target_dir_item.fileid

            self._upload_with_progress(
                client=client,
                temp_file=temp_file,
                pid=pid,
                filename=filename,
                archive_size=file_size,
            )

            logger.info(f"【STRM备份】上传到 115 网盘成功: {cloud_path}")
            temp_file.unlink(missing_ok=True)

            self._log_clean_progress("开始", BackupPhaseWeight.CLEAN_START)
            self._clean_old_cloud_backups(
                task_name=task.name,
                cloud_path=task.cloud_target_path,
                retain_count=task.retain_count,
            )
            self._log_clean_progress("完成", BackupPhaseWeight.CLEAN_END)
            self._log_complete()

            return BackupHistory(
                task_name=task.name,
                filename=filename,
                target_type=BackupTargetType.CLOUD_115,
                target_path=cloud_path,
                file_size=file_size,
                source_paths=task.source_paths,
                status="success",
            )
        except Exception as e:
            error_msg = f"上传到 115 网盘失败: {str(e)}"
            logger.error(f"【STRM备份】{error_msg}", exc_info=True)
            temp_file.unlink(missing_ok=True)
            return BackupHistory(
                task_name=task.name,
                filename=filename,
                target_type=BackupTargetType.CLOUD_115,
                target_path=cloud_path,
                file_size=file_size,
                source_paths=task.source_paths,
                status="error",
                error_msg=error_msg,
            )

    def _clean_old_cloud_backups(
        self,
        task_name: str,
        cloud_path: str,
        retain_count: int,
    ):
        """
        清理 115 网盘上旧的备份文件

        :param task_name (str): 备份任务名称
        :param cloud_path (str): 115 网盘备份目录
        :param retain_count (int): 保留数量
        """
        try:
            dir_item = self._storage_chain.get_file_item(
                storage=self._storage_name, path=Path(cloud_path)
            )
            if not dir_item:
                return

            files = self._storage_chain.list_files(dir_item) or []
            safe_name = BackupStrmHelper._safe_task_name(task_name)
            prefix = f"{safe_name}_"
            backup_files = sorted(
                [
                    f
                    for f in files
                    if f.name.startswith(prefix) and f.name.endswith(".tar.gz")
                ],
                key=lambda f: f.name,
                reverse=True,
            )

            for old_file in backup_files[retain_count:]:
                try:
                    self._storage_chain.delete_file(old_file)
                    logger.info(f"【STRM备份】已删除云端旧备份: {old_file.name}")
                except Exception as e:
                    logger.error(
                        f"【STRM备份】删除云端旧备份失败: {old_file.name}, {str(e)}"
                    )
        except Exception as e:
            logger.error(f"【STRM备份】清理云端旧备份失败: {str(e)}", exc_info=True)

    def list_local_backups(self, task: StrmBackupItem) -> List[BackupHistory]:
        """
        列出本地备份文件

        :param task (StrmBackupItem): 备份任务配置

        :return List: 备份历史记录列表
        """
        if not task.local_target_path:
            return []

        backup_dir = Path(task.local_target_path)
        if not backup_dir.exists():
            return []

        safe_name = BackupStrmHelper._safe_task_name(task.name)
        prefix = f"{safe_name}_"
        results = []

        for f in sorted(backup_dir.iterdir(), key=lambda x: x.name, reverse=True):
            if f.name.startswith(prefix) and f.name.endswith(".tar.gz"):
                results.append(
                    BackupHistory(
                        task_name=task.name,
                        filename=f.name,
                        target_type=BackupTargetType.LOCAL,
                        target_path=str(f),
                        file_size=f.stat().st_size,
                        source_paths=task.source_paths,
                    )
                )

        return results

    def list_cloud_backups(
        self,
        task: StrmBackupItem,
    ) -> List[BackupHistory]:
        """
        列出 115 网盘备份文件

        :param task (StrmBackupItem): 备份任务配置

        :return List: 备份历史记录列表
        """
        if not task.cloud_target_path:
            return []

        try:
            dir_item = self._storage_chain.get_file_item(
                storage=self._storage_name, path=Path(task.cloud_target_path)
            )
            if not dir_item:
                return []

            files = self._storage_chain.list_files(dir_item) or []
            safe_name = BackupStrmHelper._safe_task_name(task.name)
            prefix = f"{safe_name}_"
            results = []

            for f in files:
                if f.name.startswith(prefix) and f.name.endswith(".tar.gz"):
                    results.append(
                        BackupHistory(
                            task_name=task.name,
                            filename=f.name,
                            target_type=BackupTargetType.CLOUD_115,
                            target_path=f"{task.cloud_target_path}/{f.name}",
                            file_size=f.size,
                            source_paths=task.source_paths,
                        )
                    )

            return sorted(results, key=lambda x: x.filename, reverse=True)
        except Exception as e:
            logger.error(f"【STRM备份】列出 115 网盘备份失败: {str(e)}", exc_info=True)
            return []

    @staticmethod
    def restore_from_local(
        backup_path: str,
        source_paths: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        从本地备份恢复

        :param backup_path (str): 备份文件路径
        :param source_paths (List): 恢复目标目录列表（取第一个的父目录作为解压根目录）

        :return Tuple: (是否成功, 错误信息)
        """
        archive_path = Path(backup_path)
        if not archive_path.exists():
            return False, f"备份文件不存在: {backup_path}"

        if not source_paths:
            return False, "未指定恢复目标目录"

        target_dir = Path(source_paths[0]).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        return BackupStrmHelper._extract_tar_gz(archive_path, target_dir)

    def restore_from_cloud(
        self,
        cloud_path: str,
        source_paths: List[str],
        client: Optional[P115Client],
    ) -> Tuple[bool, Optional[str]]:
        """
        从 115 网盘备份恢复

        :param cloud_path (str): 115 网盘备份文件路径
        :param source_paths (List): 恢复目标目录列表（取第一个作为恢复根目录）
        :param client (P115Client): P115Client 实例

        :return Tuple: (是否成功, 错误信息)
        """
        if not source_paths:
            return False, "未指定恢复目标目录"

        if not client:
            return False, "115 客户端未初始化"

        try:
            target_file = Path(cloud_path)
            parent_path = target_file.parent
            filename = target_file.name

            parent_dir = self._storage_chain.get_file_item(
                storage=self._storage_name, path=parent_path
            )
            if not parent_dir:
                return False, f"115 网盘父目录不存在: {parent_path}"

            files = self._storage_chain.list_files(parent_dir) or []
            file_item = None
            for f in files:
                if f.name == filename and f.type == "file":
                    file_item = f
                    break

            if not file_item:
                return False, f"115 网盘备份文件不存在: {cloud_path}"

            pickcode = getattr(file_item, "pickcode", None)
            if not pickcode:
                return False, f"无法获取文件 pickcode: {cloud_path}"

            temp_dir = configer.PLUGIN_TEMP_PATH / "restore"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / filename

            download_url = client.download_url(
                pickcode, user_agent=configer.get_user_agent()
            )
            headers = {"User-Agent": configer.get_user_agent()}
            with HttpxClient(headers=headers, follow_redirects=True) as hc:
                with hc.stream("GET", str(download_url)) as resp:
                    resp.raise_for_status()
                    with open(temp_file, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8 * 1024 * 1024):
                            f.write(chunk)
            logger.info(f"【STRM备份】从 115 网盘下载备份文件成功: {cloud_path}")

            target_dir = Path(source_paths[0]).parent
            target_dir.mkdir(parents=True, exist_ok=True)
            success, error_msg = self._extract_tar_gz(temp_file, target_dir)
            temp_file.unlink(missing_ok=True)
            return success, error_msg
        except Exception as e:
            error_msg = f"从 115 网盘恢复失败: {str(e)}"
            logger.error(f"【STRM备份】{error_msg}", exc_info=True)
            return False, error_msg

    def execute_backup(
        self,
        task: StrmBackupItem,
        client: Optional[P115Client] = None,
    ) -> BackupHistory:
        """
        执行备份任务

        :param task (StrmBackupItem): 备份任务配置
        :param client (P115Client): P115Client 实例

        :return BackupHistory: 备份历史记录
        """
        if not task.enabled:
            return BackupHistory(
                task_name=task.name,
                filename="",
                target_type=task.target_type,
                target_path="",
                source_paths=task.source_paths,
                status="skipped",
                error_msg="备份任务未启用",
            )

        if not task.source_paths:
            return BackupHistory(
                task_name=task.name,
                filename="",
                target_type=task.target_type,
                target_path="",
                source_paths=[],
                status="error",
                error_msg="未配置源目录",
            )

        if task.target_type == BackupTargetType.LOCAL:
            if not task.local_target_path:
                return BackupHistory(
                    task_name=task.name,
                    filename="",
                    target_type=task.target_type,
                    target_path="",
                    source_paths=task.source_paths,
                    status="error",
                    error_msg="未配置本地备份目录",
                )
            return self.backup_to_local(task)
        elif task.target_type == BackupTargetType.CLOUD_115:
            if not task.cloud_target_path:
                return BackupHistory(
                    task_name=task.name,
                    filename="",
                    target_type=task.target_type,
                    target_path="",
                    source_paths=task.source_paths,
                    status="error",
                    error_msg="未配置 115 网盘备份目录",
                )
            if not client:
                return BackupHistory(
                    task_name=task.name,
                    filename="",
                    target_type=task.target_type,
                    target_path="",
                    source_paths=task.source_paths,
                    status="error",
                    error_msg="115 客户端未初始化",
                )
            return self.backup_to_cloud(task, client)
        else:
            return BackupHistory(
                task_name=task.name,
                filename="",
                target_type=task.target_type,
                target_path="",
                source_paths=task.source_paths,
                status="error",
                error_msg=f"不支持的备份目标类型: {task.target_type}",
            )


backup_helper = BackupStrmHelper()
