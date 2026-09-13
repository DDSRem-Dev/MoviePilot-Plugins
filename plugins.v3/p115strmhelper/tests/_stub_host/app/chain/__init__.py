"""
``app.chain`` 包替身。

真实宿主的 ``app.chain.__init__`` 是空的（只留 docstring），旧包根符号由
Compat 层惰性解析。替身提供 ``ChainBase`` 以便插件沿用
``from app.chain import ChainBase`` 的写法。
"""

from .base import ChainBase

__all__ = ["ChainBase"]
