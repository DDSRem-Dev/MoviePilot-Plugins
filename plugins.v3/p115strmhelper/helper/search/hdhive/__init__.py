__all__ = ["HDHiveSearch"]

from typing import Any, Dict, List

from .display import format_list_block_impl
from .search import fetch_resources_impl


class HDHiveSearch:
    """
    HDHive 浏览器搜索与 TG 交互资源列表的合并入口
    """

    SOURCE = "hdhive"

    @staticmethod
    def fetch_resources(resource_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        拉取并过滤 pan_type=115，映射为与 TG 合并兼容的字典列表

        :param resource_dict (Dict): 含 type、tmdb_id、name 等
        """
        return fetch_resources_impl(resource_dict, HDHiveSearch.SOURCE)

    @staticmethod
    def format_list_block(data: Dict[str, Any], line_prefix: str) -> str:
        """
        交互资源列表中单条 HDHive 的展示文案（Markdown）

        :param data (Dict): 与 ``fetch_resources`` 输出项一致
        :param line_prefix (str): 如 ``1. `` 或 emoji 序号前缀
        """
        return format_list_block_impl(data, line_prefix)
