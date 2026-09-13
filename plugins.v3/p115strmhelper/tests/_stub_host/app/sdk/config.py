"""
``app.sdk.config`` 替身。

``settings`` 用宽松对象实现：任何未显式声明的属性访问都返回一个哨兵字符串，
避免插件因缺少某个配置项而在导入期炸掉。测试若需要精确行为，可自行覆盖。
"""

from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

__all__ = ["settings", "global_vars", "Settings"]


class _Sentinel(str):
    """未配置项的占位值：字符串语义，便于直接参与 f-string 拼接。"""

    def __bool__(self) -> bool:
        return False


_UNSET = _Sentinel("")


class Settings:
    """宿主配置替身。"""

    # ---- 路径类（给真实可写目录，避免测试写文件时炸）----
    CONFIG_PATH: Path = Path(gettempdir()) / "v3-stub-config"
    ROOT_PATH: Path = Path(gettempdir()) / "v3-stub-root"
    PLUGIN_DATA_PATH: Path = Path(gettempdir()) / "v3-stub-plugin-data"

    # ---- 网络 / 域名 ----
    API_TOKEN: str = "stub-token"
    MP_DOMAIN: str = "http://localhost:3001"
    PORT: int = 3001
    PROXY: Any = None
    USER_AGENT: str = "MoviePilot/v3-stub"

    # ---- 缓存后端 ----
    CACHE_BACKEND_TYPE: str = "memory"

    # ---- 数据库 ----
    DB_ECHO: bool = False
    DB_POOL_TYPE: str = "QueuePool"
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_TIMEOUT: int = 30
    DB_TIMEOUT: int = 30

    # ---- 媒体整理 ----
    RENAME_FORMAT: str = "{title} ({year})"
    MOVIE_RENAME_FORMAT: str = "{title} ({year})"
    TV_RENAME_FORMAT: str = "{title} ({year})/Season {season}"
    DOWNLOAD_TMPEXT: str = ".!qb"
    RMT_MEDIAEXT: list = [".mp4", ".mkv", ".ts", ".iso", ".avi", ".mov", ".m2ts"]
    RMT_SUBEXT: list = [".srt", ".ass", ".ssa", ".sub"]
    RMT_AUDIOEXT: list = [".mka", ".flac", ".aac", ".ac3"]
    DEFAULT_SUB: str = "zh"
    SCRAP_FOLLOW_TMDB: bool = True
    SEARCH_SOURCE: str = "themoviedb"
    TZ: str = "Asia/Shanghai"

    # ---- AI ----
    AI_AGENT_ENABLE: bool = False
    AI_AGENT_RETRY_TRANSFER: bool = False

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def __getattr__(self, name: str) -> Any:
        # 未显式声明的配置项统一返回哨兵，保证插件导入不中断
        if name.startswith("__"):
            raise AttributeError(name)
        return _UNSET

    def model_dump(self, **_kwargs) -> Dict[str, Any]:
        return {
            k: v for k, v in self.__dict__.items() if not k.startswith("_")
        }

    def dict(self, **_kwargs) -> Dict[str, Any]:
        return self.model_dump()


settings = Settings()

#: 宿主运行时全局变量容器（V3 中用于存放运行期注入的对象）
global_vars: Dict[str, Any] = {}
