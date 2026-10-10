from typing import Any

from httpx import Response


class HDHiveAPIError(Exception):
    """
    HDHive API 错误的基类
    """

    def __init__(
        self,
        code: str,
        message: str,
        description: str | None = None,
        http_status: int | None = None,
        *,
        limit_scope: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        """
        :param code (str): 服务端业务错误码或回退为 HTTP 状态码字符串
        :param message (str): 错误摘要
        :param description (str): 可选详细说明
        :param http_status (int): 响应 HTTP 状态码
        :param limit_scope (str): 限流范围（global/app/user）
        :param retry_after (float): Retry-After 秒数
        """
        self.code = code
        self.message = message
        self.description = description
        self.http_status = http_status
        self.limit_scope = limit_scope
        self.retry_after = retry_after
        super().__init__(
            f"[{code}] {message}" + (f" — {description}" if description else "")
        )


class HDHiveAuthError(HDHiveAPIError):
    """
    401 或鉴权相关错误
    """


class HDHiveReauthRequiredError(HDHiveAuthError):
    """
    需要重新 OAuth 授权（OPENAPI_REAUTH_REQUIRED）
    """


class HDHiveRefreshRequiredError(HDHiveAuthError):
    """
    Access Token 需刷新（OPENAPI_REFRESH_REQUIRED）
    """


class HDHiveForbiddenError(HDHiveAPIError):
    """
    403 禁止访问
    """


class HDHiveNotFoundError(HDHiveAPIError):
    """
    404 资源不存在
    """


class HDHiveRateLimitError(HDHiveAPIError):
    """
    429 限流或配额
    """


class HDHiveInsufficientPointsError(HDHiveAPIError):
    """
    402 积分不足（INSUFFICIENT_POINTS）
    """


_ERROR_MAP: dict[int, type[HDHiveAPIError]] = {
    401: HDHiveAuthError,
    403: HDHiveForbiddenError,
    404: HDHiveNotFoundError,
    402: HDHiveInsufficientPointsError,
    429: HDHiveRateLimitError,
}

_CODE_MAP: dict[str, type[HDHiveAPIError]] = {
    "MISSING_API_KEY": HDHiveAuthError,
    "INVALID_API_KEY": HDHiveAuthError,
    "DISABLED_API_KEY": HDHiveAuthError,
    "EXPIRED_API_KEY": HDHiveAuthError,
    "OPENAPI_REFRESH_REQUIRED": HDHiveRefreshRequiredError,
    "OPENAPI_REAUTH_REQUIRED": HDHiveReauthRequiredError,
    "INVALID_OPENAPI_USER_TOKEN": HDHiveAuthError,
    "OPENAPI_USER_REQUIRED": HDHiveAuthError,
    "SCOPE_NOT_ALLOWED": HDHiveForbiddenError,
    "USER_SCOPE_NOT_ALLOWED": HDHiveForbiddenError,
    "VIP_REQUIRED": HDHiveForbiddenError,
    "ENDPOINT_DISABLED": HDHiveForbiddenError,
    "ENDPOINT_QUOTA_EXCEEDED": HDHiveRateLimitError,
    "RATE_LIMIT_EXCEEDED": HDHiveRateLimitError,
    "GLOBAL_RATE_LIMIT_EXCEEDED": HDHiveRateLimitError,
    "APP_RATE_LIMIT_EXCEEDED": HDHiveRateLimitError,
    "USER_RATE_LIMIT_EXCEEDED": HDHiveRateLimitError,
    "OPENAPI_COOLDOWN": HDHiveRateLimitError,
    "INSUFFICIENT_POINTS": HDHiveInsufficientPointsError,
}


def _parse_retry_after(resp: Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def raise_for_response(resp: Response) -> None:
    """
    解析统一 JSON 错误体并抛出对应异常；成功响应则直接返回

    :param resp (Response): httpx 响应对象
    :raises HDHiveAPIError: 业务失败或 HTTP 错误时
    """
    retry_after = _parse_retry_after(resp)
    try:
        body: dict[str, Any] = resp.json()
    except Exception:
        resp.raise_for_status()
        return

    if body.get("success"):
        return

    code: str = str(body.get("code", resp.status_code))
    message: str = body.get("message", "Unknown error")
    description: str | None = body.get("description")
    http_status: int = resp.status_code
    limit_scope: str | None = body.get("limit_scope")

    exc_cls = _CODE_MAP.get(code) or _ERROR_MAP.get(http_status, HDHiveAPIError)
    raise exc_cls(
        code=code,
        message=message,
        description=description,
        http_status=http_status,
        limit_scope=limit_scope,
        retry_after=retry_after,
    )
