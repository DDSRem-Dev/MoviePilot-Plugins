from typing import Any, Dict, Optional

from app.log import logger

from .broker_http import broker_http_client, broker_request_headers
from .constants import DEFAULT_OAUTH_SCOPES
from .token_store import (
    apply_token_response,
    clear_oauth_bundle,
    get_or_create_instance_key,
    load_oauth_bundle,
)


def broker_oauth_start(
    *,
    scope: str = DEFAULT_OAUTH_SCOPES,
    instance_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    向中转请求授权 URL

    :param scope (str): OAuth scope
    :param instance_key (str): 可选已有 instance_key
    :return Dict: authorize_url、state、redirect_uri 等
    """
    ik = instance_key or get_or_create_instance_key()
    with broker_http_client() as client:
        resp = client.get(
            "/oauth/hdhive/start",
            params={"instance_key": ik, "scope": scope},
            headers=broker_request_headers(ik),
        )
        resp.raise_for_status()
        body = resp.json()
    if not body.get("success"):
        raise RuntimeError(body.get("code") or "broker start failed")
    data = body
    data.setdefault("instance_key", ik)
    return data


def broker_exchange(
    *,
    code: str,
    state: str,
    redirect_uri: str,
    instance_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    用授权码换取 Token 并写入 plugin_data

    :return Dict: 脱敏后的 bundle 摘要
    """
    ik = instance_key or get_or_create_instance_key()
    payload = {
        "instance_key": ik,
        "code": code,
        "state": state,
        "redirect_uri": redirect_uri,
    }
    with broker_http_client() as client:
        resp = client.post(
            "/oauth/hdhive/exchange",
            json=payload,
            headers=broker_request_headers(ik),
        )
        resp.raise_for_status()
        body = resp.json()
    if not body.get("success"):
        raise RuntimeError(body.get("message") or body.get("code") or "exchange failed")
    tokens = body.get("data") or {}
    bundle = apply_token_response(tokens, instance_key=ik)
    return {
        "instance_key": ik,
        "scope": bundle.get("scope"),
        "authorized_at": bundle.get("authorized_at"),
        "expires_at": bundle.get("expires_at"),
    }


def broker_refresh(*, instance_key: Optional[str] = None) -> bool:
    """
    通过中转刷新 Access Token

    :return bool: 是否刷新成功
    """
    bundle = load_oauth_bundle()
    ik = instance_key or bundle.get("instance_key") or get_or_create_instance_key()
    refresh_token = (bundle.get("refresh_token") or "").strip()
    if not refresh_token:
        return False
    payload = {"instance_key": ik, "refresh_token": refresh_token}
    try:
        with broker_http_client() as client:
            resp = client.post(
                "/oauth/hdhive/refresh",
                json=payload,
                headers=broker_request_headers(ik),
            )
            resp.raise_for_status()
            body = resp.json()
        if not body.get("success"):
            return False
        apply_token_response(body.get("data") or {}, instance_key=ik)
        return True
    except Exception as e:
        logger.warning("【HDHive】OAuth refresh 失败: %s", e)
        return False


def broker_revoke() -> None:
    """
    撤销 Refresh Token 并清空本地 OAuth 数据
    """
    bundle = load_oauth_bundle()
    ik = (bundle.get("instance_key") or "").strip()
    refresh_token = (bundle.get("refresh_token") or "").strip()
    if ik and refresh_token:
        try:
            with broker_http_client() as client:
                client.post(
                    "/oauth/hdhive/revoke",
                    json={"instance_key": ik, "refresh_token": refresh_token},
                    headers=broker_request_headers(ik),
                )
        except Exception as e:
            logger.warning("【HDHive】OAuth revoke 出站失败: %s", e)
    clear_oauth_bundle()
