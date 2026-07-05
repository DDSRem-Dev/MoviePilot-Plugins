from typing import Optional

import p115client.client as _p115_client_mod

from app.log import logger

from ..utils.user_agent import UserAgentUtils

_APP_VERSION_ATTR = "_app_version"


class AppVerPatcher:
    """
    app_ver 补丁
    """

    _original_app_version: Optional[str] = None
    _patched_app_version: Optional[str] = None
    _active: bool = False

    @classmethod
    def enable(cls) -> None:
        """
        应用补丁
        """
        if cls._active:
            return
        if not hasattr(_p115_client_mod, _APP_VERSION_ATTR):
            logger.warning(
                "【app_ver】未找到 p115client.client._app_version，跳过补丁"
                "（p115client 版本可能不兼容）"
            )
            return

        cls._original_app_version = getattr(_p115_client_mod, _APP_VERSION_ATTR)
        real = UserAgentUtils.get_real_app_ver()
        setattr(_p115_client_mod, _APP_VERSION_ATTR, real)
        cls._patched_app_version = real
        cls._active = True
        logger.info(f"【app_ver】app_ver 补丁应用成功，app_ver={real}")

    @classmethod
    def disable(cls) -> None:
        """
        禁用补丁
        """
        if not cls._active:
            return
        if cls._original_app_version is not None and (
            getattr(_p115_client_mod, _APP_VERSION_ATTR, None)
            == cls._patched_app_version
        ):
            setattr(_p115_client_mod, _APP_VERSION_ATTR, cls._original_app_version)
        cls._original_app_version = None
        cls._patched_app_version = None
        cls._active = False
        logger.info("【app_ver】app_ver 补丁恢复原始状态成功")
