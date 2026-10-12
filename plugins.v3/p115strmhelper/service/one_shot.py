from types import MethodType
from typing import Any, Callable, Dict, Optional

from app.sdk.logging import logger
from app.sdk.scheduler import add_plugin_once_job

from ..core.config import configer


def schedule_plugin_one_shot(
    service_id: str,
    name: str,
    func: Callable,
    func_kwargs: Optional[Dict[str, Any]] = None,
    delay_sec: int = 3,
    pid: Optional[str] = None,
) -> bool:
    """
    通过宿主调度接口追加当前插件实例的一次性任务

    :param service_id (str): 插件内唯一任务 ID
    :param name (str): 任务显示名称
    :param func (Callable): 执行函数
    :param func_kwargs (Dict): 执行函数的关键字参数
    :param delay_sec (int): 延迟秒数
    :param pid (str): 插件实例 ID，默认使用当前实例

    :return bool: 调度器接受任务时返回 True
    """
    def execute(_plugin: Any, **kwargs: Any) -> Any:
        """
        将服务回调关联至宿主插件实例，供宿主重建服务时核对归属
        """
        return func(**kwargs)

    try:
        accepted = add_plugin_once_job(
            plugin_id=pid or configer.plugin_id,
            job_id=service_id,
            func=MethodType(execute, configer.plugin_instance),
            name=name,
            delay_seconds=delay_sec,
            func_kwargs=func_kwargs,
        )
        if not accepted:
            logger.error(f"【调度】主调度器未接受一次性任务: {name}")
        return accepted
    except Exception as e:
        logger.error(f"【调度】注册一次性任务失败: {name}, {e}", exc_info=True)
        return False
