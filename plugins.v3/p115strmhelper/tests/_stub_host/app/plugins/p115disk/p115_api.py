"""
``app.plugins.p115disk.p115_api`` 替身。

插件在 ``core/p115disk.py`` 里用 ``try/except ImportError`` 探测该模块，成功时
构造 ``P115Api(client=..., disk_name="115网盘Plus")`` 并访问一批公开与私有成员。
替身提供完整成员面，使「P115Disk 插件已安装」这条分支在测试中可被覆盖。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["P115Api"]


class P115Api:
    """115 网盘 Plus 插件 API 替身。"""

    def __init__(self, client: Any = None, disk_name: str = "115网盘Plus", **kwargs: Any) -> None:
        self.client = client
        self.disk_name = disk_name
        self._id_cache: Dict[str, Any] = {}
        self._id_item_cache: Dict[str, Any] = {}
        self._oss_token: Optional[dict] = None

    # ------------------------------------------------------------------
    # 插件实际调用的（私有）成员
    # ------------------------------------------------------------------
    def _calc_sha(self, *args: Any, **kwargs: Any) -> Optional[str]:
        """计算文件 SHA1。替身返回 ``None``，让调用方走降级。"""
        return None

    def _get_oss_token(self, *args: Any, **kwargs: Any) -> Optional[dict]:
        """获取 OSS 上传令牌。替身返回 ``None``。"""
        return None

    def _is_token_expiring(self, *args: Any, **kwargs: Any) -> bool:
        """判断令牌是否临近过期。"""
        return True

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def list(self, *args: Any, **kwargs: Any) -> Optional[List[Any]]:
        return []

    def get_item(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def get_folder(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None

    def get_parent(self, *args: Any, **kwargs: Any) -> Optional[Any]:
        return None
