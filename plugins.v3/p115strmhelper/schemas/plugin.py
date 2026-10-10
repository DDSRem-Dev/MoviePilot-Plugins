from typing import List, Optional

from pydantic import BaseModel, Field


class CheckLifeEventStatusPayload(BaseModel):
    """
    生活事件故障检查请求体
    """

    start_time: Optional[int] = Field(
        default=None,
        description="拉取指定时间内的全部数据的开始时间（Unix 时间戳，秒）",
    )


class PluginStatusData(BaseModel):
    """
    插件运行状态数据
    """

    enabled: bool = Field(..., description="是否启用")
    has_client: bool = Field(..., description="是否有客户端")
    running: bool = Field(..., description="是否运行中")


class LifeEventCheckSummary(BaseModel):
    """
    生活事件检查摘要
    """

    plugin_enabled: bool = Field(..., description="插件是否启用")
    client_initialized: bool = Field(..., description="客户端是否初始化")
    monitorlife_initialized: bool = Field(..., description="监控生活是否初始化")
    thread_running: bool = Field(..., description="线程是否运行")
    config_valid: bool = Field(..., description="配置是否有效")


class StrmCleanupRequestIdPayload(BaseModel):
    """
    待确认 STRM 清理批次操作（执行或取消）
    """

    request_id: str = Field(..., min_length=8, description="批次 request_id")


class ShareStrmMissingMediaClearPayload(BaseModel):
    """
    分享 STRM 缺失媒体列表清空或单条删除
    """

    uid: Optional[str] = Field(default=None, description="单条记录 uid")
    clear_all: bool = Field(default=False, description="是否清空全部")


class LifeEventCheckData(BaseModel):
    """
    生活事件检查数据
    """

    success: bool = Field(..., description="是否成功")
    error_messages: List[str] = Field(..., description="错误消息列表")
    debug_info: str = Field(..., description="调试信息")
    summary: LifeEventCheckSummary = Field(..., description="检查摘要")
