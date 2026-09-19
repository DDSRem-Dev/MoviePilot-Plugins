__all__ = ["PathUtils", "PathRemoveUtils"]


from os import name as os_name
from pathlib import Path, PurePosixPath
from shutil import rmtree
from typing import List, Optional, Tuple

from app.log import logger
from app.utils.system import SystemUtils


class PathUtils:
    """
    路径匹配
    """

    @staticmethod
    def sanitize_path_parts(rel_path: Path) -> Path:
        """
        将相对路径各分量中的非法文件名字符替换为下划线（仅 Windows 生效，其他平台直接返回原路径）

        :param rel_path (Path): 待处理的相对路径

        :return Path: 处理后的相对路径
        """
        if os_name != "nt":
            return rel_path
        illegal_chars = '<>"|?*'
        parts = list(rel_path.parts)
        if not parts:
            return rel_path
        sanitized = []
        for part in parts:
            part = part.replace(":", "：")
            for char in illegal_chars:
                part = part.replace(char, "_")
            sanitized.append(part)
        result = Path(sanitized[0])
        for part in sanitized[1:]:
            result = result / part
        return result

    @staticmethod
    def has_prefix(full_path, prefix_path) -> bool:
        """
        判断路径是否包含

        :param full_path (str): 完整路径
        :param prefix_path (str): 匹配路径

        :return bool: 是否包含
        """
        if not full_path or not prefix_path:
            return False
        full = Path(full_path).parts
        prefix = Path(prefix_path).parts

        if len(prefix) > len(full):
            return False

        return full[: len(prefix)] == prefix

    @staticmethod
    def get_run_transfer_path(paths, transfer_path) -> bool:
        """
        判断路径是否为整理路径

        :param paths (str): 换行分隔的整理路径列表
        :param transfer_path (str): 待判断的转移路径

        :return bool: 是否为整理路径
        """
        transfer_paths = paths.split("\n")
        for path in transfer_paths:
            if not path:
                continue
            if PathUtils.has_prefix(transfer_path, path):
                return True
        return False

    @staticmethod
    def get_scrape_metadata_exclude_path(paths, scrape_path) -> bool:
        """
        检查目录是否在排除目录内

        :param paths (str): 换行分隔的排除路径列表
        :param scrape_path (str): 待检查的刮削路径

        :return bool: 是否在排除目录内
        """
        exclude_path = paths.split("\n")
        for path in exclude_path:
            if not path:
                continue
            if PathUtils.has_prefix(scrape_path, path):
                return True
        return False

    @staticmethod
    def get_media_path(paths, media_path) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        获取媒体目录路径

        :param paths (str): 换行分隔的媒体目录映射
        :param media_path (str): 待匹配的媒体路径

        :return Tuple: (是否匹配, 媒体服务器路径, 网盘路径)
        """
        media_paths = paths.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 2)
            if PathUtils.has_prefix(media_path, parts[1]):
                return True, parts[0], parts[1]
        return False, None, None

    @staticmethod
    def get_p115_strm_path(paths, media_path) -> Tuple[bool, Optional[str]]:
        """
        匹配全量目录，自动生成新的 paths

        :param paths (str): 换行分隔的全量目录映射
        :param media_path (str): 待匹配的媒体路径

        :return Tuple: (是否匹配, 生成的路径字符串)
        """
        media_paths = paths.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 2)
            if PathUtils.has_prefix(media_path, parts[1]):
                local_path = Path(parts[0]) / Path(media_path).relative_to(parts[1])
                final_paths = f"{local_path}#{media_path}"
                return True, final_paths
        return False, None

    @staticmethod
    def get_p115_media_path(
        media_path: str, p115_library_path: str
    ) -> Tuple[bool, Optional[List[str]]]:
        """
        获取 115 网盘媒体目录路径

        :param media_path (str): 媒体路径
        :param p115_library_path (str): 115 网盘媒体库路径映射（格式：媒体服务器STRM路径#MoviePilot路径# 115 网盘路径）

        :return Tuple: (是否匹配, 路径部分列表)
        """
        if not p115_library_path:
            return False, None
        media_paths = p115_library_path.split("\n")
        for path in media_paths:
            if not path:
                continue
            parts = path.split("#", 2)
            if PathUtils.has_prefix(media_path, parts[0]):
                return True, parts
        return False, None

    @staticmethod
    def get_media_file_paths_with_suffix(
        file_path: str, media_suffix: Optional[str]
    ) -> Tuple[str, str]:
        """
        根据媒体库文件路径和真实媒体后缀还原网盘媒体路径

        :param file_path (str): 媒体库文件路径
        :param media_suffix (str): 真实媒体后缀

        :return Tuple: 正常大小写路径和大小写切换路径
        """
        normalized_path = file_path.replace("\\", "/")
        path = PurePosixPath(normalized_path)
        if not path.suffix or not media_suffix:
            return normalized_path, normalized_path

        suffix = media_suffix.lstrip(".")
        if not suffix:
            return normalized_path, normalized_path

        stem = path.stem
        suffix_marker = f".{suffix}"
        if stem.lower().endswith(suffix_marker.lower()):
            base_stem = stem[: -(len(suffix) + 1)]
            primary_suffix = stem[-len(suffix) :]
        else:
            base_stem = stem
            primary_suffix = suffix

        media_path = str(path.parent / f"{base_stem}.{primary_suffix}")
        if primary_suffix.isupper():
            final_suffix = primary_suffix.lower()
        elif primary_suffix.islower():
            final_suffix = primary_suffix.upper()
        else:
            final_suffix = primary_suffix

        media_path_final = (
            str(path.parent / f"{base_stem}.{final_suffix}")
            if final_suffix != primary_suffix
            else media_path
        )
        return media_path, media_path_final


class PathRemoveUtils:
    """
    目录删除工具
    """

    @staticmethod
    def remove_parent_dir(
        file_path: Path,
        mode: str | list = "all",
        func_type: str = None,
    ):
        """
        删除父目录

        :param file_path (Path): 文件夹路径
        :param mode (str): 删除模式，支持全部匹配（\"all\"）、文件后缀匹配（list）和混合模式（\"mixed\"，
                     第一层以 \"all\" 判断空目录，上层以 [\"strm\"] 判断）
        :param func_type (str): 日志输出函数名称
        """
        # 判断当前媒体父路径下是否有媒体文件，如有则无需遍历父级
        if mode in ("all", "mixed"):
            func_bool = any(file_path.parent.iterdir())
        else:
            func_bool = SystemUtils.exits_files(
                directory=file_path.parent, extensions=mode
            )
        if not func_bool:
            # 判断父目录是否为空, 为空则删除
            i = 0
            for parent_path in file_path.parents:
                i += 1
                if i > 3:
                    break
                if str(parent_path.parent) != str(file_path.root):
                    # 父目录非根目录，才删除父目录
                    if mode == "all" or (mode == "mixed" and i == 1):
                        func_bool = any(parent_path.iterdir())
                    elif mode == "mixed":
                        # 混合模式：上层以 ["strm"] 判断，允许穿透含 sidecar 的上级目录
                        func_bool = SystemUtils.exits_files(
                            directory=parent_path, extensions=["strm"]
                        )
                    else:
                        func_bool = SystemUtils.exits_files(
                            directory=parent_path, extensions=mode
                        )
                    if not func_bool:
                        # 当前路径下没有媒体文件则删除
                        rmtree(parent_path)
                        logger.warn(f"{func_type}本地空目录 {parent_path} 已删除")

    @staticmethod
    def clean_related_files(file_path: Path, func_type: str = None):
        """
        根据一个文件的路径，清理同一文件夹下文件名包含此文件名的其他文件

        对于 .strm 后缀文件进行保护，不做删除操作

        :param file_path (Path): 基准文件路径
        :param func_type (str): 日志输出函数名称
        """
        directory = file_path.parent
        file_stem = file_path.stem
        for item_to_check in directory.iterdir():
            if (
                item_to_check.is_file()
                and item_to_check != file_path
                and file_stem in item_to_check.stem
                and item_to_check.suffix.lower() != ".strm"
            ):
                logger.warn(f"{func_type}删除文件 {item_to_check}")
                item_to_check.unlink(missing_ok=True)
