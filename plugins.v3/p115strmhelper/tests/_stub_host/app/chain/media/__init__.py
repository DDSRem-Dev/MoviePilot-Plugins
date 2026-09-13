"""
``app.chain.media`` 包替身。

真实宿主是惰性导出包：``MediaChain`` 实际定义在 ``app.chain.media.facade``。
替身同样把实现放在 ``facade`` 里，包根做惰性转发，以复刻宿主的导入语义。
"""

from importlib import import_module
from typing import Any

__all__ = ["MediaChain"]

_EXPORTS = {
    "MediaChain": ("app.chain.media.facade", "MediaChain"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, symbol_name = target
    value = getattr(import_module(module_name), symbol_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
