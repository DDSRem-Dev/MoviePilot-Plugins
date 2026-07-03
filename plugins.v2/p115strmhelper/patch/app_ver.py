from functools import wraps
from typing import Any, Callable, Coroutine, Literal, Optional, Union

from orjson import dumps, loads as json_loads
from dicttools import dict_update
import p115client.client as _p115_client_mod
from p115client import P115Client
from p115client.util import complete_url
from p115cipher import (
    rsa_encrypt,
    rsa_decrypt,
    ecdh_aes_decrypt,
    make_upload_payload,
)

from app.log import logger

from ..utils.user_agent import UserAgentUtils


PLACEHOLDER_APP_VER = "99.99.99.99"

_MARKER = "__p115strmhelper_app_ver_patched__"


def _real_ua(real: str) -> str:
    """
    生成使用真实版本号的 115disk User-Agent
    """
    return f"Mozilla/5.0 115disk/{real} 115Browser/{real} 115wangpan_android/{real}"


class AppVerPatcher:
    """
    app_ver 补丁

    1. ``p115client.client.get_request``：所有 GET 请求的 ``params["app_ver"]``
       由该函数用 setdefault 塞入占位值，这里在其返回后统一替换。覆盖
       behavior/detail、life_show、iter_life_list 等全部 GET 接口。
    2. ``P115Client._clouddownload_lixianssp_request``：离线接口在方法体内无条件
       写死 ``app_ver`` / UA 并立即 RSA 加密，无法事后修改，故复制方法体、替换占位值。
    3. ``P115Client.upload_init``：上传初始化在方法体内无条件写死 ``appversion`` / UA
       并立即 ``make_upload_payload`` 加密，同样复制方法体、替换占位值。间接经由
       ``upload_file`` / ``upload_file_init`` / ``tool.upload`` 触达。
    """

    _original_get_request: Optional[Callable[..., Any]] = None
    _original_lixianssp: Optional[Callable[..., Any]] = None
    _original_upload_init: Optional[Callable[..., Any]] = None
    _active: bool = False

    @classmethod
    def _wrap_get_request(cls) -> None:
        original = _p115_client_mod.get_request
        if getattr(original, _MARKER, False):
            return

        @wraps(original)
        def patched(*args, **kwargs):
            request, request_kwargs = original(*args, **kwargs)
            params = request_kwargs.get("params")
            if (
                isinstance(params, dict)
                and params.get("app_ver") == PLACEHOLDER_APP_VER
            ):
                params["app_ver"] = UserAgentUtils.get_real_app_ver()
            return request, request_kwargs

        setattr(patched, _MARKER, True)
        cls._original_get_request = original
        _p115_client_mod.get_request = patched

    @staticmethod
    def _patched_lixianssp_request(
        self_instance: P115Client,
        payload: dict = {},
        /,
        action: str = "",
        base_url: Union[str, Callable[[], str]] = "https://clouddownload.115.com",
        *,
        async_: Literal[False, True] = False,
        **request_kwargs,
    ) -> Union[dict, Coroutine[Any, Any, dict]]:
        """
        重实现 ``_clouddownload_lixianssp_request``，使用真实 app_ver / UA
        """
        real = UserAgentUtils.get_real_app_ver()
        api = complete_url("/lixianssp/", base_url=base_url)
        request_kwargs["method"] = "POST"
        for k, v in payload.items():
            payload[k] = str(v)
        if action:
            payload["ac"] = action
        payload["app_ver"] = real
        request_kwargs["headers"] = {
            **(request_kwargs.get("headers") or {}),
            "user-agent": _real_ua(real),
        }
        request_kwargs["ecdh_encrypt"] = False

        def parse(_, content: bytes, /) -> dict:
            json = json_loads(content)
            if data := json.get("data"):
                try:
                    json["data"] = json_loads(rsa_decrypt(data))
                except Exception:
                    pass
            return json

        request_kwargs.setdefault("parse", parse)
        return self_instance.request(
            url=api,
            data={"data": rsa_encrypt(dumps(payload)).decode("ascii")},
            async_=async_,
            **request_kwargs,
        )

    @staticmethod
    def _patched_upload_init(
        self_instance: P115Client,
        payload: dict,
        /,
        base_url: Union[str, Callable[[], str]] = "https://uplb.115.com",
        *,
        async_: Literal[False, True] = False,
        **request_kwargs,
    ) -> Union[dict, Coroutine[Any, Any, dict]]:
        """
        重实现 ``upload_init``，使用真实 appversion / UA
        """
        real = UserAgentUtils.get_real_app_ver()
        api = complete_url("/4.0/initupload.php", base_url=base_url)
        payload = {
            "appid": 0,
            "target": "U_1_0",
            "sign_key": "",
            "sign_val": "",
            "topupload": "true",
            **payload,
            "appversion": real,
        }
        if "userid" not in payload:
            payload["userid"] = self_instance.user_id
        if "userkey" not in payload:
            payload["userkey"] = self_instance.user_key
        request_kwargs["headers"] = dict_update(
            dict(request_kwargs.get("headers") or ()),
            {
                "content-type": "application/x-www-form-urlencoded",
                "user-agent": _real_ua(real),
            },
        )
        request_kwargs.update(make_upload_payload(payload))

        def parse_upload_init_response(_, content: bytes, /) -> dict:
            data = ecdh_aes_decrypt(content)
            return json_loads(data)

        request_kwargs.setdefault("parse", parse_upload_init_response)
        return self_instance.request(
            url=api, method="POST", async_=async_, **request_kwargs
        )

    @classmethod
    def _wrap_method(cls, method_name: str, impl: Callable) -> Optional[Callable]:
        """
        用 ``impl`` 包装 ``P115Client.<method_name>``，返回被替换的原方法。

        若目标已被本补丁包装（带 ``_MARKER``），则跳过并返回 None。
        """
        original = getattr(P115Client, method_name)
        if getattr(original, _MARKER, False):
            return None

        @wraps(original)
        def patched(self, *args, **kwargs):
            return impl(self, *args, **kwargs)

        setattr(patched, _MARKER, True)
        setattr(P115Client, method_name, patched)
        return original

    @classmethod
    def _restore_method(cls, method_name: str, original: Optional[Callable]) -> None:
        """
        仅当当前方法仍是本补丁的包装时，才还原为 ``original``
        """
        if original is None:
            return
        current = getattr(P115Client, method_name, None)
        if getattr(current, _MARKER, False):
            setattr(P115Client, method_name, original)

    @classmethod
    def enable(cls) -> None:
        """
        应用补丁
        """
        if cls._active:
            return
        cls._wrap_get_request()
        cls._original_lixianssp = cls._wrap_method(
            "_clouddownload_lixianssp_request", cls._patched_lixianssp_request
        )
        cls._original_upload_init = cls._wrap_method(
            "upload_init", cls._patched_upload_init
        )
        cls._active = True
        logger.info("【app_ver】app_ver 补丁应用成功")

    @classmethod
    def disable(cls) -> None:
        """
        禁用补丁
        """
        if not cls._active:
            return
        current_get_request = getattr(_p115_client_mod, "get_request", None)
        if cls._original_get_request is not None and getattr(
            current_get_request, _MARKER, False
        ):
            _p115_client_mod.get_request = cls._original_get_request
        cls._original_get_request = None

        cls._restore_method("_clouddownload_lixianssp_request", cls._original_lixianssp)
        cls._original_lixianssp = None

        cls._restore_method("upload_init", cls._original_upload_init)
        cls._original_upload_init = None

        cls._active = False
        logger.info("【app_ver】app_ver 补丁恢复原始状态成功")
