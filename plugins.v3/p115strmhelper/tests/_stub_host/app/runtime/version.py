"""V3 宿主桩：运行期版本读取入口。

真实宿主 ``app/runtime/version.py`` 从构建期生成的顶层 ``version`` 模块读取
``APP_VERSION`` / ``FRONTEND_VERSION``。桩环境没有该模块，因此给出稳定的占位值。
"""

from __future__ import annotations

try:
    # 构建期生成的顶层 version 模块（宿主根目录）
    from version import APP_VERSION as _APP_VERSION
except ImportError:  # pragma: no cover - 桩环境常态
    _APP_VERSION = "v3-stub"

try:
    from version import FRONTEND_VERSION as _FRONTEND_VERSION
except ImportError:  # pragma: no cover - 桩环境常态
    _FRONTEND_VERSION = "v3-stub"


def get_app_version() -> str:
    """返回当前后端构建的发布版本。"""
    return str(_APP_VERSION)


def get_frontend_version(*, fallback_to_declared: bool = True) -> str:
    """返回前端资源版本；桩环境直接回退到声明值。"""
    return str(_FRONTEND_VERSION)
