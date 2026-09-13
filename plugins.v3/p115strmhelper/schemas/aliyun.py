from typing import Optional

from pydantic import BaseModel, Field


class AliyunDriveQRCodeData(BaseModel):
    """
    阿里云盘二维码数据
    """

    qrcode: str = Field(..., description="二维码")
    t: str = Field(..., description="时间戳")
    ck: str = Field(..., description="校验值")


class CheckAliyunDriveQRCodeParams(BaseModel):
    """
    检查阿里云盘二维码请求参数
    """

    t: str = Field(..., description="时间戳")
    ck: str = Field(..., description="校验值")


class CheckAliyunDriveQRCodeData(BaseModel):
    """
    阿里云盘二维码状态检查结果
    """

    status: str = Field(..., description="状态")
    msg: str = Field(..., description="消息")
    token: Optional[str] = Field(default=None, description="Token")
