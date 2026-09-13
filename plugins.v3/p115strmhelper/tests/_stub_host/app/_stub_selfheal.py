"""
MoviePilot V3 宿主桩（stub）自愈层。

**问题**：仓库既有测试习惯用 ``ModuleType("app")`` / ``_make_pkg("app.schemas")``
手工伪造宿主包并注册进 ``sys.modules``。``sys.modules`` 是全局的，而
``unittest discover`` 在**同一进程**内顺序执行全部测试，于是：

1. 前序测试把 ``sys.modules["app"]`` 换成 ``__path__ = []`` 的空壳；
2. 或者把 ``app.schemas.types`` 登记成裸模块（没有 ``__path__``）。

此后任何测试再 ``import app.sdk.utilities`` 都会失败——报错形如
``No module named 'app.sdk.utilities'; 'app.sdk' is not a package``，
即使 ``PYTHONPATH`` 已指向桩。

**方案**：导入 ``app`` 时安装 ``sys.meta_path`` 钩子，在解析 ``app`` 与
``app.*`` 之前做一次「体检 + 修复」：

* ``app`` 本身被换成空壳 → 把桩目录补回 ``__path__``；
* 桩里真实存在的**包**（有 ``__init__.py``）被顶替成裸模块 → 重新加载真实包。

手工伪造的**叶子模块**（如 ``app.schemas.types`` 被塞入 ``MessageType``）会被
保留，因为修复只针对「桩里是包、当前却不是包」的冲突情形，最小侵入。
"""

import os
import sys
from importlib.abc import MetaPathFinder
from importlib.util import module_from_spec, spec_from_file_location
from typing import Any, Optional, Sequence, Set

__all__ = [
    "STUB_APP_DIR",
    "ensure_app_package",
    "ensure_stub_packages",
    "install_self_heal",
    "StubSelfHealFinder",
]

#: 桩内 ``app`` 包所在目录
STUB_APP_DIR = os.path.dirname(os.path.abspath(__file__))

#: 桩内所有「包」的完整模块名（由磁盘扫描得出，缓存一次）
_PACKAGE_NAMES: Optional[Set[str]] = None


def _scan_stub_packages() -> Set[str]:
    """扫描桩目录，返回所有真实包（含 ``__init__.py``）的模块名。"""
    global _PACKAGE_NAMES
    if _PACKAGE_NAMES is not None:
        return _PACKAGE_NAMES

    packages: Set[str] = set()
    for current_dir, dirnames, filenames in os.walk(STUB_APP_DIR):
        # 跳过字节码缓存
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        if "__init__.py" not in filenames:
            continue
        relative = os.path.relpath(current_dir, os.path.dirname(STUB_APP_DIR))
        module_name = relative.replace(os.sep, ".")
        packages.add(module_name)
    _PACKAGE_NAMES = packages
    return packages


def _build_package(module_name: str) -> Optional[Any]:
    """按模块名从桩目录重新加载一个包。"""
    relative = module_name.replace(".", os.sep)
    init_path = os.path.join(STUB_APP_DIR, relative, "__init__.py")
    if not os.path.isfile(init_path):
        return None
    spec = spec_from_file_location(
        module_name,
        init_path,
        submodule_search_locations=[os.path.dirname(init_path)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - 极端情况
        return None
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_app_package() -> bool:
    """确保 ``sys.modules['app']`` 是可解析子模块的桩包。

    :return: 执行了修复返回 ``True``；本就健康返回 ``False``
    """
    current = sys.modules.get("app")
    path = getattr(current, "__path__", None) if current is not None else None

    # 健康判断：__path__ 必须是非字符串的可迭代，且包含桩目录
    healthy = False
    if path is not None and not isinstance(path, str):
        try:
            healthy = STUB_APP_DIR in list(path)
        except TypeError:
            healthy = False
    if healthy:
        return False

    # 就地补齐包属性，保留测试可能挂在同一 module 对象上的自定义属性
    if current is not None:
        try:
            current.__path__ = [STUB_APP_DIR]
            current.__file__ = os.path.join(STUB_APP_DIR, "__init__.py")
            setattr(current, "IS_STUB", True)
            return True
        except Exception:  # noqa: BLE001 - 补齐失败则整体重建
            pass

    return _build_package("app") is not None


def ensure_stub_packages() -> bool:
    """修复被顶替成裸模块的**桩内包**。

    例：``app.schemas.types`` 在桩里是包，却被测试伪造成裸模块，导致后续
    ``import app.schemas.types.X`` 语义错乱。

    :return: 只要有任意一个包被修复就返回 ``True``
    """
    repaired = False
    for module_name in sorted(_scan_stub_packages()):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        path = getattr(module, "__path__", None)
        # 桩内是包，而当前对象没有可用的 __path__ → 说明被顶替了
        if path is None or isinstance(path, str):
            if _build_package(module_name) is not None:
                repaired = True
    return repaired


class StubSelfHealFinder(MetaPathFinder):
    """在解析 ``app`` / ``app.*`` 之前修复被测试污染的模块状态。"""

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]] = None,
        target: Any = None,
    ):
        """执行自愈后返回 ``None``，把解析交还正常导入链。"""
        if fullname == "app":
            ensure_app_package()
        elif fullname.startswith("app."):
            ensure_app_package()
            # 仅当本次要解析的模块是桩内包时才做全量体检，控制开销
            if fullname in _scan_stub_packages():
                ensure_stub_packages()
        return None


def install_self_heal() -> None:
    """安装自愈钩子（幂等）。"""
    if not any(isinstance(f, StubSelfHealFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, StubSelfHealFinder())
    ensure_app_package()
