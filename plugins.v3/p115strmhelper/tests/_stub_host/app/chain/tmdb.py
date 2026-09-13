"""``app.chain.tmdb`` 替身。"""

from typing import Any, List, Optional

from .base import ChainBase

__all__ = ["TmdbChain"]


class TmdbChain(ChainBase):
    """TheMovieDB 处理链替身。"""

    def tmdb_discover(self, *args: Any, **kwargs: Any) -> Optional[List[Any]]:
        return []

    def tmdb_search(self, *args: Any, **kwargs: Any) -> Optional[List[Any]]:
        return []

    def tmdb_detail(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None
