from pathlib import Path
from typing import Optional

from app.chain.storage import StorageChain
from app.log import logger
from app.schemas import FileItem


def find_subdirectory_by_name(
    chain: StorageChain,
    parent: FileItem,
    name: str,
) -> Optional[FileItem]:
    """
    在已定位的父目录下列举子项，按名称匹配第一个目录类型项

    :param chain (StorageChain): 储存链实例
    :param parent (FileItem): 父目录 FileItem
    :param name (str): 子目录名称（与 FileItem.name 一致比较）

    :return FileItem: 匹配的目录 FileItem；无匹配或列举结果为空时返回 None

    :raises Exception: 透传 ``list_files`` 的异常，由调用方记录日志
    """
    entries = chain.list_files(parent) or []
    for entry in entries:
        if entry.type == "dir" and entry.name == name:
            return entry
    return None


def find_file_by_name(
    chain: StorageChain,
    parent: FileItem,
    name: str,
) -> Optional[FileItem]:
    """
    在已定位的父目录下列举子项，按名称匹配第一个文件类型项

    :param chain (StorageChain): 储存链实例
    :param parent (FileItem): 父目录 FileItem
    :param name (str): 文件名（与 FileItem.name 一致比较）

    :return FileItem: 匹配的文件 FileItem；无匹配或列举结果为空时返回 None

    :raises Exception: 透传 ``list_files`` 的异常，由调用方记录日志
    """
    entries = chain.list_files(parent) or []
    for entry in entries:
        if entry.type == "file" and entry.name == name:
            return entry
    return None


def resolve_directory_via_parent_list(
    chain: StorageChain,
    storage: str,
    target_dir: Path,
    *,
    log_label: str = "【网盘整理】",
) -> Optional[FileItem]:
    """
    不经目标路径全量 ``get_file_item``，仅解析其父目录后在子项中按名匹配目标文件夹

    :param chain (StorageChain): 储存链实例
    :param storage (str): 储存名称（如 CloudDrive 储存名）
    :param target_dir (Path): 目标目录路径（会先规范为目录 posix）
    :param log_label (str): 日志前缀

    :return FileItem: 目标目录 FileItem；无法解析或目标为储存根 ``/`` 时返回 None
    """
    posix = target_dir.as_posix().rstrip("/") or "/"
    if posix == "/":
        logger.error(
            "%s 储存「%s」目标目录不能为储存根路径: %s",
            log_label,
            storage,
            target_dir,
        )
        return None

    parent_path = Path(posix).parent
    child_name = Path(posix).name
    if not child_name:
        logger.error(
            "%s 储存「%s」目标路径无效（无法得到子目录名）: %s",
            log_label,
            storage,
            target_dir,
        )
        return None

    parent_posix = parent_path.as_posix().rstrip("/") or "/"
    if parent_posix == "/":
        parent_item: FileItem = FileItem(storage=storage, path="/")
    else:
        parent_item = chain.get_file_item(storage=storage, path=parent_path)
        if not parent_item:
            logger.warning(
                "%s 储存「%s」无法直接解析父目录，尝试回退遍历解析: %s",
                log_label,
                storage,
                parent_path,
            )
            parent_item = resolve_directory_via_parent_list(
                chain,
                storage,
                parent_path,
                log_label=log_label,
            )
            if not parent_item:
                logger.error(
                    "%s 储存「%s」父目录回退遍历失败，跳过文件夹遍历: %s",
                    log_label,
                    storage,
                    parent_path,
                )
                return None

    try:
        child = find_subdirectory_by_name(chain, parent_item, child_name)
    except Exception as e:
        logger.error(
            "%s list_files 失败: %s %s",
            log_label,
            parent_item.path,
            e,
            exc_info=True,
        )
        return None

    if child is None:
        logger.error(
            "%s 储存「%s」在上级目录中未找到子目录: name=%s parent=%s（目标 %s）",
            log_label,
            storage,
            child_name,
            parent_item.path,
            posix,
        )
        return None

    return child


def resolve_file_via_parent_list(
    chain: StorageChain,
    storage: str,
    target_file: Path,
    *,
    log_label: str = "【网盘整理】",
) -> Optional[FileItem]:
    """
    不经目标文件全量 ``get_file_item``，仅解析其父目录后在子项中按名匹配目标文件

    :param chain (StorageChain): 储存链实例
    :param storage (str): 储存名称（如 CloudDrive 储存名）
    :param target_file (Path): 目标文件路径（会先规范 posix，去掉末尾 ``/``）
    :param log_label (str): 日志前缀

    :return FileItem: 目标文件 FileItem；无法解析时返回 None
    """
    posix = target_file.as_posix().rstrip("/")
    child_name = Path(posix).name
    if not posix or posix == "/" or not child_name:
        logger.error(
            "%s 储存「%s」目标文件路径无效（无法得到文件名）: %s",
            log_label,
            storage,
            target_file,
        )
        return None

    parent_path = Path(posix).parent
    parent_posix = parent_path.as_posix().rstrip("/") or "/"
    if parent_posix == "/":
        parent_item: FileItem = FileItem(storage=storage, path="/")
    else:
        parent_item = chain.get_file_item(storage=storage, path=parent_path)
        if not parent_item:
            logger.warning(
                "%s 储存「%s」无法直接解析父目录，尝试回退遍历解析: %s",
                log_label,
                storage,
                parent_path,
            )
            parent_item = resolve_directory_via_parent_list(
                chain,
                storage,
                parent_path,
                log_label=log_label,
            )
            if not parent_item:
                logger.error(
                    "%s 储存「%s」父目录回退遍历失败，跳过单文件整理: %s",
                    log_label,
                    storage,
                    parent_path,
                )
                return None

    try:
        child = find_file_by_name(chain, parent_item, child_name)
    except Exception as e:
        logger.error(
            "%s list_files 失败: %s %s",
            log_label,
            parent_item.path,
            e,
            exc_info=True,
        )
        return None

    if child is None:
        logger.error(
            "%s 储存「%s」在上级目录中未找到子文件: name=%s parent=%s（目标 %s）",
            log_label,
            storage,
            child_name,
            parent_item.path,
            posix,
        )
        return None

    return child
