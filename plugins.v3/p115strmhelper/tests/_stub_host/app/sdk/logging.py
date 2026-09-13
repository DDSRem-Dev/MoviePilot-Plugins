"""``app.sdk.logging`` 替身：插件最常用的日志入口。"""

import logging

__all__ = ["logger"]

logger = logging.getLogger("v3-stub")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.CRITICAL)
