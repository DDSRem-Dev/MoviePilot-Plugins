__all__ = ["TimeUtils"]


from datetime import datetime
from email.utils import formatdate
from time import time


class TimeUtils:
    """
    时间 工具类
    """

    @staticmethod
    def timestamp2isoformat(ts: None | float | datetime = None, /) -> str:
        """
        将时间戳或 datetime 对象转换为 ISO 8601 格式字符串

        :param ts (float): Unix 时间戳（秒）、datetime 对象或 None（默认使用当前时间）

        :return str: 带时区信息的 ISO 8601 格式字符串
        """
        if ts is None:
            dt = datetime.now()
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts)
        return dt.astimezone().isoformat()

    @staticmethod
    def timestamp2gmtformat(ts: None | float | datetime = None, /) -> str:
        """
        将时间戳或 datetime 对象转换为 GMT 格式的 HTTP 日期字符串

        :param ts (float): Unix 时间戳（秒）、datetime 对象或 None（默认使用当前时间）

        :return str: GMT 格式的 HTTP 日期字符串（如 "Mon, 01 Jan 2024 00:00:00 GMT"）
        """
        if ts is None:
            ts = time()
        elif isinstance(ts, datetime):
            ts = ts.timestamp()
        return formatdate(ts, usegmt=True)
