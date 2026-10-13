from pathlib import Path
from typing import Optional

from app.chain.storage import StorageChain
from app.sdk.config import settings
from app.schemas import FileItem


class TransferFileTypes:
    """
    保留 V2 的媒体、字幕与音轨后缀判定
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

    @staticmethod
    def _is_audio_file(fileitem: FileItem) -> bool:
        """
        判断是否为音频文件

        :param fileitem (FileItem): 文件项
        :return bool: 是否为音频文件
        """
        ext = TransferFileTypes._normalize_ext(fileitem.extension)
        if not ext and fileitem.path:
            ext = TransferFileTypes._normalize_ext(Path(fileitem.path).suffix)
        if not ext:
            return False
        return ext in {
            TransferFileTypes._normalize_ext(ext_item)
            for ext_item in settings.RMT_AUDIOEXT
        }

    @staticmethod
    def _is_media_file(fileitem: FileItem) -> bool:
        """
        与 TransferChain.__is_media_file 一致的主要媒体文件判定（文件项）

        :param fileitem (FileItem): 文件项
        :return bool: 是否为主要媒体文件
        """
        if fileitem.type == "dir":
            return StorageChain().is_bluray_folder(fileitem)
        ext = TransferFileTypes._normalize_ext(fileitem.extension)
        if not ext and fileitem.path:
            ext = TransferFileTypes._normalize_ext(Path(fileitem.path).suffix)
        if not ext:
            return False
        return ext in {
            TransferFileTypes._normalize_ext(ext_item)
            for ext_item in settings.RMT_MEDIAEXT
        }
