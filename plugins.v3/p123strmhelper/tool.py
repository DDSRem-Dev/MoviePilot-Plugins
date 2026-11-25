from typing import Any, Callable, Coroutine, Dict, Optional, Union

from p123client import P123Client


class P123AutoClient:
    """
    123云盘客户端
    """

    def __init__(self, passport: str, password: str):
        self._client = None
        self._passport = passport
        self._password = password

    def fs_list_new(
        self,
        payload: Union[Dict[str, Any], int, str] = 0,
        /,
        event: str = "homeListFile",
        base_url: Optional[Union[str, Callable[[], str]]] = None,
        *,
        async_: bool = False,
        **request_kwargs: Any,
    ) -> Union[Dict[str, Any], Coroutine[Any, Any, Dict[str, Any]]]:
        """
        保留接口要求的参数大小写，获取文件或目录列表

        :param payload (Union): 父目录 ID 或查询参数，查询参数使用接口原始键名
        :param event (str): 文件列表事件类型
        :param base_url (Union): 请求基地址，未指定时使用客户端默认值
        :param async_ (bool): 是否异步请求
        :param request_kwargs (Dict): 传递给客户端的其他请求参数

        :return Union: 同步返回响应字典，异步返回协程
        """
        if isinstance(payload, (int, str)):
            payload = {"parentFileId": payload}
        params = {
            "driveId": 0,
            "limit": 100,
            "orderBy": "file_id",
            "orderDirection": "asc",
            "parentFileId": 0,
            "inDirectSpace": False,
            "fileCategory": 0,
            "event": event,
            "OnlyLookAbnormalFile": 0,
            "Page": 1,
            **payload,
        }
        if params.get("trashed") is None:
            params["trashed"] = params["event"] == "recycleListFile"
        if base_url is not None:
            request_kwargs["base_url"] = base_url
        return self.request(
            "file/list/new",
            params=params,
            async_=async_,
            **request_kwargs,
        )

    def __getattr__(self, name):
        if self._client is None:
            self._client = P123Client(passport=self._passport, password=self._password)

        def wrapped(*args, **kwargs):
            """
            代理调用 P123Client 的方法，自动处理 Token 超限重连

            :param args: 传递给客户端方法的位置参数
            :param kwargs: 传递给客户端方法的关键字参数
            :return: 客户端方法的返回值
            """
            attr = getattr(self._client, name)
            if not callable(attr):
                return attr
            result = attr(*args, **kwargs)
            if (
                isinstance(result, dict)
                and result.get("code") == 401
                and result.get("message") == "tokens number has exceeded the limit"
            ):
                self._client = P123Client(self._passport, self._password)
                attr = getattr(self._client, name)
                if not callable(attr):
                    return attr
                return attr(*args, **kwargs)
            return result

        return wrapped
