__all__ = [
    "ShareLinkResolver",
    "build_share_page_client",
    "extract_cloud_links_from_text",
]


from re import match as re_match
from threading import Lock
from typing import List, Optional, Set, Tuple

from httpx import Client, RequestError

from app.log import logger
from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ...core.config import configer
from ...utils.share_url_patterns import (
    ALIYUN_SHARE_URL_MATCH,
    HTTPS_URL_TOKEN_PATTERN,
    U115_SHARE_URL_MATCH,
    extract_cloud_link_urls_from_text,
    is_direct_u115_or_aliyun_share_url,
    is_telegra_ph_url,
    normalize_share_url_candidate,
)


_share_page_client: Optional[Client] = None
_share_page_client_lock = Lock()


def build_share_page_client() -> Client:
    """
    构建用于拉取分享中间页（如 telegra.ph、TG 公开页）的 httpx 客户端

    与 TgSearcher 使用相同代理与 User-Agent，模块内单例复用连接
    """
    global _share_page_client
    if _share_page_client is not None:
        return _share_page_client
    with _share_page_client_lock:
        if _share_page_client is None:
            proxies = (
                AsyncRequestUtils._convert_proxies_for_httpx(settings.PROXY)
                if settings.PROXY
                else None
            )
            _share_page_client = Client(
                headers={"User-Agent": configer.get_user_agent(utype=1)},
                proxy=proxies,
                follow_redirects=True,
            )
        return _share_page_client


def extract_cloud_links_from_text(text: str) -> Tuple[List[str], str]:
    """
    从任意字符串（含 HTML）中提取 115 与阿里云盘链接

    :param text (str): 网页或纯文本
    :return Tuple: (链接列表, 首个匹配到的云类型 u115/aliyun，可能为空串)
    """
    try:
        return extract_cloud_link_urls_from_text(text)
    except Exception as e:
        logger.warn(f"【ShareLinks】提取云盘链接时出错: {str(e)}")
        return [], ""


def _pick_first_u115_url(links: List[str]) -> Optional[str]:
    """
    在已提取的链接中只取第一条 115 分享 URL

    :param links (List): 原始链接列表
    :return str: 规范化后的第一条 115 URL，否则 None
    """
    normalized = [normalize_share_url_candidate(x) for x in links if x]
    for cand in normalized:
        if re_match(U115_SHARE_URL_MATCH, cand):
            return cand
    return None


def _pick_preferred_share_url(links: List[str]) -> Optional[str]:
    """
    在已提取的链接中优先 115，其次阿里云

    :param links (List): 原始链接列表
    :return str: 规范化后的第一条可用分享 URL
    """
    normalized = [normalize_share_url_candidate(x) for x in links if x]
    for cand in normalized:
        if re_match(U115_SHARE_URL_MATCH, cand):
            return cand
    for cand in normalized:
        if re_match(ALIYUN_SHARE_URL_MATCH, cand):
            return cand
    return None


def _fetch_share_url_from_telegra(telegra_url: str) -> Optional[str]:
    """
    拉取 telegra.ph 页面并解析其中的云盘分享链接

    :param telegra_url (str): Telegraph 页面 URL
    :return str: 优先 115 的分享 URL，失败为 None
    """
    try:
        client = build_share_page_client()
        response = client.get(telegra_url, timeout=30)
        response.raise_for_status()
        links, _ = extract_cloud_link_urls_from_text(response.text)
        picked = _pick_preferred_share_url(links)
        if picked:
            logger.debug(f"【ShareLinks】从 telegra.ph 解析到分享链接: {telegra_url}")
        return picked
    except RequestError as e:
        logger.warning(f"【ShareLinks】访问 telegra.ph 失败: {telegra_url}, 错误: {e}")
        return None
    except Exception as e:
        logger.warning(
            f"【ShareLinks】解析 telegra.ph 页面出错: {telegra_url}, 错误: {e}"
        )
        return None


def _fetch_u115_share_url_from_telegra(telegra_url: str) -> Optional[str]:
    """
    拉取 telegra.ph 页面并解析其中的 115 分享链接（忽略阿里云等）

    :param telegra_url (str): Telegraph 页面 URL
    :return str: 第一条 115 分享 URL，失败为 None
    """
    try:
        client = build_share_page_client()
        response = client.get(telegra_url, timeout=30)
        response.raise_for_status()
        links, _ = extract_cloud_link_urls_from_text(response.text)
        picked = _pick_first_u115_url(links)
        if picked:
            logger.debug(
                f"【ShareLinks】从 telegra.ph 解析到 115 分享链接: {telegra_url}"
            )
        return picked
    except RequestError as e:
        logger.warning(f"【ShareLinks】访问 telegra.ph 失败: {telegra_url}, 错误: {e}")
        return None
    except Exception as e:
        logger.warning(
            f"【ShareLinks】解析 telegra.ph 页面出错: {telegra_url}, 错误: {e}"
        )
        return None


def _fetch_u115_share_urls_from_telegra(telegra_url: str) -> List[str]:
    """
    拉取 telegra.ph 页面并解析其中的所有 115 分享链接

    :param telegra_url (str): Telegraph 页面 URL
    :return List: 115 分享 URL 列表
    """
    try:
        client = build_share_page_client()
        response = client.get(telegra_url, timeout=30)
        response.raise_for_status()
        links, _ = extract_cloud_link_urls_from_text(response.text)
        return _filter_all_u115_urls(links)
    except RequestError as e:
        logger.warning(f"【ShareLinks】访问 telegra.ph 失败: {telegra_url}, 错误: {e}")
        return []
    except Exception as e:
        logger.warning(
            f"【ShareLinks】解析 telegra.ph 页面出错: {telegra_url}, 错误: {e}"
        )
        return []


def _filter_all_u115_urls(links: List[str]) -> List[str]:
    """
    从链接列表中过滤出所有 115 分享 URL，去重并保持顺序

    :param links (List): 原始链接列表
    :return List: 去重后的 115 URL 列表
    """
    normalized = [normalize_share_url_candidate(x) for x in links if x]
    seen: Set[str] = set()
    result: List[str] = []
    for cand in normalized:
        if cand and re_match(U115_SHARE_URL_MATCH, cand) and cand not in seen:
            seen.add(cand)
            result.append(cand)
    return result


class ShareLinkResolver:
    """
    从用户消息中解析 115 / 阿里云分享链接

    支持直连 URL，以及通过 telegra.ph 等中间页拉取后再提取
    """

    @staticmethod
    def extract_share_url_from_text(text: Optional[str]) -> Optional[str]:
        """
        从整段消息文本中提取第一条可用的 115 或阿里云分享链接

        :param text (str): 用户消息全文
        :return str: 合法分享 URL，否则 None
        """
        if not text or not isinstance(text, str):
            return None

        for m in HTTPS_URL_TOKEN_PATTERN.finditer(text):
            cand = normalize_share_url_candidate(m.group(0))
            if not cand:
                continue
            if is_direct_u115_or_aliyun_share_url(cand):
                return cand
            if is_telegra_ph_url(cand):
                resolved = _fetch_share_url_from_telegra(cand)
                if resolved:
                    return resolved
                continue
        return None

    @staticmethod
    def extract_u115_share_url_from_text(text: Optional[str]) -> Optional[str]:
        """
        从整段消息文本中提取第一条 115 分享链接（不接受阿里云盘）

        :param text (str): 用户消息全文或命令参数
        :return str: 合法 115 分享 URL，否则 None
        """
        if not text or not isinstance(text, str):
            return None

        for m in HTTPS_URL_TOKEN_PATTERN.finditer(text):
            cand = normalize_share_url_candidate(m.group(0))
            if not cand:
                continue
            if re_match(U115_SHARE_URL_MATCH, cand):
                return cand
            if re_match(ALIYUN_SHARE_URL_MATCH, cand):
                continue
            if is_telegra_ph_url(cand):
                resolved = _fetch_u115_share_url_from_telegra(cand)
                if resolved:
                    return resolved
                continue
        return None

    @staticmethod
    def extract_all_u115_share_urls_from_text(text: Optional[str]) -> List[str]:
        """
        从整段消息文本中提取所有 115 分享链接（支持多行输入）

        :param text (str): 用户消息全文或命令参数
        :return List: 115 分享 URL 列表，无匹配时为空列表
        """
        if not text or not isinstance(text, str):
            return []

        urls: List[str] = []
        for m in HTTPS_URL_TOKEN_PATTERN.finditer(text):
            cand = normalize_share_url_candidate(m.group(0))
            if not cand:
                continue
            if re_match(U115_SHARE_URL_MATCH, cand):
                urls.append(cand)
            elif is_telegra_ph_url(cand):
                urls.extend(_fetch_u115_share_urls_from_telegra(cand))

        seen: Set[str] = set()
        result: List[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                result.append(url)
        return result
