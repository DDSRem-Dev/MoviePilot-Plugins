from dataclasses import dataclass
from typing import Optional


@dataclass
class UploadResult:
    """
    上传结果数据类
    """

    success: bool
    target_name: str
    file_size: int
    elapsed_time: Optional[float] = None
    error_msg: Optional[str] = None
