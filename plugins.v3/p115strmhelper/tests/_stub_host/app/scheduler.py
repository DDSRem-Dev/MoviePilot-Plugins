"""
``app.scheduler`` 替身。

真实宿主的 ``Scheduler`` 是应用层兼容门面，``__new__`` 返回组合根注册的
调度器实例。插件同时使用了门面的私有成员（``_lock`` / ``_jobs`` /
``_scheduler`` / ``triggers``）与公开方法（``remove_plugin_job`` /
``add_job``），替身因此把两者都提供出来，且保证是**同一个对象**。
"""

import threading
from typing import Any, Dict, List, Optional

__all__ = ["Scheduler"]


class _InnerScheduler:
    """被门面包裹的底层调度器替身（模拟 APScheduler 的接口面）。"""

    def __init__(self) -> None:
        self.running: bool = True
        self.jobs: List[Any] = []

    def add_job(self, func: Any, trigger: Any = None, **kwargs: Any) -> Any:
        """登记任务。替身只记录。"""
        job = {"func": func, "trigger": trigger, "kwargs": kwargs}
        self.jobs.append(job)
        return job

    def remove_job(self, job_id: str) -> None:
        """移除任务。"""
        self.jobs = [j for j in self.jobs if j.get("id") != job_id]

    def start(self, *args: Any, **kwargs: Any) -> None:
        self.running = True

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        self.running = False


class Scheduler:
    """应用层调度器门面替身（进程内单例）。"""

    _instance: Optional["Scheduler"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "Scheduler":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._init_state()
            cls._instance = instance
        return cls._instance

    def _init_state(self) -> None:
        """初始化调度器状态。"""
        self._scheduler = _InnerScheduler()
        #: 插件/Agent 登记的任务表：job_id -> 任务描述
        self._jobs: Dict[str, Any] = {}
        #: 与宿主一致的模块级保护锁
        self._lock = threading.RLock()
        self.triggers: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------
    def remove_plugin_job(self, plugin_id: str, job_id: Optional[str] = None) -> None:
        """移除插件（或指定）的定时任务。"""
        with self._lock:
            if job_id:
                self._jobs.pop(job_id, None)
                return
            for key in [k for k in self._jobs if str(k).startswith(str(plugin_id))]:
                self._jobs.pop(key, None)

    def add_job(self, *args: Any, **kwargs: Any) -> Any:
        return self._scheduler.add_job(*args, **kwargs)

    def start(self, *args: Any, **kwargs: Any) -> Any:
        """立即运行指定任务。"""
        return None

    def list(self) -> List[Any]:
        """列出全部任务。"""
        return list(self._jobs.values())

    def update_plugin_job(self, plugin_id: str) -> None:
        """更新插件定时任务。"""

    def schedule_retry(self, *args: Any, **kwargs: Any) -> Any:
        """登记一次重试任务（宿主重试调度入口替身）。"""
        return None

    def start_agent_task(self, task_id: int) -> bool:
        return False


def _reset() -> None:
    """测试辅助：清除单例。"""
    Scheduler._instance = None
