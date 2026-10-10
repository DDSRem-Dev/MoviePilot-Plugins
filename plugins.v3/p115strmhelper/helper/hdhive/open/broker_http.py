from typing import Dict

from httpx import Client

from app.core.config import settings
from app.utils.http import AsyncRequestUtils

from ....core.config import configer
from .constants import HDHIVE_OAUTH_BROKER_BASE


def broker_http_client() -> Client:
    """
    创建访问 OAuth 中转的 httpx 客户端

    :return Client: 配置好 base_url 与代理的 Client
    """
    proxy_h = (
        AsyncRequestUtils._convert_proxies_for_httpx(settings.PROXY)
        if settings.PROXY
        else None
    )
    return Client(
        base_url=HDHIVE_OAUTH_BROKER_BASE.rstrip("/"),
        timeout=30.0,
        proxy=proxy_h,
    )


def broker_request_headers(instance_key: str) -> Dict[str, str]:
    """
    中转请求通用头（实例标识 + 可选 Machine ID）

    :param instance_key (str): 实例 key
    :return Dict: 请求头 dict
    """
    headers = {
        "X-Instance-Key": instance_key,
        "Content-Type": "application/json",
    }
    machine_id = getattr(configer, "machine_id", None) or ""
    if machine_id:
        headers["X-Machine-Id"] = str(machine_id)
    return headers
