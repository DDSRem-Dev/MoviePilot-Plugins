"""
``app.sdk.cache`` 替身。

真实宿主从 ``app.runtime.cache`` 与 ``app.adapters.cache.backends`` 重新导出。
替身实现插件实际用到的 4 个符号，且**行为对齐宿主签名**（而不是返回 Mock），
这样测试断言的语义才有意义：

* ``LRUCache(region, maxsize)``  -> ``get/set/delete/clear/items``
* ``TTLCache(maxsize, ttl, region)`` -> ``get/set``
* ``AsyncCache(maxsize)``        -> 异步 ``set/get/items/clear/close/transact``
* ``cached(region, ttl, skip_none)`` -> 进程内记忆化装饰器
"""

import asyncio
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

__all__ = [
    "AsyncCache",
    "LRUCache",
    "TTLCache",
    "cached",
]

_MISSING = object()


def _normalize_key(key: Any) -> Any:
    """把关键字参数形式 ``key=...`` 与位置参数统一成同一个键。"""
    return key


class _BaseCache:
    """共享字典语义的缓存基类。"""

    def __init__(self, region: Optional[str] = None, maxsize: int = 128) -> None:
        self.region = region
        self.maxsize = maxsize
        self._store: "OrderedDict[Any, Any]" = OrderedDict()

    # -- 命名参数友好：宿主大量使用 ``key=`` / ``value=`` 形式 --
    @staticmethod
    def _key_of(key: Any = None, **_kwargs) -> Any:
        return key

    def _evict(self) -> None:
        while self.maxsize and len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def get(self, key: Any = None, default: Any = None, **_kwargs) -> Any:
        resolved = self._key_of(key, **_kwargs)
        value = self._store.get(resolved, _MISSING)
        if value is _MISSING or value is default:
            return default
        self._store.move_to_end(resolved)
        return value

    def set(self, key: Any = None, value: Any = None, **_kwargs) -> None:
        resolved = self._key_of(key, **_kwargs)
        self._store[resolved] = value
        self._store.move_to_end(resolved)
        self._evict()

    def delete(self, key: Any = None, **_kwargs) -> None:
        self._store.pop(self._key_of(key, **_kwargs), None)

    def clear(self, **_kwargs) -> None:
        self._store.clear()

    def items(self, **_kwargs):
        # 宿主调用方普遍写 ``list(self.xxx.items())``，
        # 这里返回与 dict 一致的可迭代视图
        return list(self._store.items())

    def keys(self, **_kwargs):
        return list(self._store.keys())

    def close(self, **_kwargs) -> None:
        self._store.clear()

    def __contains__(self, key: Any) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)


class LRUCache(_BaseCache):
    """容量受限的最近最少使用缓存。"""

    def __init__(self, region: Optional[str] = None, maxsize: int = 128, **kwargs):
        super().__init__(region=region, maxsize=int(maxsize))


class TTLCache(_BaseCache):
    """带过期时间的容量受限缓存。"""

    def __init__(
        self,
        maxsize: int = 128,
        ttl: int = 60,
        region: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(region=region, maxsize=int(maxsize))
        self.ttl = ttl

    def set(self, key: Any = None, value: Any = None, **_kwargs) -> None:
        resolved = self._key_of(key, **_kwargs)
        self._store[resolved] = (time.time() + self.ttl, value)
        self._store.move_to_end(resolved)
        self._evict()

    def get(self, key: Any = None, default: Any = None, **_kwargs) -> Any:
        resolved = self._key_of(key, **_kwargs)
        entry = self._store.get(resolved, _MISSING)
        if entry is _MISSING:
            return default
        expire_at, value = entry
        if expire_at < time.time():
            self._store.pop(resolved, None)
            return default
        self._store.move_to_end(resolved)
        return value

    def items(self, **_kwargs):
        now = time.time()
        return [
            (key, value)
            for key, (expire_at, value) in list(self._store.items())
            if expire_at >= now
        ]


class _Transact:
    """``AsyncCache.transact()`` 的上下文管理器（替身内不加锁）。"""

    def __enter__(self) -> "_Transact":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    async def __aenter__(self) -> "_Transact":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


class AsyncCache:
    """异步缓存替身，方法与宿主一致（``set/get/items/clear/close/transact``）。

    ``set`` 等写入方法既可按同步也可按 ``await`` 调用：返回一个「可等待的
    ``None``」，两种写法都能跑通，避免测试因忘写 ``await`` 而误判。
    """

    def __init__(self, maxsize: int = 128, **kwargs) -> None:
        self.maxsize = maxsize
        self._backing = LRUCache(maxsize=maxsize)

    class _AwaitableNone:
        """既像 ``None`` 又可以 ``await`` 的返回值。"""

        def __await__(self):
            async def _noop():
                return None

            return _noop().__await__()

        def __bool__(self) -> bool:
            return False

    async def set(self, key: Any = None, value: Any = None, ttl: Optional[int] = None,
                  region: Optional[str] = None, **kwargs) -> None:
        self._backing.set(key=key, value=value)

    async def get(self, key: Any = None, default: Any = None,
                  region: Optional[str] = None, **kwargs) -> Any:
        return self._backing.get(key=key, default=default)

    async def items(self, region: Optional[str] = None, **kwargs):
        """异步迭代缓存条目，产出 ``(key, value)``。"""
        for key, value in self._backing.items():
            await asyncio.sleep(0)
            yield key, value

    async def clear(self, region: Optional[str] = None, **kwargs) -> None:
        self._backing.clear()

    async def close(self, **kwargs) -> None:
        self._backing.clear()

    def transact(self, **_kwargs) -> _Transact:
        return _Transact()

    def __contains__(self, key: Any) -> bool:
        return key in self._backing

    def __getitem__(self, key: Any) -> Any:
        value = self._backing.get(key=key, default=_MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: Any, value: Any) -> None:
        self._backing.set(key=key, value=value)

    def __delitem__(self, key: Any) -> None:
        self._backing.delete(key=key)


def cached(
    region: Optional[str] = None,
    ttl: Optional[int] = 3600,
    skip_none: bool = False,
    **kwargs,
) -> Callable:
    """记忆化装饰器替身：按 ``region`` + 参数在进程内缓存结果。"""

    def decorator(func: Callable) -> Callable:
        store: Dict[Tuple, Any] = {}

        @wraps(func)
        def wrapper(*args, **call_kwargs):
            key = (region or func.__qualname__, args[1:], tuple(sorted(call_kwargs.items())))
            if key in store:
                expire_at, value = store[key]
                if expire_at is None or expire_at >= time.time():
                    return value
                store.pop(key, None)
            value = func(*args, **call_kwargs)
            if skip_none and value is None:
                return None
            store[key] = (None if ttl is None else time.time() + ttl, value)
            return value

        # 供测试清缓存用
        wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator
