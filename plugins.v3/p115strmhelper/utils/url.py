__all__ = ["Url", "UrlUtils"]


from typing import Any, Dict, Self
from urllib.parse import parse_qs, quote, urlparse


class Url(str):
    """
    带属性字典的 URL 字符串，支持同时作为字符串使用和通过属性/字典访问附加元数据
    """

    def __new__(cls, val: Any = "", /, *args, **kwds):
        return super().__new__(cls, val)

    def __init__(self, val: Any = "", /, *args, **kwds):
        self.__dict__.update(*args, **kwds)

    def __getattr__(self, attr: str, /):
        try:
            return self.__dict__[attr]
        except KeyError as e:
            raise AttributeError(attr) from e

    def __getitem__(self, key, /):
        try:
            if isinstance(key, str):
                return self.__dict__[key]
        except KeyError:
            return super().__getitem__(key)  # type: ignore

    def __repr__(self, /) -> str:
        cls = type(self)
        if (module := cls.__module__) == "__main__":
            name = cls.__qualname__
        else:
            name = f"{module}.{cls.__qualname__}"
        return f"{name}({super().__repr__()}, {self.__dict__!r})"

    @classmethod
    def of(cls, val: Any = "", /, ns: None | dict = None) -> Self:
        """
        创建带有属性字典的 Url 实例

        :param val (str): URL 字符串值
        :param ns (dict): 附加的属性字典

        :return Url: 新的 Url 实例
        """
        self = cls.__new__(cls, val)
        if ns is not None:
            self.__dict__ = ns
        return self

    def get(self, key, /, default=None):
        """
        从属性字典中获取值，不存在时返回默认值

        :param key (str): 属性键名
        :param default (Any): 默认值

        :return Any: 属性值或默认值
        """
        return self.__dict__.get(key, default)

    def items(self, /):
        """
        返回属性字典的 (key, value) 键值对视图

        :return: 属性字典 items 视图
        """
        return self.__dict__.items()

    def keys(self, /):
        """
        返回属性字典的键视图

        :return: 属性字典 keys 视图
        """
        return self.__dict__.keys()

    def values(self, /):
        """
        返回属性字典的值视图

        :return: 属性字典 values 视图
        """
        return self.__dict__.values()


class UrlUtils:
    """
    URL 解析与编码工具
    """

    @staticmethod
    def encode_url_fully(url: str) -> str:
        """
        对 URL 中的非 ASCII 字符和空白字符做百分号编码

        保留 URL 保留字符和已有百分号转义，避免改变签名查询串

        :param url (str): 完整 URL

        :return str: 编码后的 URL
        """
        return quote(url, safe=":/?#@!$&'()*+,;=%")

    @staticmethod
    def parse_query_params(url: str) -> Dict[str, str]:
        """
        从 URL 中解析查询字符串里的全部参数（主要返回值即该 dict）

        :param url (str): 完整 URL、仅含 ?key=value 的片段、或无 scheme 的 path?query

        :return Dict: 参数名到单个字符串值；同一键出现多次时取首次出现的值；无 query 时为空 dict
        """
        raw = (url or "").strip()
        parsed = urlparse(raw)
        query = parsed.query
        if not query and "?" in raw:
            query = raw.split("?", 1)[1].split("#", 1)[0]
        qs = parse_qs(query)
        return {k: vals[0] for k, vals in qs.items()}
