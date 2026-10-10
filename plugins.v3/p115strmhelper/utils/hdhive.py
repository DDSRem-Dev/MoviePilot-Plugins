from json import JSONDecodeError, loads
from re import fullmatch
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit


READ_RESOURCE_CHUNKS_JS = """
() => [...document.scripts].flatMap(script => {
    const text = (script.textContent || '').trim();
    const prefix = 'self.__next_f.push(';
    if (!text.startsWith(prefix)) return [];
    try {
        const chunk = JSON.parse(text.slice(prefix.length, text.lastIndexOf(')')));
        return chunk[0] === 1 && typeof chunk[1] === 'string' ? [chunk[1]] : [];
    } catch { return []; }
})
"""

EXTRACT_SHARE_URL_JS = r"""
() => {
    const valid = value => {
        try {
            const url = new URL(value);
            return ['http:', 'https:'].includes(url.protocol) &&
                ['115.com', '115cdn.com', 'anxia.com'].includes(url.hostname) &&
                /^\/s\/[^/\s]+\/?$/.test(url.pathname) && !url.username && !url.password;
        } catch { return false; }
    };
    for (const el of document.querySelectorAll('a[href], input, textarea')) {
        const value = el.tagName === 'A' ? el.href : el.value;
        if (valid(value)) return value.trim();
    }
    for (const value of (document.body?.innerText || '').match(/https?:\/\/[^\s<>"']+/g) || []) {
        if (valid(value)) return value;
    }
    return null;
}
"""


def extract_hdhive_resource_slug(href: str) -> Optional[str]:
    """
    从 RE0 或旧站 115 资源详情地址提取 slug，忽略查询参数和片段

    :param href (str): 资源详情地址或相对路径

    :return str: 合法的资源 slug，非 115 资源地址返回 None
    """
    try:
        url = urlsplit(href)
        if url.netloc and url.hostname not in ("re0.me", "hdhive.com"):
            return None
        if url.scheme and url.scheme not in ("http", "https"):
            return None
        match = fullmatch(r"/resource/115/([A-Za-z0-9_-]+)/?", url.path)
        return match[1] if match else None
    except ValueError:
        return None


def is_hdhive_share_url(value: Any) -> bool:
    """
    判断地址是否为受支持的 115 分享链接

    :param value (Any): 待校验地址

    :return bool: 地址为合法分享链接时返回 True
    """
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value.strip())
        return (
            url.scheme in ("http", "https")
            and url.hostname in ("115.com", "115cdn.com", "anxia.com")
            and not url.username
            and not url.password
            and fullmatch(r"/s/[^/\s]+/?", url.path) is not None
        )
    except ValueError:
        return False


def _normalize_resource(row: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    website = row.get("website")
    if website is not None and str(website) != "115":
        return None
    href = row.get("href")
    if isinstance(href, str) and extract_hdhive_resource_slug(href):
        return row
    slug = row.get("slug")
    if (
        str(website) != "115"
        or not isinstance(slug, str)
        or not fullmatch(r"[A-Za-z0-9_-]+", slug)
    ):
        return None
    user = row.get("user")
    username = (
        (user.get("nickname") or user.get("username") or "")
        if isinstance(user, dict)
        else ""
    )
    resolutions = row.get("video_resolution")
    points = row.get("unlock_points")
    try:
        points = int(points) if points is not None else 0
    except (TypeError, ValueError):
        points = None
    tags = []
    if row.get("is_official"):
        tags.append("官组")
    if points == 0:
        tags.append("免费")
    return {
        "href": f"/resource/115/{slug}",
        "title": str(row.get("remark") or row.get("title") or "未命名").strip(),
        "user": str(username).strip(),
        "posted_at": row.get("submitted_at") or row.get("created_at") or "",
        "tags": tags,
        "size": str(row.get("share_size") or ""),
        "resolution": " / ".join(str(value) for value in resolutions)
        if isinstance(resolutions, list)
        else str(resolutions or ""),
        "video_resolution": resolutions if isinstance(resolutions, list) else [],
        "source": row.get("source") if isinstance(row.get("source"), list) else [],
        "subtitle_language": row.get("subtitle_language")
        if isinstance(row.get("subtitle_language"), list)
        else [],
        "subtitle_type": row.get("subtitle_type")
        if isinstance(row.get("subtitle_type"), list)
        else [],
        "is_free": points == 0,
        "unlock_points": points,
    }


def extract_hdhive_resource_rows(body: Any) -> List[Dict[str, Any]]:
    """
    从 RE0 JSON 响应中筛选并规范化 115 资源条目

    :param body (Any): JSON 响应体

    :return List: 去除其他网盘及重复资源后的条目
    """
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return []
    rows = {}
    for row in body["data"]:
        normalized = _normalize_resource(row)
        if normalized:
            rows[extract_hdhive_resource_slug(normalized["href"])] = normalized
    return list(rows.values())


def extract_hdhive_page_resources(chunks: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    从 RE0 页面内嵌的 Next.js 数据分片读取资源分组

    不执行脚本，不依赖构建版本或动态 Server Action ID

    :param chunks (List): 页面按顺序提供的文本数据分片

    :return List: 115 资源列表，缺少可识别的资源分组时返回 None
    """
    records = {}
    for line in "".join(chunks).splitlines():
        key, separator, value = line.partition(":")
        if not separator or not fullmatch(r"[0-9a-fA-F]+", key):
            continue
        try:
            records[key] = loads(value)
        except (JSONDecodeError, ValueError):
            continue

    unresolved = object()

    def resolve(value: Any, seen: Optional[Set[str]] = None) -> Any:
        if isinstance(value, str) and fullmatch(r"\$[0-9a-fA-F]+", value):
            key = value[1:]
            seen = seen or set()
            if key in records and key not in seen:
                return resolve(records[key], seen | {key})
            return unresolved
        return value

    groups = []
    for record in records.values():
        pending = [record]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                if "groupData" in value:
                    group = resolve(value["groupData"])
                    if group is unresolved:
                        return None
                    if isinstance(group, dict):
                        groups.append(group)
                pending.extend(value.values())
    if not groups:
        return None
    resources = []
    for group in groups:
        rows = resolve(group.get("115", []))
        if not isinstance(rows, list):
            return None
        for row in rows:
            row = resolve(row)
            if row is unresolved:
                return None
            if isinstance(row, dict):
                resource = {key: resolve(value) for key, value in row.items()}
                website = resource.get("website")
                if (
                    website is not None
                    and website is not unresolved
                    and str(website) != "115"
                ):
                    continue
                if any(value is unresolved for value in resource.values()):
                    return None
                resources.append(resource)
    return extract_hdhive_resource_rows({"data": resources})
