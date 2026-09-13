"""
``app.sdk.media`` 替身。

真实宿主这里从 ``app.domain.meta.*`` / ``app.domain.metainfo`` 重新导出。
替身实现一个「够用的」媒体识别对象：``MetaInfo`` / ``MetaInfoPath`` /
``MetaVideo`` 共享同一套属性（``MetaBase`` 子集），并提供一个朴素的
文件名解析器，让 ``MetaInfoPath(Path("Show.S01E01.mkv"))`` 能给出
``season`` / ``episode``，而不用引入宿主的完整识别逻辑。
"""

import re
from pathlib import Path
from typing import Any, List, Optional, Union

__all__ = [
    "MediaInfo",
    "MetaBase",
    "MetaInfo",
    "MetaInfoPath",
    "MetaVideo",
]

#: ``S01E02`` / ``S01`` / ``E02`` 形式的季集识别
_SEASON_EPISODE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])S(\d{1,4})(?:[^A-Za-z0-9]*)E(\d{1,4})", re.IGNORECASE
)
_SEASON_ONLY_RE = re.compile(r"(?:^|[^A-Za-z0-9])S(\d{1,4})(?:[^0-9]|$)", re.IGNORECASE)
_EPISODE_ONLY_RE = re.compile(r"(?:^|[^A-Za-z0-9])E(?:P)?(\d{1,4})(?:[^0-9]|$)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?:^|[^0-9])((?:19|20)\d{2})(?:[^0-9]|$)")


class MetaBase:
    """媒体识别结果基类（宿主 ``app.domain.meta.metabase.MetaBase`` 子集）。"""

    def __init__(
        self,
        title: Optional[str] = None,
        year: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.title = title
        self.year = year
        self.type: Any = kwargs.pop("type", None)
        self.season = season
        self.episode = episode
        self.begin_season = kwargs.pop("begin_season", season)
        self.end_season = kwargs.pop("end_season", season)
        self.begin_episode = kwargs.pop("begin_episode", episode)
        self.end_episode = kwargs.pop("end_episode", episode)
        self.total_season = kwargs.pop("total_season", 1 if season else None)
        self.total_episode = kwargs.pop("total_episode", None)
        self.season_episode = kwargs.pop("season_episode", None)
        self.season_seq = kwargs.pop("season_seq", None)
        self.part = kwargs.pop("part", None)
        self.episode_list: List[int] = kwargs.pop("episode_list", [])
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(title={self.title!r}, year={self.year!r}, "
            f"season={self.season!r}, episode={self.episode!r})"
        )


def _parse_from_text(text: str) -> dict:
    """从文件/目录名中提取季、集、年份等朴素元数据。"""
    parsed: dict = {}
    match = _SEASON_EPISODE_RE.search(text)
    if match:
        parsed["season"] = int(match.group(1))
        parsed["episode"] = int(match.group(2))
    else:
        match = _SEASON_ONLY_RE.search(text)
        if match:
            parsed["season"] = int(match.group(1))
        match = _EPISODE_ONLY_RE.search(text)
        if match:
            parsed["episode"] = int(match.group(1))
    year_match = _YEAR_RE.search(text)
    if year_match:
        parsed["year"] = year_match.group(1)
    return parsed


class MetaInfo(MetaBase):
    """按标题构造的识别结果。"""

    def __init__(self, title: Optional[str] = None, **kwargs: Any) -> None:
        parsed = _parse_from_text(title or "")
        parsed.update(kwargs)
        super().__init__(title=title, **parsed)


class MetaInfoPath(MetaBase):
    """按路径构造的识别结果。"""

    def __init__(self, path: Union[str, Path], **kwargs: Any) -> None:
        self.path = Path(path)
        text = self.path.name
        # 无扩展名时用文件名本体，避免 ``.mkv`` 干扰
        parsed = _parse_from_text(text)
        parsed.update(kwargs)
        super().__init__(title=text, **parsed)

    def __repr__(self) -> str:
        return f"MetaInfoPath(path={str(self.path)!r})"


class MetaVideo(MetaBase):
    """视频识别结果。"""

    def __init__(
        self,
        title: Optional[str] = None,
        isfile: bool = True,
        **kwargs: Any,
    ) -> None:
        self.isfile = isfile
        parsed = _parse_from_text(title or "")
        parsed.update(kwargs)
        super().__init__(title=title, **parsed)


class MediaInfo:
    """媒体信息替身（宿主 ``app.domain.context.MediaInfo`` 子集）。"""

    def __init__(
        self,
        title: Optional[str] = None,
        year: Optional[str] = None,
        type: Any = None,
        tmdb_id: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.title = title
        self.year = year
        self.type = type
        self.tmdb_id = tmdb_id
        self.season = kwargs.pop("season", None)
        self.media_id = kwargs.pop("media_id", None)
        self.media_source = kwargs.pop("media_source", None)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self) -> str:
        return f"MediaInfo(title={self.title!r}, year={self.year!r})"
