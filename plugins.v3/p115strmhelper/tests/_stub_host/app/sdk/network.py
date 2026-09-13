"""
``app.sdk.network`` 替身。

真实宿主从 ``app.adapters.network.http`` / ``app.domain.site`` 等重新导出。
替身只提供插件实际引用的两个符号，并保留宿主中被插件当作公开工具使用的
``_convert_proxies_for_httpx``（把 requests 风格的代理字典转成 httpx 字符串）。
"""

from typing import Any, Callable, Dict, Optional, Union

__all__ = ["AsyncRequestUtils", "RequestUtils"]


def _convert_proxies_for_httpx(
    proxies: Optional[Union[str, Dict[str, str]]],
) -> Optional[str]:
    """把 requests 格式的代理配置转换为 httpx 兼容格式。

    :param proxies: 形如 ``{"http": "http://proxy:port"}`` 的字典，或已是字符串
    :return: httpx 可接受的代理字符串；无有效代理时返回 ``None``
    """
    if not proxies:
        return None
    if isinstance(proxies, str):
        return proxies
    if isinstance(proxies, dict):
        # httpx 只接受单一代理地址，优先取 https，再退到 http
        for scheme in ("https", "http", "all"):
            candidate = proxies.get(scheme)
            if candidate:
                return candidate if "://" in candidate else f"http://{candidate}"
        # 字典非空但键名不在预期内：退回任意第一个值
        for candidate in proxies.values():
            if candidate:
                return candidate if "://" in candidate else f"http://{candidate}"
    return None


class RequestUtils:
    """同步 HTTP 工具替身（只保留插件用到的静态能力）。"""

    _convert_proxies_for_httpx = staticmethod(_convert_proxies_for_httpx)


class AsyncRequestUtils:
    """异步 HTTP 工具替身（只保留插件用到的静态能力）。"""

    _convert_proxies_for_httpx = staticmethod(_convert_proxies_for_httpx)
