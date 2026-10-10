from threading import Lock, Thread
from time import sleep
from typing import Callable, Optional, Set

from p115client import P115Client

from app.log import logger
from app.scheduler import Scheduler

from ...core.config import configer
from ...helper.backup import BackupStrmHelper, backup_helper
from ...schemas.backup import StrmBackupItem
from ...service.one_shot import schedule_plugin_one_shot
from ...utils.sentry import sentry_manager


@sentry_manager.capture_all_class_exceptions
class BackupService:
    """
    STRM 备份与恢复调度服务
    """

    def __init__(self, client: Optional[P115Client] = None) -> None:
        self.client = client
        self._backup_task_lock = Lock()
        self._backup_running_tasks: Set[str] = set()
        self._reserved_task_started: Set[str] = set()

    def _try_acquire_backup_task(self, task_name: str) -> bool:
        """
        尝试占用备份任务运行槽（备份与恢复共用）

        :param task_name (str): 备份任务名称

        :return bool: 占用成功返回 True，已在运行返回 False
        """
        with self._backup_task_lock:
            if task_name in self._backup_running_tasks:
                return False
            self._backup_running_tasks.add(task_name)
            return True

    def _release_backup_task(self, task_name: str) -> None:
        """
        释放备份任务运行槽

        :param task_name (str): 备份任务名称
        """
        with self._backup_task_lock:
            self._backup_running_tasks.discard(task_name)
            self._reserved_task_started.discard(task_name)

    def _mark_reserved_task_started(self, task_name: str) -> None:
        """
        标记已占位任务已开始执行

        :param task_name (str): 备份任务名称
        """
        with self._backup_task_lock:
            self._reserved_task_started.add(task_name)

    def is_backup_task_running(self, task_name: str) -> bool:
        """
        备份任务是否正在运行

        :param task_name (str): 备份任务名称

        :return bool: 正在运行返回 True
        """
        with self._backup_task_lock:
            return task_name in self._backup_running_tasks

    @staticmethod
    def _find_backup_task(task_name: str) -> Optional[StrmBackupItem]:
        """
        按名称查找备份任务配置

        :param task_name (str): 备份任务名称

        :return StrmBackupItem: 匹配的配置，未找到返回 None
        """
        for item in configer.strm_backup_items:
            if item.name == task_name:
                return item
        return None

    def _execute_backup_impl(self, task_name: str) -> None:
        """
        执行备份任务核心逻辑

        :param task_name (str): 备份任务名称
        """
        if not configer.strm_backup_enabled:
            return

        task = self._find_backup_task(task_name)
        if not task:
            logger.error(f"【STRM备份】备份任务不存在: {task_name}")
            return

        logger.info(f"【STRM备份】开始执行备份任务: {task_name}")
        history = backup_helper.execute_backup(task, client=self.client)

        if history.status == "success":
            logger.info(
                f"【STRM备份】备份成功: {task_name}, "
                f"文件: {history.filename}, 大小: {history.file_size} 字节"
            )
        elif history.status == "skipped":
            logger.info(
                f"【STRM备份】备份任务已跳过: {task_name}, 原因: {history.error_msg}"
            )
        else:
            logger.error(
                f"【STRM备份】备份失败: {task_name}, 错误: {history.error_msg}"
            )

    def run_backup_task(self, task_name: str) -> None:
        """
        执行备份任务

        :param task_name (str): 备份任务名称
        """
        if not configer.strm_backup_enabled:
            return

        if not self._try_acquire_backup_task(task_name):
            logger.info(f"【STRM备份】任务已在运行，跳过: {task_name}")
            return

        try:
            self._execute_backup_impl(task_name)
        finally:
            self._release_backup_task(task_name)

    def _run_backup_task_reserved(self, task_name: str) -> None:
        """
        执行已占位的备份任务

        用于 start_backup_task 注册的一次性调度任务，避免 TOCTOU 下重复调度
        调度前已将 task_name 写入运行槽，因此此处不再二次 acquire

        :param task_name (str): 备份任务名称
        """
        self._mark_reserved_task_started(task_name)
        try:
            self._execute_backup_impl(task_name)
        finally:
            self._release_backup_task(task_name)

    def _watch_orphaned_reserved_slot(
        self,
        task_name: str,
        job_id: str,
        grace_sec: int = 10,
    ) -> None:
        """
        检测调度任务被主调度器清空后释放孤立运行槽

        :param task_name (str): 备份任务名称
        :param job_id (str): 主调度器 job_id
        :param grace_sec (int): 等待任务启动的宽限秒数
        """

        def _watch() -> None:
            sleep(grace_sec)
            with self._backup_task_lock:
                if task_name not in self._backup_running_tasks:
                    return
                if task_name in self._reserved_task_started:
                    return
            scheduler = Scheduler()
            with scheduler._lock:
                jobs = getattr(scheduler, "_jobs", None) or {}
                job_exists = job_id in jobs
            if job_exists:
                return
            self._release_backup_task(task_name)
            logger.warning(
                f"【STRM备份】调度任务未执行且已被移除，已释放运行槽: {task_name}"
            )

        Thread(
            target=_watch,
            name=f"P115StrmHelper-备份槽位守护-{task_name}",
            daemon=True,
        ).start()

    def _schedule_one_shot_or_release(
        self,
        task_name: str,
        service_id: str,
        job_name: str,
        func: Callable,
        func_kwargs: Optional[dict] = None,
    ) -> bool:
        """
        注册一次性任务，失败时释放已占用的运行槽

        :param task_name (str): 备份任务名称（用于释放运行槽）
        :param service_id (str): 插件内服务 ID
        :param job_name (str): 调度任务显示名称
        :param func (Callable): 执行函数
        :param func_kwargs (dict): 传入 func 的关键字参数

        :return bool: 调度注册成功返回 True
        """
        job_id = f"P115StrmHelper_{service_id}"
        if schedule_plugin_one_shot(
            service_id=service_id,
            name=job_name,
            func=func,
            func_kwargs=func_kwargs,
            delay_sec=0,
        ):
            self._watch_orphaned_reserved_slot(task_name, job_id)
            return True
        self._release_backup_task(task_name)
        logger.error(f"【STRM备份】调度失败，已释放运行槽: {task_name}")
        return False

    def start_backup_task(self, task: StrmBackupItem) -> bool:
        """
        启动备份任务（通过主调度器立即执行）

        :param task (StrmBackupItem): 备份任务配置

        :return bool: 调度注册成功返回 True
        """
        if not self._try_acquire_backup_task(task.name):
            logger.info(f"【STRM备份】任务已在运行，跳过调度: {task.name}")
            return False

        safe_name = BackupStrmHelper._safe_task_name(task.name)
        return self._schedule_one_shot_or_release(
            task_name=task.name,
            service_id=f"strm_backup_{safe_name}",
            job_name=f"STRM备份-{task.name}",
            func=self._run_backup_task_reserved,
            func_kwargs={"task_name": task.name},
        )

    def _execute_restore_impl(self, task_name: str, backup_path: str) -> None:
        """
        执行恢复任务核心逻辑

        :param task_name (str): 备份任务名称
        :param backup_path (str): 备份文件路径
        """
        if not configer.strm_backup_enabled:
            return

        task = self._find_backup_task(task_name)
        if not task:
            logger.error(f"【STRM恢复】备份任务不存在: {task_name}")
            return

        logger.info(f"【STRM恢复】开始执行恢复任务: {task_name}, 路径: {backup_path}")

        if task.target_type.value == "local":
            success, error_msg = backup_helper.restore_from_local(
                backup_path=backup_path,
                source_paths=task.source_paths,
            )
        elif task.target_type.value == "cloud":
            success, error_msg = backup_helper.restore_from_cloud(
                cloud_path=backup_path,
                source_paths=task.source_paths,
                client=self.client,
            )
        else:
            success, error_msg = False, f"不支持的备份目标类型: {task.target_type}"

        if success:
            logger.info(f"【STRM恢复】恢复成功: {task_name}")
        else:
            logger.error(f"【STRM恢复】恢复失败: {task_name}, 错误: {error_msg}")

    def run_restore_task(self, task_name: str, backup_path: str) -> None:
        """
        执行恢复任务

        :param task_name (str): 备份任务名称
        :param backup_path (str): 备份文件路径
        """
        if not configer.strm_backup_enabled:
            return

        if not self._try_acquire_backup_task(task_name):
            logger.info(f"【STRM恢复】任务已在运行，跳过: {task_name}")
            return

        try:
            self._execute_restore_impl(task_name, backup_path)
        finally:
            self._release_backup_task(task_name)

    def _run_restore_task_reserved(
        self,
        task_name: str,
        backup_path: str,
    ) -> None:
        """
        执行已占位的恢复任务

        用于 start_restore_task 注册的一次性调度任务，避免 TOCTOU 下重复调度
        调度前已将 task_name 写入运行槽，因此此处不再二次 acquire

        :param task_name (str): 备份任务名称
        :param backup_path (str): 备份文件路径
        """
        self._mark_reserved_task_started(task_name)
        try:
            self._execute_restore_impl(task_name, backup_path)
        finally:
            self._release_backup_task(task_name)

    def start_restore_task(self, task_name: str, backup_path: str) -> bool:
        """
        启动恢复任务（通过主调度器立即执行）

        :param task_name (str): 备份任务名称
        :param backup_path (str): 备份文件路径

        :return bool: 调度注册成功返回 True
        """
        if not self._try_acquire_backup_task(task_name):
            logger.info(f"【STRM恢复】任务已在运行，跳过调度: {task_name}")
            return False

        safe_name = BackupStrmHelper._safe_task_name(task_name)
        return self._schedule_one_shot_or_release(
            task_name=task_name,
            service_id=f"strm_restore_{safe_name}",
            job_name=f"STRM恢复-{task_name}",
            func=self._run_restore_task_reserved,
            func_kwargs={
                "task_name": task_name,
                "backup_path": backup_path,
            },
        )
