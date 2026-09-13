"""
``app.db.models.transferhistory`` 替身。

插件只读取下列字段：``id`` / ``src`` / ``dest`` / ``dest_storage`` / ``mode`` /
``image`` / ``media_id`` / ``media_source`` / ``download_hash`` 等，因此替身用
宽松属性容器实现，未显式声明的字段返回 ``None`` 而不是 ``AttributeError``。
"""

from typing import Any, Optional

__all__ = ["TransferHistory", "DownloadHistory", "DownloadFiles"]


class _ModelBase:
    """宽松模型基类：任意字段可读写，未设置时返回 ``None``。"""

    #: 已知字段及其默认值（供 ``model_dump`` 排序输出）
    _fields: tuple = ()

    def __init__(self, **kwargs: Any) -> None:
        for field_name in self._fields:
            setattr(self, field_name, kwargs.pop(field_name, None))
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return None

    def model_dump(self, **_kwargs) -> dict:
        return {
            key: value
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }

    dict = model_dump

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"{type(self).__name__}(id={identifier!r})"


class TransferHistory(_ModelBase):
    """整理历史记录替身。"""

    _fields = (
        "id",
        "src",
        "src_storage",
        "dest",
        "dest_storage",
        "mode",
        "type",
        "category",
        "title",
        "year",
        "season",
        "episode",
        "image",
        "media_id",
        "media_source",
        "download_hash",
        "downloader",
        "status",
        "errmsg",
        "date",
        "transfer_task_id",
    )


class DownloadHistory(_ModelBase):
    """下载历史记录替身。"""

    _fields = (
        "id",
        "path",
        "downloader",
        "download_hash",
        "torrent_name",
        "title",
        "year",
        "season",
        "media_id",
        "media_source",
        "status",
        "date",
    )


class DownloadFiles(_ModelBase):
    """下载文件记录替身。"""

    _fields = (
        "id",
        "download_hash",
        "fullpath",
        "savepath",
        "state",
        "size",
    )
