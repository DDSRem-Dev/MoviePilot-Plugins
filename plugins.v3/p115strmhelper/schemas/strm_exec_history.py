from pydantic import BaseModel, Field


class DeleteStrmSyncHistoryPayload(BaseModel):
    """
    删除 STRM 执行历史单条记录请求体
    """

    key: str = Field(..., description="历史记录 unique")
