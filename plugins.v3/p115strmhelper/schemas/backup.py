from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..utils.cron import CronUtils


class BackupTargetType(str, Enum):
    """
    备份目标类型
    """

    LOCAL = "local"
    CLOUD_115 = "cloud"


class StrmBackupItem(BaseModel):
    """
    单个备份任务配置
    """

    name: str = Field(..., min_length=1, description="备份任务名称")
    enabled: bool = Field(default=True, description="是否启用")
    source_paths: List[str] = Field(
        default_factory=list, description="要备份的本地目录列表"
    )
    target_type: BackupTargetType = Field(
        default=BackupTargetType.LOCAL, description="备份目标类型"
    )
    local_target_path: Optional[str] = Field(
        default=None, description="本地备份存放目录（target_type=local 时必填）"
    )
    cloud_target_path: Optional[str] = Field(
        default=None, description="115 网盘备份目录（target_type=cloud 时必填）"
    )
    cron: Optional[str] = Field(default=None, description="定时备份 cron 表达式")
    retain_count: int = Field(default=7, ge=1, description="保留备份数量")
    timing_enabled: bool = Field(default=False, description="是否启用定时备份")

    @field_validator("cron", mode="before")
    @classmethod
    def _validate_cron(cls, v: Optional[str]) -> Optional[str]:
        """
        校验并必要时修复 cron 表达式
        """
        if not v:
            return v
        status, msg = CronUtils.validate_cron_expression(v)
        if status:
            return v
        from app.log import logger

        logger.warning(msg)
        fixed = CronUtils.fix_cron_expression(v)
        if CronUtils.is_valid_cron(fixed):
            return fixed
        return CronUtils.get_default_cron()


class BackupHistory(BaseModel):
    """
    备份历史记录
    """

    task_name: str = Field(..., description="备份任务名称")
    filename: str = Field(..., description="备份文件名")
    target_type: BackupTargetType = Field(..., description="备份目标类型")
    target_path: str = Field(..., description="备份文件完整路径或 115 路径")
    file_size: int = Field(default=0, description="备份文件大小（字节）")
    source_paths: List[str] = Field(
        default_factory=list, description="备份的源目录列表"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        description="备份创建时间",
    )
    status: str = Field(default="success", description="备份状态")
    error_msg: Optional[str] = Field(default=None, description="错误信息")
