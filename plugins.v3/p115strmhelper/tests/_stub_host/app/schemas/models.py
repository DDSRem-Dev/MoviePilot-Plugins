"""
Schema 替身。

模型用 pydantic（若可用）定义，保证 ``model_dump`` / ``model_validate`` 等
插件实际调用的方法存在；pydantic 不可用时退化为宽松的鸭子类型对象。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - 取决于运行环境
    from pydantic import BaseModel, ConfigDict, Field

    _PYDANTIC = True
except Exception:  # pragma: no cover
    _PYDANTIC = False
    BaseModel = object  # type: ignore[assignment,misc]

    def Field(default=None, **_kwargs):  # type: ignore[no-redef]
        return default

    ConfigDict = dict  # type: ignore[assignment]


class FileItem(BaseModel):  # type: ignore[misc,valid-type]
    """文件或目录条目。"""

    storage: Optional[str] = "u115"
    path: Optional[str] = None
    name: Optional[str] = None
    basename: Optional[str] = None
    extension: Optional[str] = None
    type: Optional[str] = "file"
    size: Optional[int] = 0
    modify_time: Optional[float] = None
    children: Optional[List[Any]] = None
    fileid: Optional[str] = None
    parent_fileid: Optional[str] = None
    pickcode: Optional[str] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class TransferInfo(BaseModel):  # type: ignore[misc,valid-type]
    """整理结果。"""

    success: bool = False
    message: Optional[str] = None
    fileitem: Optional[FileItem] = None
    target_item: Optional[FileItem] = None
    target_diritem: Optional[FileItem] = None
    transfer_type: Optional[str] = None
    file_list: Optional[List[str]] = None
    file_list_new: Optional[List[str]] = None
    fail_list: Optional[List[str]] = None
    need_scrape: Optional[bool] = False
    need_notify: Optional[bool] = False

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class TransferTask(BaseModel):  # type: ignore[misc,valid-type]
    """整理任务（宿主别名 MPTransferTask 用）。"""

    fileitem: Optional[Any] = None
    meta: Optional[Any] = None
    mediainfo: Optional[Any] = None
    media_source: Optional[Any] = None
    media_id: Optional[str] = None
    mtype: Optional[Any] = None
    target_directory: Optional[Any] = None
    target_storage: Optional[str] = None
    target_path: Optional[Any] = None
    transfer_type: Optional[str] = None
    scrape: Optional[bool] = None
    library_type_folder: Optional[bool] = None
    library_category_folder: Optional[bool] = None
    episodes_info: Optional[Any] = None
    username: Optional[str] = None
    downloader: Optional[str] = None
    download_hash: Optional[str] = None
    download_history: Optional[Any] = None
    manual: Optional[bool] = False
    background: Optional[bool] = False
    preview: Optional[bool] = False

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class MediaInfo(BaseModel):  # type: ignore[misc,valid-type]
    """媒体信息。"""

    title: Optional[str] = None
    year: Optional[str] = None
    type: Optional[Any] = None
    tmdb_id: Optional[int] = None
    media_source: Optional[Any] = None
    media_id: Optional[str] = None
    season: Optional[int] = None
    category: Optional[str] = None
    episode_group: Optional[str] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class RefreshMediaItem(BaseModel):  # type: ignore[misc,valid-type]
    """刷新媒体项。"""

    title: Optional[str] = None
    year: Optional[str] = None
    type: Optional[Any] = None
    category: Optional[str] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class ServiceInfo(BaseModel):  # type: ignore[misc,valid-type]
    """服务信息。"""

    name: Optional[str] = None
    url: Optional[str] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class TransferRenameBuildEventData(BaseModel):  # type: ignore[misc,valid-type]
    """重命名构建事件数据。"""

    template_string: Optional[str] = None
    rename_dict: Dict[str, Any] = Field(default_factory=dict)
    meta: Optional[Any] = None
    mediainfo: Optional[Any] = None
    file_ext: Optional[str] = None
    episodes_info: Optional[Any] = None
    source_path: Optional[str] = None
    source_item: Optional[Any] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class StorageOperSelectionEventData(BaseModel):  # type: ignore[misc,valid-type]
    """存储操作选择事件数据。"""

    storage: Optional[str] = None
    storage_oper: Optional[Any] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class TransferInterceptEventData(BaseModel):  # type: ignore[misc,valid-type]
    """整理拦截事件数据。"""

    fileitem: Optional[Any] = None
    meta: Optional[Any] = None
    mediainfo: Optional[Any] = None
    target_path: Optional[Any] = None
    intercept: Optional[bool] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class TransferOverwriteCheckEventData(BaseModel):  # type: ignore[misc,valid-type]
    """整理覆盖检查事件数据。"""

    fileitem: Optional[Any] = None
    target_item: Optional[Any] = None
    overwrite: Optional[bool] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


class WebhookEventInfo(BaseModel):  # type: ignore[misc,valid-type]
    """媒体服务器 Webhook 事件。"""

    event: Optional[str] = None
    item_type: Optional[str] = None
    item_name: Optional[str] = None
    item_path: Optional[str] = None

    if _PYDANTIC:
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


@dataclass
class _Message:
    """通知消息替身（V3 名 Message；旧名 Notification）。"""

    channel: Optional[Any] = None
    source: Optional[str] = None
    mtype: Optional[Any] = None
    ctype: Optional[Any] = None
    title: Optional[str] = None
    text: Optional[str] = None
    image: Optional[str] = None
    link: Optional[str] = None
    userid: Optional[Any] = None
    username: Optional[Any] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    buttons: Optional[List[List[dict]]] = None
    save_history: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs):
        known = {f.name for f in self.__dataclass_fields__.values()} - {"extra"}
        extra = {k: v for k, v in kwargs.items() if k not in known}
        for key in known:
            if key in kwargs:
                object.__setattr__(self, key, kwargs[key])
        object.__setattr__(self, "extra", extra)

    def model_dump(self, **_kwargs) -> Dict[str, Any]:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "extra"}
        data.update(self.extra)
        return data

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


Notification = _Message


class _NotificationSwitchConf:
    """通知开关配置替身。"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class ChannelCapabilityManager:
    """通知渠道能力管理器替身。"""

    @staticmethod
    def supports_capability(*_args, **_kwargs) -> bool:
        return False
