from p123client import P123Client


class P123AutoClient:
    """
    123云盘客户端
    """

    def __init__(self, passport: str, password: str):
        self._client = None
        self._passport = passport
        self._password = password

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
