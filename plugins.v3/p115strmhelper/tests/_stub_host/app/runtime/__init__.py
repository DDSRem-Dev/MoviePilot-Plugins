"""V3 宿主桩：``app.runtime`` 包。

真实 MoviePilot V3 在该包下放置运行期能力（events / cache / settings / version 等）。
本桩仅提供被插件源码或兜底逻辑引用到的部分，其余按需惰性补齐。
"""

from __future__ import annotations

from .version import get_app_version

__all__ = ["get_app_version"]
