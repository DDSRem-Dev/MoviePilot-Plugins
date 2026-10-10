from datetime import datetime, timezone
from secrets import token_urlsafe
from time import time
from typing import Any, Dict, Optional

from ....core.config import configer
from .constants import PLUGIN_DATA_KEY_OAUTH, TOKEN_EXPIRY_BUFFER_SEC


def load_oauth_bundle() -> Dict[str, Any]:
    """
    读取 OAuth Token 包

    :return Dict: 存储 dict，不存在时为空 dict
    """
    return configer.get_plugin_data(PLUGIN_DATA_KEY_OAUTH) or {}


def save_oauth_bundle(bundle: Dict[str, Any]) -> None:
    """
    保存 OAuth Token 包

    :param bundle (Dict): Token 字段 dict
    """
    configer.save_plugin_data(PLUGIN_DATA_KEY_OAUTH, bundle)


def clear_oauth_bundle() -> None:
    """
    删除本地 OAuth Token
    """
    configer.del_plugin_data(PLUGIN_DATA_KEY_OAUTH)


def get_or_create_instance_key() -> str:
    """
    获取或生成实例级 instance_key

    :return str: instance_key 字符串
    """
    bundle = load_oauth_bundle()
    key = (bundle.get("instance_key") or "").strip()
    if key:
        return key
    key = token_urlsafe(32)
    bundle["instance_key"] = key
    save_oauth_bundle(bundle)
    return key


def _now_ts() -> int:
    return int(time())


def is_access_valid(bundle: Optional[Dict[str, Any]] = None) -> bool:
    """
    Access Token 是否在有效期内

    :param bundle (Dict): 可选已加载 bundle
    """
    b = bundle if bundle is not None else load_oauth_bundle()
    exp = b.get("expires_at")
    if not exp:
        return False
    return _now_ts() < int(exp)


def is_refresh_valid(bundle: Optional[Dict[str, Any]] = None) -> bool:
    """
    Refresh Token 是否仍可用

    :param bundle (Dict): 可选已加载 bundle
    """
    b = bundle if bundle is not None else load_oauth_bundle()
    rt = (b.get("refresh_token") or "").strip()
    if not rt:
        return False
    exp = b.get("refresh_expires_at")
    if exp is None:
        return True
    return _now_ts() < int(exp)


def is_authorized() -> bool:
    """
    是否已 OAuth 授权且凭证仍可用（access 有效或 refresh 可用）

    :return bool: 是否视为已授权
    """
    bundle = load_oauth_bundle()
    if not (bundle.get("access_token") or "").strip():
        return False
    return is_access_valid(bundle) or is_refresh_valid(bundle)


def apply_token_response(data: Dict[str, Any], *, instance_key: str) -> Dict[str, Any]:
    """
    将 broker/HDHive 返回的 token 数据写入 bundle 结构

    :param data (Dict): 含 access_token、refresh_token、expires_in 等
    :param instance_key (str): 实例 key
    :return Dict: 完整 bundle
    """
    now = _now_ts()
    expires_in = int(data.get("expires_in") or 0)
    refresh_expires_in = data.get("refresh_expires_in")
    bundle: Dict[str, Any] = {
        "instance_key": instance_key,
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": now + max(expires_in - TOKEN_EXPIRY_BUFFER_SEC, 0),
        "scope": data.get("scope") or "",
        "authorized_at": datetime.now(timezone.utc).isoformat(),
    }
    if refresh_expires_in is not None:
        bundle["refresh_expires_at"] = now + int(refresh_expires_in)
    save_oauth_bundle(bundle)
    return bundle


def status_snapshot() -> Dict[str, Any]:
    """
    供 API 返回的脱敏状态

    :return Dict: 不含 refresh_token / access_token 明文
    """
    bundle = load_oauth_bundle()
    oauth_ok = is_authorized()
    return {
        "auth_mode": "oauth" if oauth_ok else "none",
        "oauth_configured": oauth_ok,
        "scope": bundle.get("scope"),
        "authorized_at": bundle.get("authorized_at"),
        "expires_at": bundle.get("expires_at"),
        "instance_key": bundle.get("instance_key"),
    }
