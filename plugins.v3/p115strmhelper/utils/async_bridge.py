__all__ = ["run_coroutine_sync"]

from asyncio import get_running_loop, new_event_loop, run as asyncio_run, set_event_loop
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def _run_in_new_loop(coro: Coroutine[Any, Any, T]) -> T:
    """
    在独立事件循环中执行协程

    :param coro (Coroutine): 待执行的协程对象

    :return T: 协程返回值
    """
    loop = new_event_loop()
    try:
        set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        set_event_loop(None)
        loop.close()


def run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    """
    在同步上下文中执行协程并返回结果

    宿主部分查询接口只提供异步实现，而插件侧调用点位于同步函数内。当前线程没有
    运行中的事件循环时直接使用 ``asyncio.run``；若调用方本身处于事件循环内，则改用
    独立线程携带全新事件循环执行，避免 ``asyncio.run`` 抛出
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``

    :param coro (Coroutine): 待执行的协程对象

    :return T: 协程返回值
    """
    try:
        get_running_loop()
    except RuntimeError:
        return asyncio_run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_new_loop, coro)
        return future.result()
