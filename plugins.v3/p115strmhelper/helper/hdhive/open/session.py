from typing import Any, Dict, Literal, Optional

from app.log import logger

from .broker_http import broker_http_client, broker_request_headers
from .client import HDHiveOpenClient
from .errors import (
    HDHiveAPIError,
    HDHiveReauthRequiredError,
    HDHiveRefreshRequiredError,
    raise_for_response,
)
from .oauth import broker_refresh
from .token_store import (
    is_access_valid,
    is_refresh_valid,
    load_oauth_bundle,
)

AuthMode = Literal["oauth", "none"]


def _resolve_auth_mode() -> AuthMode:
    """
    解析当前鉴权模式

    :return str: ``oauth`` 或 ``none``
    """
    bundle = load_oauth_bundle()
    if (bundle.get("access_token") or "").strip():
        if is_access_valid(bundle) or is_refresh_valid(bundle):
            return "oauth"
    return "none"


class HDHiveSession(HDHiveOpenClient):
    """
    统一 HDHive Open API 会话：OAuth 经中转代理，接口与 ``HDHiveOpenClient`` 一致
    """

    def __init__(self) -> None:
        super().__init__(defer_client=True)
        self._auth_mode: AuthMode = "none"

    @property
    def auth_mode(self) -> AuthMode:
        """
        最近一次请求使用的鉴权模式
        """
        return self._auth_mode

    def _ensure_oauth_access(self) -> Optional[str]:
        bundle = load_oauth_bundle()
        if is_access_valid(bundle):
            return str(bundle["access_token"])
        if is_refresh_valid(bundle):
            if broker_refresh():
                bundle = load_oauth_bundle()
                if is_access_valid(bundle):
                    return str(bundle["access_token"])
        return None

    def _proxy_open_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        access_token: str,
        instance_key: str,
    ) -> tuple[Any, Any]:
        url_path = path if path.startswith("/") else f"/{path}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            **broker_request_headers(instance_key),
        }
        with broker_http_client() as client:
            resp = client.request(
                method,
                f"/proxy/open{url_path}",
                params=params,
                json=json,
                headers=headers,
            )
        raise_for_response(resp)
        body: Dict[str, Any] = resp.json()
        return body.get("data"), body.get("meta")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        access_token: str | None = None,
        _retry_refresh: bool = True,
    ) -> Any:
        """
        经 OAuth 中转代理发起 Open API 请求

        :param access_token (str): 未使用（由 token_store 提供）
        :param _retry_refresh (bool): 内部用，是否在 REFRESH_REQUIRED 时自动刷新一次
        """
        del access_token
        if _resolve_auth_mode() != "oauth":
            self._auth_mode = "none"
            raise HDHiveAPIError(
                "OPENAPI_USER_REQUIRED",
                "未配置 HDHive OAuth，请在插件设置中完成授权",
            )

        token = self._ensure_oauth_access()
        if not token:
            self._auth_mode = "none"
            raise HDHiveReauthRequiredError(
                "OPENAPI_REAUTH_REQUIRED",
                "HDHive OAuth 已失效，请重新授权",
            )

        bundle = load_oauth_bundle()
        ik = str(bundle.get("instance_key") or "")
        try:
            self._auth_mode = "oauth"
            return self._proxy_open_request(
                method,
                path,
                params=params,
                json=json,
                access_token=token,
                instance_key=ik,
            )
        except HDHiveRefreshRequiredError:
            if _retry_refresh and broker_refresh():
                return self._request(
                    method,
                    path,
                    params=params,
                    json=json,
                    _retry_refresh=False,
                )
            raise
        except HDHiveReauthRequiredError:
            self._auth_mode = "none"
            logger.warning("【HDHive】OAuth 需重新授权")
            raise
