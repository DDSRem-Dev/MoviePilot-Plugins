"""
``app.adapters.cache.redis`` 替身。

插件用法固定为三步：``helper = RedisHelper(); helper._connect();
client = helper.client``，随后把 ``client`` 当作 ``redis.Redis`` 使用
（``pipeline`` / ``sadd`` / ``rpush`` / ``expire`` / ``sismember`` / ``smembers``）。

替身因此提供：

* ``_connect()`` 成功时把 ``client`` 指向一个可用的内存实现
* 连接失败时把 ``client`` 置为 ``None``（与宿主一致，插件会据此抛
  ``ConnectionError`` 并降级到 txt 后端）——通过 :func:`set_available` 控制
"""

from typing import Any, Dict, List, Optional, Set

__all__ = ["RedisHelper", "set_available"]

#: 替身环境默认「Redis 可用」，客户端走内存实现
_AVAILABLE: bool = True


def set_available(available: bool) -> None:
    """测试辅助：切换 Redis 可用状态，用于覆盖降级分支。"""
    global _AVAILABLE
    _AVAILABLE = bool(available)


class _MemoryPipeline:
    """最小可用的 pipeline 替身（命令立即执行）。"""

    def __init__(self, client: "_MemoryClient") -> None:
        self._client = client

    def __getattr__(self, name: str):
        def _call(*args: Any, **kwargs: Any):
            target = getattr(self._client, name)
            return target(*args, **kwargs)

        return _call

    def execute(self) -> List[Any]:
        return []

    def __enter__(self) -> "_MemoryPipeline":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _MemoryClient:
    """内存版 Redis 客户端替身。"""

    def __init__(self) -> None:
        self._sets: Dict[str, Set[str]] = {}
        self._lists: Dict[str, List[str]] = {}
        self._values: Dict[str, Any] = {}

    # -- pipeline --
    def pipeline(self, *args: Any, **kwargs: Any) -> _MemoryPipeline:
        return _MemoryPipeline(self)

    # -- set --
    def sadd(self, key: str, *values: str) -> int:
        bucket = self._sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(str(v) for v in values)
        return len(bucket) - before

    def sismember(self, key: str, value: str) -> bool:
        return str(value) in self._sets.get(key, set())

    def smembers(self, key: str) -> Set[str]:
        return set(self._sets.get(key, set()))

    def scard(self, key: str) -> int:
        return len(self._sets.get(key, set()))

    # -- list --
    def rpush(self, key: str, *values: str) -> int:
        bucket = self._lists.setdefault(key, [])
        bucket.extend(str(v) for v in values)
        return len(bucket)

    def lrange(self, key: str, start: int = 0, end: int = -1) -> List[str]:
        bucket = self._lists.get(key, [])
        if end == -1:
            return bucket[start:]
        return bucket[start : end + 1]

    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    # -- string --
    def get(self, key: str) -> Optional[Any]:
        return self._values.get(key)

    def set(self, key: str, value: Any, *args: Any, **kwargs: Any) -> bool:
        self._values[key] = value
        return True

    # -- 通用 --
    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            for store in (self._sets, self._lists, self._values):
                if key in store:
                    store.pop(key)
                    removed += 1
        return removed

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def exists(self, key: str) -> int:
        return int(
            key in self._sets or key in self._lists or key in self._values
        )

    def keys(self, pattern: str = "*") -> List[str]:
        all_keys = set(self._sets) | set(self._lists) | set(self._values)
        if pattern in ("*", ""):
            return list(all_keys)
        prefix = pattern.rstrip("*")
        return [key for key in all_keys if key.startswith(prefix)]

    def info(self) -> Dict[str, Any]:
        return {"used_memory": 0, "used_memory_human": "0B"}

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        pass


class RedisHelper:
    """Redis 帮助类替身。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.client: Optional[_MemoryClient] = None

    def _connect(self) -> None:
        """建立连接。替身按 :data:`_AVAILABLE` 决定是否给出客户端。"""
        self.client = _MemoryClient() if _AVAILABLE else None

    def connect(self) -> None:
        self._connect()
