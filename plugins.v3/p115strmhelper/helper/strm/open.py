from ...core.u115_open import U115OpenHelper


class OpenStrmHelper:
    """
    基于 Open API 接口的同步方案
    """

    def __init__(self):
        self.open = U115OpenHelper()

    def __del__(self):
        pass

    def full(self):
        """
        全量同步 STRM 文件（暂未实现）

        基于 Open API 接口进行全量 STRM 同步
        """
        pass

    def inc(self):
        """
        增量同步 STRM 文件（暂未实现）

        基于 Open API 接口进行增量 STRM 同步
        """
        pass
