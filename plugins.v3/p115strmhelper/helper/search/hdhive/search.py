from typing import Any, Dict, List, Optional

from app.log import logger
from app.schemas.types import MediaType

from ....core.config import configer
from ...hdhive.browser import HDHiveError, get_hdhive_browser_client
from .display import strip_hdhive_title_points_prefix


def _media_type_to_hdhive(value: Any) -> Optional[str]:
    """
    将交互 resource_dict 的 type 转为 HDHive 浏览器搜索用的 movie / tv
    """
    if value is None:
        return None
    if isinstance(value, MediaType):
        if value == MediaType.MOVIE:
            return "movie"
        if value == MediaType.TV:
            return "tv"
        return None
    s = str(value).strip()
    if s in (MediaType.MOVIE.value, "电影"):
        return "movie"
    if s in (MediaType.TV.value, "电视剧"):
        return "tv"
    low = s.lower()
    if low == "movie":
        return "movie"
    if low == "tv":
        return "tv"
    return None


def fetch_resources_impl(
    resource_dict: Dict[str, Any], source_tag: str
) -> List[Dict[str, Any]]:
    """
    通过浏览器自动化拉取 HDHive 115网盘资源列表，映射为与 TG 合并兼容的字典列表
    """
    if not configer.hdhive_search_enabled:
        return []

    mt = _media_type_to_hdhive(resource_dict.get("type"))
    tmdb_id = resource_dict.get("tmdb_id")
    if not mt or tmdb_id is None:
        logger.debug("【HDHive】跳过：无有效 media_type 或 tmdb_id: %s", resource_dict)
        return []

    client = get_hdhive_browser_client()
    if client is None:
        logger.debug("【HDHive】浏览器客户端未就绪（无持久化 Cookie 且未配置账号密码）")
        return []

    try:
        items = client.get_resources(mt, tmdb_id)
    except HDHiveError as e:
        logger.warning("【HDHive】get_resources 失败: %s", e)
        return []
    except Exception as e:
        logger.warning("【HDHive】get_resources 异常: %s", e, exc_info=True)
        return []

    out: List[Dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        href = (row.get("href") or "").strip()
        slug = href.rsplit("/", 1)[-1] if href else ""
        if not slug:
            continue
        title = (
            strip_hdhive_title_points_prefix((row.get("title") or "").strip())
            or "未命名"
        )
        is_official = "官组" in (row.get("tags") or [])
        raw: Dict[str, Any] = {
            "unlock_points": row.get("unlock_points"),
            "share_size": row.get("size", ""),
            "video_resolution": [row["resolution"]] if row.get("resolution") else [],
            "source": [],
            "subtitle_language": [],
            "subtitle_type": [],
            "is_official": is_official,
            "user": row.get("user", ""),
            "posted_at": row.get("posted_at", ""),
            "pw_tags": row.get("tags", []),
            "href": href,
        }
        out.append(
            {
                "shareurl": "",
                "taskname": title,
                "content": "",
                "tags": [],
                "channel_id": "",
                "channel_name": "HDHive",
                "source": source_tag,
                "hdhive_slug": slug,
                "hdhive_media_url": "",
                "hdhive_raw": raw,
            }
        )
    return out
