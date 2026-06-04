from inspect import signature as inspect_signature
from typing import Any, Callable, Dict, Optional

from p115client import P115Client

from app.log import logger


SLOW_METHODS = {
    "download_url",
    "download_url_app",
    "download_urls",
    "upload_file_init",
    "upload_gettoken",
    "upload_file",
    "share_snap",
    "share_snap_app",
    "share_snap_cookie",
    "share_receive",
    "life_behavior_detail",
    "life_behavior_detail_app",
    "offline_add_urls",
}

NO_TIMEOUT_METHODS = {
    "to_pickcode",
    "to_id",
    "get_fs",
    "login_app",
    "login_qrcode",
    "login_qrcode_token",
    "login_qrcode_scan_status",
    "login_qrcode_scan_result",
}


def _accepts_extra_kwargs(func: Callable) -> bool:
    try:
        sig = inspect_signature(func)
        return any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
    except (ValueError, TypeError):
        return False


def _make_timeout_wrapper(
    default_timeout: Dict[str, Any], slow_timeout: Dict[str, Any]
):
    def __getattribute__(self, name: str):
        if name.startswith("_") or name in (
            "__init__",
            "__class__",
            "__dict__",
            "__getattribute__",
            "__getattr__",
        ):
            return object.__getattribute__(self, name)

        attr = object.__getattribute__(self, name)

        if name in NO_TIMEOUT_METHODS:
            return attr

        timeout = slow_timeout if name in SLOW_METHODS else default_timeout

        if callable(attr) and timeout:
            if not _accepts_extra_kwargs(attr):
                return attr

            def wrapper(*args, **kwargs):
                """
                拦截 API 方法调用，自动注入超时配置到 extensions 参数中

                若调用者已显式指定 extensions["timeout"]，则跳过注入
                """
                if "extensions" in kwargs and "timeout" in kwargs.get("extensions", {}):
                    logger.debug(f"【超时包装】{name} 调用者已指定超时，跳过注入")
                    return attr(*args, **kwargs)
                if "extensions" not in kwargs:
                    kwargs["extensions"] = {}
                kwargs["extensions"]["timeout"] = timeout
                timeout_type = "慢操作" if name in SLOW_METHODS else "普通"
                logger.debug(f"【超时包装】{name} 注入{timeout_type}超时: {timeout}")
                return attr(*args, **kwargs)

            return wrapper
        return attr

    return __getattribute__


def create_client_with_timeout(
    client: P115Client,
    default_timeout: Optional[Dict[str, Any]] = None,
    slow_timeout: Optional[Dict[str, Any]] = None,
) -> P115Client:
    """
    为现有的 P115Client 实例添加超时支持

    :param client (P115Client): P115Client 实例（或其子类）
    :param default_timeout (Dict): 普通操作超时配置
    :param slow_timeout (Dict): 慢操作超时配置

    :return P115Client: 带超时支持的客户端
    """
    if not default_timeout:
        return client

    slow_timeout = slow_timeout or default_timeout

    class TimeoutMixin:
        """
        混入类，通过 __getattribute__ 拦截方法调用以注入超时
        """

        __getattribute__ = _make_timeout_wrapper(default_timeout, slow_timeout)

    wrapper_class = type(
        f"{type(client).__name__}WithTimeout",
        (TimeoutMixin, type(client)),
        {},
    )

    wrapper = object.__new__(wrapper_class)
    for key, value in client.__dict__.items():
        object.__setattr__(wrapper, key, value)
    return wrapper


class P115ClientWithTimeout(P115Client):
    """
    P115Client 子类，自动注入超时配置到所有 API 调用

    支持两种超时级别：
    - default_timeout: 普通操作（list/detail/rename 等）
    - slow_timeout: 慢操作（upload/download/iter 等）

    如果调用者显式指定 extensions["timeout"]，则优先使用调用者的配置
    """

    def __init__(
        self,
        cookies: Any,
        default_timeout: Optional[Dict[str, Any]] = None,
        slow_timeout: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """
        初始化带超时的 P115Client

        :param cookies (Any): 115 Cookie（字符串或路径）
        :param default_timeout (Dict): 普通操作超时配置，如 {"connect": 30, "read": 60}
        :param slow_timeout (Dict): 慢操作超时配置，如 {"connect": 30, "read": 300}
        """
        super().__init__(cookies, **kwargs)
        self._default_timeout = default_timeout
        self._slow_timeout = slow_timeout or default_timeout

    def __getattribute__(self, name: str):
        if name.startswith("_") or name in (
            "__init__",
            "__class__",
            "__dict__",
            "__getattribute__",
            "__getattr__",
        ):
            return object.__getattribute__(self, name)

        attr = object.__getattribute__(self, name)

        try:
            default_timeout = object.__getattribute__(self, "_default_timeout")
            slow_timeout = object.__getattribute__(self, "_slow_timeout")
        except AttributeError:
            return attr

        if name in NO_TIMEOUT_METHODS:
            return attr

        timeout = slow_timeout if name in SLOW_METHODS else default_timeout

        if callable(attr) and timeout:
            if not _accepts_extra_kwargs(attr):
                return attr

            def wrapper(*args, **kwargs):
                """
                拦截 API 方法调用，自动注入超时配置到 extensions 参数中

                若调用者已显式指定 extensions["timeout"]，则跳过注入
                """
                if "extensions" in kwargs and "timeout" in kwargs.get("extensions", {}):
                    logger.debug(f"【超时包装】{name} 调用者已指定超时，跳过注入")
                    return attr(*args, **kwargs)
                if "extensions" not in kwargs:
                    kwargs["extensions"] = {}
                kwargs["extensions"]["timeout"] = timeout
                timeout_type = "慢操作" if name in SLOW_METHODS else "普通"
                logger.debug(f"【超时包装】{name} 注入{timeout_type}超时: {timeout}")
                return attr(*args, **kwargs)

            return wrapper
        return attr


def create_client(
    cookies: Any,
    default_timeout: Optional[Dict[str, Any]] = None,
    slow_timeout: Optional[Dict[str, Any]] = None,
) -> P115Client:
    """
    创建 P115Client，可选带超时配置

    :param cookies (Any): 115 Cookie（字符串或路径）
    :param default_timeout (Dict): 普通操作超时，如 {"connect": 30, "read": 60}，None 表示不启用
    :param slow_timeout (Dict): 慢操作超时，如 {"connect": 30, "read": 300}，None 则与 default_timeout 相同

    :return P115Client: P115Client 实例（可能被 P115ClientWithTimeout 包装）
    """
    if not default_timeout:
        return P115Client(cookies)

    slow_timeout = slow_timeout or default_timeout
    logger.debug(
        f"【超时包装】已启用，默认超时: {default_timeout}, 慢操作超时: {slow_timeout}"
    )
    return P115ClientWithTimeout(cookies, default_timeout, slow_timeout)


def build_timeout_config(
    timeout_enabled: bool,
    connect: int = 30,
    pool: int = 15,
    read: int = 60,
    write: int = 60,
) -> Optional[Dict[str, Any]]:
    """
    从配置值构建超时字典

    :param timeout_enabled (bool): 是否启用超时
    :param connect (int): 连接超时秒数
    :param pool (int): 连接池超时秒数
    :param read (int): 读取超时秒数
    :param write (int): 写入超时秒数

    :return Dict: 超时配置字典，未启用时返回 None
    """
    if not timeout_enabled:
        return None
    timeout = {}
    if connect > 0:
        timeout["connect"] = connect
    if pool > 0:
        timeout["pool"] = pool
    if read > 0:
        timeout["read"] = read
    if write > 0:
        timeout["write"] = write
    return timeout if timeout else None
