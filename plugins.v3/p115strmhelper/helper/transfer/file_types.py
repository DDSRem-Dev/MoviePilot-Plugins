from pathlib import Path
from typing import Optional

from app.sdk.config import settings
from app.schemas import FileItem


class TransferFileTypes:
    """
    旧关联持久任务结算所需的字幕类型判定
    """

    @staticmethod
    def _normalize_ext(ext: Optional[str]) -> Optional[str]:
        """
        归一化扩展名（兼容配置中带点/不带点、大小写差异）

        :param ext (str): 原始扩展名

        :return str: 归一化后的带点小写扩展名，如 ".ass"
        """
        if not ext:
            return None
        return f".{str(ext).strip().lower().lstrip('.')}"

    @staticmethod
    def _is_subtitle_file(fileitem: FileItem) -> bool:
        """
        判断是否为字幕文件

        :param fileitem (FileItem): 文件项
        :return bool: 是否为字幕文件
        """
        ext = TransferFileTypes._normalize_ext(fileitem.extension)
        if not ext and fileitem.path:
            ext = TransferFileTypes._normalize_ext(Path(fileitem.path).suffix)
        if not ext:
            return False
        return ext in {
            TransferFileTypes._normalize_ext(ext_item)
            for ext_item in settings.RMT_SUBEXT
        }
