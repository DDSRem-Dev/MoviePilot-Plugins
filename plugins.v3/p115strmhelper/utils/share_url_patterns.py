__all__ = [
    "ALIYUN_SHARE_URL_MATCH",
    "HTTPS_URL_TOKEN_PATTERN",
    "U115_SHARE_URL_MATCH",
    "extract_cloud_link_urls_from_text",
    "is_direct_u115_or_aliyun_share_url",
    "is_telegra_ph_url",
    "normalize_share_url_candidate",
]


from re import compile as re_compile, findall, match
from typing import List, Tuple
from urllib.parse import urlparse


U115_SHARE_URL_MATCH = r"^https?://(.*\.)?115[^/]*\.[a-zA-Z]{2,}(?:/|$)"
ALIYUN_SHARE_URL_MATCH = r"^https?://(.*\.)?(alipan|aliyundrive)\.[a-zA-Z]{2,}(?:/|$)"

HTTPS_URL_TOKEN_PATTERN = re_compile(r"https?://[^\s)]+")

_TRAILING_JUNK = frozenset(".,;，。；、）)」』\"'")


def normalize_share_url_candidate(raw: str) -> str:
    """
    去掉 URL 末尾可能被一并匹配到的标点或全角括号

    :param raw (str): 原始子串

    :return str: 规范化后的字符串
    """
    s = raw.strip()
    while s and s[-1] in _TRAILING_JUNK:
        s = s[:-1].rstrip()
    return s


def is_telegra_ph_url(url: str) -> bool:
    """
    判断 URL 是否指向 telegra.ph（含子域）

    :param url (str): 完整 http(s) URL

    :return bool: 是否为 Telegraph 页面
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        host = (parsed.netloc or "").lower()
        if "@" in host:
            host = host.split("@")[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        return host == "telegra.ph" or host.endswith(".telegra.ph")
    except Exception:
        return False


_CLOUD_LINK_FINDALL_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (
        "u115",
        r"(https?://(?:[a-zA-Z0-9-]+\.)*115[^/\s#]*\.[a-zA-Z]{2,}[^\s#]*)",
    ),
    (
        "aliyun",
        r"(https?://(?:[a-zA-Z0-9-]+\.)?(?:alipan|aliyundrive)\.[a-zA-Z]{2,}[^\s#]*)",
    ),
)


def extract_cloud_link_urls_from_text(text: str) -> Tuple[List[str], str]:
    """
    从任意字符串（含 HTML）中用正则提取 115 与阿里云链接（无 I/O、无日志）

    :param text (str): 网页或纯文本

    :return Tuple: (去重后的链接列表, 首个匹配到的云类型 u115/aliyun，无则空串)
    """
    if not text or not isinstance(text, str):
        return [], ""

    links: List[str] = []
    cloud_type = ""

    for cloud_name, pattern in _CLOUD_LINK_FINDALL_PATTERNS:
        matches = findall(pattern, text)
        if matches:
            links.extend(matches)
            if not cloud_type:
                cloud_type = cloud_name

    return list(set(links)), cloud_type


def is_direct_u115_or_aliyun_share_url(url: str) -> bool:
    """
    判断是否为直连 115 或阿里云分享 URL（与历史 match 规则一致）

    :param url (str): 已规范化的候选 URL

    :return bool: 是否匹配
    """
    if not url:
        return False
    return bool(match(U115_SHARE_URL_MATCH, url)) or bool(
        match(ALIYUN_SHARE_URL_MATCH, url)
    )
