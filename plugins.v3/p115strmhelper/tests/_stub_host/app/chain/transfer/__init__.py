"""``app.chain.transfer`` 包替身（惰性稳定入口，与宿主一致）。"""

from importlib import import_module
from typing import Any

__all__ = ["TransferChain", "task_lock"]

_EXPORTS = {
    "TransferChain": ("app.chain.transfer.facade", "TransferChain"),
    "task_lock": ("app.chain.transfer.queue", "task_lock"),
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
