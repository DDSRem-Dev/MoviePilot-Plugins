from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..utils.cron import CronUtils


ShareIterFunction = Literal["share_iter_files", "iter_share_files_with_path"]


class ShareStrmCleanupConfig(BaseModel):
    """
    无效分享 STRM 清理（扫描根目录、定时与删除策略）
    """

    cleanup_paths: List[str] = Field(
        default_factory=list,
        description="参与扫描的本地根目录列表，仅在这些目录下扫描分享 STRM",
    )
    timing_share_strm_cleanup: bool = Field(
        default=False,
        description="是否按 cron 定时执行清理扫描",
    )
    cron_share_strm_cleanup: Optional[str] = Field(
        default="0 */12 * * *",
        description="定时清理的 cron 表达式",
    )
    delete_mode: Literal["immediate", "plugin_ui"] = Field(
        default="plugin_ui",
        description="immediate=扫到后立即删除；plugin_ui=先入队待插件内确认",
    )
    remove_related_mediainfo: bool = Field(
        default=True,
        description="是否连带删除 nfo/jpg 等关联文件",
    )
    remove_empty_parent_dirs: bool = Field(
        default=True,
        description="是否清理空父目录（strm 模式）",
    )
    remove_stale_transfer_history: bool = Field(
        default=False,
        description="删除 STRM 时是否清理匹配的 MP 整理记录",
    )
    record_missing_media_from_history: bool = Field(
        default=True,
        description="是否从整理记录解析并写入「缺失媒体」列表",
    )

    @field_validator("cron_share_strm_cleanup", mode="before")
    @classmethod
    def _validate_cron_share_strm_cleanup(cls, v: Optional[str]) -> Optional[str]:
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
            logger.info(f"自动修复 cron_share_strm_cleanup: '{v}' -> '{fixed}'")
            return fixed
        logger.error(
            f"无法修复无效的 cron_share_strm_cleanup: '{v}'，"
            f"恢复默认值 '{CronUtils.get_default_cron()}'"
        )
        return CronUtils.get_default_cron()


class ShareSaveParent(BaseModel):
    """
    分享转存目录信息
    """

    path: str = Field(..., description="路径")
    id: int | str = Field(..., description="目录ID")


class ShareResponseData(BaseModel):
    """
    分享转存返回信息
    """

    media_info: Optional[Dict] = Field(default=None, description="媒体信息")
    save_parent: ShareSaveParent = Field(..., description="保存父目录")


class ShareApiData(BaseModel):
    """
    分享转存 API 返回数据
    """

    code: int = Field(default=0, description="响应码")
    msg: str = Field(default="success", description="响应消息")
    data: Optional[ShareResponseData] = Field(default=None, description="响应数据")
    timestamp: Optional[datetime] = Field(default=None, description="时间戳")


class ShareInteractiveGenStrmConfig(BaseModel):
    """
    分享交互生成 STRM 专用配置
    """

    min_file_size: Optional[int] = Field(
        default=None, ge=0, description="分享生成最小文件大小"
    )
    auto_download_mediainfo: bool = Field(
        default=False, description="自动下载网盘元数据"
    )
    local_path: Optional[str] = Field(default=None, description="本地生成目录")
    moviepilot_transfer: bool = Field(default=False, description="交由 MoviePilot 整理")
    moviepilot_transfer_download_rmt_audio_sub: bool = Field(
        default=False,
        description="MP 整理时是否下载 MoviePilot 设定中 RMT 音轨与字幕后缀文件",
    )
    iter_function: ShareIterFunction = Field(
        default="iter_share_files_with_path", description="分享文件迭代函数"
    )
    speed_mode: Literal[0, 1, 2, 3] = Field(default=3, description="运行速度模式")

    @model_validator(mode="after")
    def enforce_moviepilot_constraints(self):
        """
        当 moviepilot_transfer 为 True 时，强制关闭自动下载网盘元数据
        """
        if not self.moviepilot_transfer:
            self.moviepilot_transfer_download_rmt_audio_sub = False
        if self.moviepilot_transfer:
            self.auto_download_mediainfo = False
        if self.iter_function == "share_iter_files":
            self.auto_download_mediainfo = False
            self.moviepilot_transfer_download_rmt_audio_sub = False
        return self


class ShareStrmConfig(BaseModel):
    """
    分享 STRM 生成配置
    """

    comment: Optional[str] = Field(default=None, description="备注")
    enabled: bool = Field(default=True, description="是否启用")
    share_link: Optional[str] = Field(default=None, description="分享链接")
    share_code: Optional[str] = Field(default=None, description="分享码")
    share_receive: Optional[str] = Field(default=None, description="分享密码")
    share_path: Optional[str] = Field(default=None, description="分享路径")
    local_path: Optional[str] = Field(default=None, description="本地路径")
    min_file_size: Optional[int] = Field(
        default=None, description="分享生成最小文件大小"
    )
    moviepilot_transfer: bool = Field(default=False, description="交由 MoviePilot 整理")
    moviepilot_transfer_download_rmt_audio_sub: bool = Field(
        default=False,
        description="MP 整理时是否下载 MoviePilot 设定中 RMT 音轨与字幕后缀文件",
    )
    auto_download_mediainfo: bool = Field(
        default=False, description="自动下载网盘元数据"
    )
    media_server_refresh: bool = Field(default=False, description="刷新媒体服务器")
    scrape_metadata: bool = Field(default=False, description="是否刮削元数据")
    iter_function: ShareIterFunction = Field(
        default="iter_share_files_with_path", description="分享文件迭代函数"
    )
    speed_mode: Literal[0, 1, 2, 3] = Field(default=3, description="运行速度模式")

    @model_validator(mode="after")
    def enforce_moviepilot_constraints(self):
        """
        当 moviepilot_transfer 为 True 时，强制关闭其他相关选项
        """
        if not self.moviepilot_transfer:
            self.moviepilot_transfer_download_rmt_audio_sub = False
        if self.moviepilot_transfer:
            self.auto_download_mediainfo = False
            self.media_server_refresh = False
            self.scrape_metadata = False
        if self.iter_function == "share_iter_files":
            self.auto_download_mediainfo = False
            self.moviepilot_transfer_download_rmt_audio_sub = False
        return self
