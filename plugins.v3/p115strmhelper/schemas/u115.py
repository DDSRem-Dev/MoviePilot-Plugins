from typing import Optional

from pydantic import BaseModel, Field


class GetQRCodeParams(BaseModel):
    """
    获取二维码请求参数
    """

    client_type: str = Field(default="alipaymini", description="客户端类型")


class QRCodeData(BaseModel):
    """
    二维码数据
    """

    uid: str = Field(..., description="用户ID")
    time: str = Field(..., description="时间")
    sign: str = Field(..., description="签名")
    qrcode: str = Field(..., description="二维码")
    tips: str = Field(..., description="提示")
    client_type: str = Field(..., description="客户端类型")


class CheckQRCodeParams(BaseModel):
    """
    检查二维码状态请求参数
    """

    uid: str = Field(..., description="用户ID")
    time: str = Field(..., description="时间")
    sign: str = Field(..., description="签名")
    client_type: str = Field(default="alipaymini", description="客户端类型")


class CheckQRCodeData(BaseModel):
    """
    二维码状态检查结果
    """

    status: str = Field(..., description="状态")
    msg: str = Field(..., description="消息")
    cookie: Optional[str] = Field(default=None, description="Cookie")


class UserInfo(BaseModel):
    """
    115 用户信息
    """

    name: Optional[str] = Field(default=None, description="用户名")
    is_vip: Optional[bool] = Field(default=None, description="是否VIP")
    is_forever_vip: Optional[bool] = Field(default=None, description="是否永久VIP")
    vip_expire_date: Optional[str] = Field(default=None, description="VIP过期日期")
    avatar: Optional[str] = Field(default=None, description="头像")


class StorageInfo(BaseModel):
    """
    115 存储空间信息
    """

    total: Optional[str] = Field(default=None, description="总容量")
    used: Optional[str] = Field(default=None, description="已用容量")
    remaining: Optional[str] = Field(default=None, description="剩余容量")


class UserStorageStatusResponse(BaseModel):
    """
    用户存储状态响应
    """

    success: bool = Field(..., description="是否成功")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    user_info: Optional[UserInfo] = Field(default=None, description="用户信息")
    storage_info: Optional[StorageInfo] = Field(default=None, description="存储信息")
