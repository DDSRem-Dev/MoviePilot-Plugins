from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from apscheduler.triggers.date import DateTrigger
from pytz import timezone

from app.core.config import settings
from app.log import logger
from app.scheduler import Scheduler


def schedule_plugin_one_shot(
    service_id: str,
    name: str,
    func: Callable,
    func_kwargs: Optional[Dict[str, Any]] = None,
    delay_sec: int = 3,
    pid: str = "P115StrmHelper",
    provider_name: str = "115网盘STRM助手",
) -> bool:
    """
    向 MoviePilot 主调度器注册一次性延迟任务

    :param service_id (str): 插件内唯一服务 ID（与 pid 组合为 job_id）
    :param name (str): 任务显示名称
    :param func (Callable): 执行函数
    :param func_kwargs (Dict): 传入 func 的关键字参数
    :param delay_sec (int): 延迟秒数
    :param pid (str): 插件 ID
    :param provider_name (str): 任务提供方名称

    :return bool: 注册成功返回 True
    """
    scheduler = Scheduler()
    if not scheduler._scheduler or not scheduler._scheduler.running:
        logger.error(f"【调度】主调度器未运行，无法注册一次性任务: {name}")
        return False

    job_id = f"{pid}_{service_id}"
    scheduler.remove_plugin_job(pid, job_id)

    run_date = datetime.now(tz=timezone(settings.TZ)) + timedelta(seconds=delay_sec)

    try:
        with scheduler._lock:
            scheduler._jobs[job_id] = {
                "func": func,
                "name": name,
                "pid": pid,
                "provider_name": provider_name,
                "kwargs": func_kwargs or {},
                "running": False,
            }
            scheduler._scheduler.add_job(
                scheduler.start,
                DateTrigger(run_date=run_date),
                id=job_id,
                name=name,
                kwargs={"job_id": job_id},
                replace_existing=True,
            )
        logger.info(f"【调度】已注册一次性任务: {name}，将于 {delay_sec}s 后执行")
        return True
    except Exception as e:
        with scheduler._lock:
            scheduler._jobs.pop(job_id, None)
        logger.error(f"【调度】注册一次性任务失败: {name}, {e}", exc_info=True)
        return False
