from asyncio import run as asyncio_run
from typing import Any, Dict, List, Union

from app.chain.media import MediaChain
from app.core.config import settings
from app.log import logger


class MediaSearcher:
    """
    媒体搜索器
    """

    @staticmethod
    def _get_source(obj: Union[Dict[str, Any], Any]) -> Any:
        """
        与 media 端点 ``__get_source`` 一致
        """
        if isinstance(obj, dict):
            return obj.get("source")
        return getattr(obj, "source", None)

    @classmethod
    async def _async_search_media_sorted(cls, title: str) -> List[Dict[str, Any]]:
        """
        异步搜索媒体并排序（全量，未切片）
        """
        media_chain = MediaChain()
        _, medias = await media_chain.async_search(title=title)
        if not medias:
            return []
        result = [media.to_dict() for media in medias]
        setting_order = (
            settings.SEARCH_SOURCE.split(",") if settings.SEARCH_SOURCE else []
        )
        sort_order = {source: index for index, source in enumerate(setting_order)}
        return sorted(result, key=lambda x: sort_order.get(cls._get_source(x), 4))

    @classmethod
    def search_like_api(cls, title: str, count: int) -> List[Dict[str, Any]]:
        """
        同步入口：与主程序媒体搜索 API 一致，返回前 ``count`` 条

        :param title (str): 搜索关键词（与端点 ``title`` 一致）
        :param count (int): 最大条数，对应端点 ``count``；应 >= 1
        :return List: 媒体 ``to_dict()`` 列表
        """
        if not title or not str(title).strip():
            return []
        safe_count = max(1, min(int(count), 500))

        async def _run() -> List[Dict[str, Any]]:
            sorted_result = await cls._async_search_media_sorted(title.strip())
            return sorted_result[:safe_count]

        try:
            return asyncio_run(_run())
        except Exception as e:
            logger.error(f"【/sh】媒体搜索失败: {title!r}, error={e}", exc_info=True)
            raise
