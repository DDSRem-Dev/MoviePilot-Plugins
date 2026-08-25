from enum import IntEnum
from pathlib import Path, PurePosixPath
from queue import Empty, Queue
from threading import RLock, Thread
from time import monotonic, sleep
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Set, Tuple
from uuid import uuid4

from cryptography.hazmat.primitives import hashes
from grpc import Call, RpcError, StatusCode
from httpx import RequestError
from httpx import stream as httpx_stream

from app.modules.filemanager.storages import transfer_process
from app.schemas import FileItem, StorageUsage
from app.schemas.exception import StorageQueryError
from app.sdk.config import global_vars, settings
from app.sdk.logging import logger

from clouddrive2_client import CloudDriveClient


# 115/CD2：移动或「从含撇号的旧名改到其它名」时不稳定；先脱敏的是**源侧末段名/路径**
# 最终目标名 `new_name` 仍可含 ASCII 撇号（改为带撇号的展示名通常可用），本模块不禁止
APOSTROPHE_ESCAPE = "[Jw==]"


def _build_download_path(fileitem: FileItem, base_path: Path) -> Optional[Path]:
    """
    构造限制在目标目录内的下载路径
    """
    safe_name = PurePosixPath(str(fileitem.name or "").replace("\\", "/")).name
    if safe_name in ("", ".", ".."):
        return None
    local_path = base_path / safe_name
    try:
        local_path.resolve().relative_to(base_path.resolve())
    except ValueError:
        return None
    return local_path


def escape_apostrophe_in_name(name: str) -> str:
    """
    将名称中的 ASCII 单引号替换为占位串，便于移动前或两步重命名第一步脱敏（针对**源名**）

    :param name (str): 原始文件名或目录名

    :return str: 替换后的名称
    """

    return name.replace("'", APOSTROPHE_ESCAPE)


def _posix_join_parent_name(parent: str, name: str) -> str:
    """
    将父目录路径与末段名称拼接为 POSIX 路径（根目录无双斜杠）

    :param parent (str): 父目录绝对路径
    :param name (str): 文件或目录名

    :return str: 完整路径
    """

    base = (parent or "/").rstrip("/") or "/"
    if base == "/":
        return f"/{name}"
    return f"{base}/{name}"


class UploadStatus(IntEnum):
    """
    上传状态枚举

    Attributes:
        FINISH: 完成
        ERROR: 错误
        FATAL_ERROR: 致命错误
    """

    FINISH = 5
    ERROR = 9
    FATAL_ERROR = 10


class HashType(IntEnum):
    """
    Hash 类型

    Attributes:
        MD5: MD5 哈希
        SHA1: SHA1 哈希
        PIKPAK_SHA1: PikPak SHA1 哈希
    """

    MD5 = 1
    SHA1 = 2
    PIKPAK_SHA1 = 3


def _cloudfile_to_fileitem(
    f: Any, disk_name: str, parent_fileid: Optional[str] = None
) -> FileItem:
    """
    将 proto CloudDriveFile 转为 FileItem

    :param f (Any): proto CloudDriveFile
    :param disk_name (str): 磁盘名称
    :param parent_fileid (str): 父文件ID

    :return FileItem: 转换后的文件项
    """
    path_str = f.fullPathName or ""
    if f.isDirectory and path_str and not path_str.endswith("/"):
        path_str = path_str + "/"
    name = f.name or ""
    stem = Path(name).stem
    suffix = Path(name).suffix
    extension = suffix[1:] if suffix and not f.isDirectory else None
    modify_time = None
    if f.writeTime and f.writeTime.seconds:
        modify_time = f.writeTime.seconds
    return FileItem(
        storage=disk_name,
        fileid=f.id or "",
        parent_fileid=parent_fileid,
        name=name,
        basename=stem,
        extension=extension,
        type="dir" if f.isDirectory else "file",
        path=path_str,
        size=f.size if not f.isDirectory else None,
        modify_time=modify_time,
    )


class CloudDriveApi:
    """
    CloudDrive 储存操作实现
    """

    def __init__(
        self,
        client: CloudDriveClient,
        disk_name: str,
        download_base: Optional[str] = None,
        upload_mode: Literal["remote_upload", "direct_write"] = "direct_write",
    ) -> None:
        """
        初始化 CloudDrive API 封装

        :param client (CloudDriveClient): 已认证的 CloudDrive 客户端
        :param disk_name (str): 储存名称，与注册的 storage 一致
        :param download_base (str): 下载 URL 基地址
        :param upload_mode (str): 上传模式
        """
        self.client = client
        self._disk_name = disk_name
        self._download_base = (download_base or "http://127.0.0.1:19798").rstrip("/")
        self._upload_mode = upload_mode
        self.transtype = {"move": "移动", "copy": "复制"}
        self._folder_lock = RLock()

    def list(self, fileitem: FileItem) -> Optional[List[FileItem]]:
        """
        列出目录下文件，或单文件则返回包含该文件的列表

        :param fileitem (FileItem): 目录或文件项

        :return List: FileItem 列表
        """
        if fileitem.type == "file":
            item = self.get_item(Path(fileitem.path))
            return [item] if item else []
        path = (fileitem.path or "/").rstrip("/") or "/"
        try:
            sub = self.client.get_sub_files(path, force_refresh=True)
            return [
                _cloudfile_to_fileitem(
                    f, self._disk_name, parent_fileid=fileitem.fileid
                )
                for f in sub
            ]
        except Exception as e:
            logger.error("【CloudDrive】列出目录失败 %s: %s", path, e)
            return None

    def iter_files(self, fileitem: FileItem) -> Optional[List[FileItem]]:
        """
        递归遍历目录，返回扁平文件列表

        :param fileitem (FileItem): 目录或文件项

        :return List: 所有文件项列表，失败返回 None
        """
        if fileitem.type == "file":
            item = self.get_item(Path(fileitem.path))
            return [item] if item else []
        items: List[FileItem] = []
        try:
            children = self.list(fileitem)
            if children is None:
                return None
            for child in children:
                if child.type == "dir":
                    sub_list = self.iter_files(child)
                    if sub_list is None:
                        return None
                    items.extend(sub_list)
                else:
                    items.append(child)
            return items
        except Exception as e:
            logger.error("【CloudDrive】递归列表失败 %s: %s", fileitem.path, e)
            return None

    def get_item(self, path: Path) -> Optional[FileItem]:
        """
        按路径获取文件或目录项

        :param path (Path): 路径

        :return FileItem: 文件项，未找到返回 None
        """
        try:
            return self._query_item(path)
        except Exception as e:
            logger.error("【CloudDrive】查询文件失败 %s: %s", path.as_posix(), e)
            return None

    def get_item_strict(self, path: Path) -> Optional[FileItem]:
        """
        严格获取文件或目录，无法确认状态时抛出存储查询异常

        :param path (Path): 文件或目录路径

        :return FileItem: 文件项，确认不存在时返回 None

        :raises StorageQueryError: RPC 或接口异常导致无法确认文件状态
        """
        try:
            return self._query_item(path)
        except StorageQueryError:
            raise
        except Exception as e:
            raise StorageQueryError(
                f"【CloudDrive】查询文件信息失败: {path} - {e}"
            ) from e

    def _query_item(self, path: Path) -> Optional[FileItem]:
        """
        查询远端文件项

        :param path (Path): 文件或目录路径

        :return FileItem: 查询到的文件项，确认不存在时返回 None
        """
        path_str = path.as_posix()
        if not path_str or path_str == ".":
            path_str = "/"
        try:
            cloud_file = self.client.find_file_by_path(path_str)
            logger.info("【CloudDrive】查找文件成功 %s: %s", path_str, cloud_file)
        except RpcError as e:
            if not isinstance(e, Call) or e.code() != StatusCode.NOT_FOUND:
                raise
            try:
                cloud_file = self.client.get_file_detail_properties(path_str)
                logger.info(
                    "【CloudDrive】获取文件详情成功 %s: %s",
                    path_str,
                    cloud_file,
                )
            except RpcError as detail_error:
                if (
                    isinstance(detail_error, Call)
                    and detail_error.code() == StatusCode.NOT_FOUND
                ):
                    return None
                raise
        if not cloud_file or not cloud_file.id:
            return None
        return _cloudfile_to_fileitem(cloud_file, self._disk_name)

    def get_parent(self, fileitem: FileItem) -> Optional[FileItem]:
        """
        获取父目录项

        :param fileitem (FileItem): 文件项

        :return FileItem: 父目录项，如果不存在则返回 None
        """
        parent_path = Path(fileitem.path).parent
        if parent_path.as_posix() == "." or parent_path.as_posix() == "":
            parent_path = Path("/")
        return self.get_item(parent_path)

    def create_folder(self, fileitem: FileItem, name: str) -> Optional[FileItem]:
        """
        在指定目录下创建文件夹

        :param fileitem (FileItem): 父目录项
        :param name (str): 新文件夹名

        :return FileItem: 新目录的 FileItem，失败返回 None
        """
        parent_path = (fileitem.path or "").rstrip("/") or "/"
        try:
            result = self.client.create_folder(parent_path, name)
        except Exception as e:
            logger.error("【CloudDrive】创建文件夹失败 %s/%s: %s", parent_path, name, e)
            return None
        if not result or not result.result or not result.result.success:
            return None
        if result.folderCreated and result.folderCreated.id:
            return _cloudfile_to_fileitem(
                result.folderCreated, self._disk_name, parent_fileid=fileitem.fileid
            )
        new_path = f"{parent_path.rstrip('/')}/{name}/"
        return self.get_item(Path(new_path))

    def get_folder(self, path: Path) -> Optional[FileItem]:
        """
        获取目录，如目录不存在则逐级创建

        :param path (Path): 目录路径

        :return FileItem: 目录文件项，若创建失败则返回 None
        """
        with self._folder_lock:
            return self._get_folder_unlocked(path)

    def _get_folder_unlocked(self, path: Path) -> Optional[FileItem]:
        path = path if path.is_absolute() else Path("/") / path
        normalized = path.as_posix().rstrip("/") or "/"
        if normalized != "/":
            try:
                folder = self.get_item_strict(Path(normalized))
            except StorageQueryError as e:
                logger.error("【CloudDrive】查询目录失败 %s: %s", normalized, e)
                return None
            if folder:
                if folder.type == "dir":
                    return folder
                logger.error("【CloudDrive】目标路径不是目录: %s", normalized)
                return None
        try:
            root = self.get_item_strict(Path("/"))
        except StorageQueryError as e:
            logger.error("【CloudDrive】查询根目录失败: %s", e)
            return None
        if not root:
            root = FileItem(
                storage=self._disk_name,
                fileid="",
                parent_fileid=None,
                name="",
                basename="",
                extension=None,
                type="dir",
                path="/",
                size=None,
                modify_time=None,
            )
        fileitem = root
        parts = path.parts[1:] if path.parts[0] == "/" else path.parts
        for part in parts:
            if not part or part == ".":
                continue
            sub_folders = self.list(fileitem)
            if sub_folders is None:
                logger.error("【CloudDrive】查询子目录失败: %s", fileitem.path)
                return None
            dir_file = next(
                (
                    sub_folder
                    for sub_folder in sub_folders
                    if sub_folder.type == "dir" and sub_folder.name == part
                ),
                None,
            )
            if dir_file:
                fileitem = dir_file
            else:
                dir_file = self.create_folder(fileitem, part)
                if not dir_file:
                    logger.error(
                        "【CloudDrive】创建目录 %s%s 失败",
                        fileitem.path,
                        part,
                    )
                    return None
                fileitem = dir_file
        return fileitem

    def detail(self, fileitem: FileItem) -> Optional[FileItem]:
        """
        获取文件详情

        :param fileitem (FileItem): 文件项

        :return FileItem: 包含详细信息的文件项，如果获取失败则返回None
        """
        return self.get_item(Path(fileitem.path))

    def delete(self, fileitem: FileItem) -> bool:
        """
        删除文件或目录

        :param fileitem (FileItem): 文件项

        :return bool: 删除成功返回 True，失败返回 False
        """
        try:
            result = self.client.delete_file(fileitem.path)
            return bool(result and result.success)
        except Exception as e:
            logger.error("【CloudDrive】删除失败 %s: %s", fileitem.path, e)
            return False

    def _disambiguate_safe_name(self, parent_dir: str, candidate: str) -> str:
        """
        若同目录已存在 candidate，则追加随机后缀避免覆盖

        :param parent_dir (str): 父目录路径
        :param candidate (str): 撇号脱敏后的候选名

        :return str: 唯一候选名
        """

        parent_item = self.get_item(Path(parent_dir))
        if not parent_item:
            return candidate
        existing = {it.name for it in self.list(parent_item)}
        if candidate not in existing:
            return candidate
        for _ in range(32):
            alt = f"{candidate}_cd2_{uuid4().hex[:8]}"
            if alt not in existing:
                logger.warning(
                    "【CloudDrive】撇号脱敏名与同目录冲突，已改用 %s",
                    alt,
                )
                return alt
        alt = f"{candidate}_cd2_{uuid4().hex[:16]}"
        logger.warning("【CloudDrive】撇号脱敏名与同目录冲突，已改用 %s", alt)
        return alt

    def _path_after_rename(self, parent_dir: str, basename: str, is_dir: bool) -> str:
        """
        在父目录下拼接重命名后的完整路径（目录保留末尾 /）

        :param parent_dir (str): 父目录路径
        :param basename (str): 新末段名
        :param is_dir (bool): 是否为目录

        :return str: 完整路径
        """

        joined = _posix_join_parent_name(parent_dir, basename)
        if is_dir and not joined.endswith("/"):
            return joined + "/"
        return joined

    def _verify_rename_succeeded(
        self,
        parent_str: str,
        new_basename: str,
        max_attempts: int = 8,
        delay_s: float = 0.25,
    ) -> bool:
        """
        列举父目录子项，判断是否已存在指定末段名

        :param parent_str (str): 父目录绝对路径
        :param new_basename (str): 重命名后的末段名
        :param max_attempts (int): 最大尝试次数（115 偶发延迟或 RPC 报错后实际已成功）
        :param delay_s (float): 两次尝试间隔秒数

        :return bool: 子项中存在同名则 True
        """

        parent_norm = (parent_str or "/").rstrip("/") or "/"
        for attempt in range(max_attempts):
            try:
                sub = self.client.get_sub_files(parent_norm, force_refresh=True)
                for f in sub:
                    if (f.name or "") == new_basename:
                        return True
            except Exception:
                pass
            if attempt < max_attempts - 1:
                sleep(delay_s)
        return False

    def _rename_with_verify(self, source_path: str, new_basename: str) -> bool:
        """
        重命名并在 API 返回失败时校验路径是否已更新（115/CD2 偶发假失败）

        :param source_path (str): 当前完整路径
        :param new_basename (str): 新名称（仅末段）

        :return bool: 成功返回 True
        """

        result: Any = None
        err: Optional[Exception] = None
        try:
            result = self.client.rename_file(source_path, new_basename)
        except Exception as e:
            err = e
            logger.debug("【CloudDrive】重命名调用异常（将尝试校验）: %s", e)

        ok_api = bool(result and result.success)
        if ok_api:
            return True

        parent = Path(source_path.rstrip("/")).parent
        parent_str = parent.as_posix()
        if parent_str in ("", "."):
            parent_str = "/"

        if self._verify_rename_succeeded(parent_str, new_basename):
            logger.warning(
                "【CloudDrive】重命名 RPC 未返回成功但已校验到目标文件存在，视为成功: %s -> %s",
                source_path,
                new_basename,
            )
            return True

        if err:
            logger.error(
                "【CloudDrive】重命名失败 %s -> %s: %s",
                source_path,
                new_basename,
                err,
            )
        else:
            logger.error(
                "【CloudDrive】重命名失败 %s -> %s: %s",
                source_path,
                new_basename,
                getattr(result, "errorMessage", "") if result else "",
            )
        return False

    def rename(self, fileitem: FileItem, name: str) -> bool:
        """
        重命名文件或目录

        若**旧名（源末段）**含撇号：先改为脱敏名再改为 ``name``，避免一步「含撇号旧名 → 其它名」触发的 API 问题
        若 ``name`` 本身含撇号，第二步仍会把它交给 CD2；规避的是**源路径上的撇号**，不是禁止目标名含撇号

        :param fileitem (FileItem): 文件项
        :param name (str): 新名称

        :return bool: 重命名成功返回 True，失败返回 False
        """
        if name == fileitem.name:
            return True

        raw_path = (fileitem.path or "/").rstrip("/") or "/"
        p = Path(raw_path)
        parent_dir = p.parent.as_posix() or "/"
        if parent_dir == ".":
            parent_dir = "/"
        old_name = fileitem.name or p.name
        is_dir = fileitem.type == "dir"
        current_path = fileitem.path or _posix_join_parent_name(parent_dir, old_name)

        if "'" not in old_name:
            return self._rename_with_verify(current_path, name)

        intermediate = self._disambiguate_safe_name(
            parent_dir, escape_apostrophe_in_name(old_name)
        )
        if not self._rename_with_verify(current_path, intermediate):
            return False
        if intermediate == name:
            return True
        mid_path = self._path_after_rename(parent_dir, intermediate, is_dir)
        # 第二步：源路径已不含撇号；目标名仍可含撇号（策略只约束源侧末段名）
        if not self._rename_with_verify(mid_path, name):
            logger.warning(
                "【CloudDrive】两步重命名第二步失败，对象已保留脱敏末段名且未自动回滚: %s（期望改为 %s）",
                intermediate,
                name,
            )
            return False
        return True

    def move(self, fileitem: FileItem, path: Path, new_name: str) -> bool:
        """
        移动文件或目录到目标位置

        若**被移动项当前末段名**含撇号，移动前先脱敏；移动后再 ``rename`` 为 ``new_name``
        ``new_name`` 可含撇号，规避的是**移动时源路径**中的撇号，与最终展示名是否含撇号无关

        :param fileitem (FileItem): 要移动的文件项
        :param path (Path): 目标目录路径
        :param new_name (str): 移动后的文件名

        :return bool: 成功返回 True，失败返回 False
        """
        dest_path = (
            Path(path).as_posix().rstrip("/") if path is not None else "/"
        ) or "/"

        raw_path = (fileitem.path or "/").rstrip("/") or "/"
        p = Path(raw_path)
        parent_dir = p.parent.as_posix() or "/"
        if parent_dir == ".":
            parent_dir = "/"
        current_name = fileitem.name or p.name
        is_dir = fileitem.type == "dir"
        current_path = fileitem.path or _posix_join_parent_name(
            parent_dir, current_name
        )

        working_name = current_name
        escaped_applied = False
        if "'" in current_name:
            safe = self._disambiguate_safe_name(
                parent_dir, escape_apostrophe_in_name(current_name)
            )
            if not self._rename_with_verify(current_path, safe):
                return False
            escaped_applied = True
            working_name = safe
            current_path = self._path_after_rename(parent_dir, safe, is_dir)

        try:
            result = self.client.move_file([current_path], dest_path)
            if not result or not result.success:
                if escaped_applied:
                    logger.warning(
                        "【CloudDrive】移动失败，源侧已脱敏的对象未移动且未回滚，当前末段: %s",
                        working_name,
                    )
                logger.error(
                    "【CloudDrive】移动失败 %s -> %s: %s",
                    current_path,
                    dest_path,
                    getattr(result, "errorMessage", "") if result else "",
                )
                return False
            if working_name != new_name:
                new_path = _posix_join_parent_name(dest_path, working_name)
                if is_dir and not new_path.endswith("/"):
                    new_path = new_path + "/"
                if not self._rename_with_verify(new_path, new_name):
                    if escaped_applied:
                        logger.warning(
                            "【CloudDrive】移动后重命名失败，目标目录中仍为脱敏末段名且未回滚: %s（期望 %s）",
                            working_name,
                            new_name,
                        )
                    return False
            return True
        except Exception as e:
            if escaped_applied:
                logger.warning(
                    "【CloudDrive】移动异常，源侧已脱敏的对象未移动且未回滚，当前末段: %s",
                    working_name,
                )
            logger.error(
                "【CloudDrive】移动失败 %s -> %s: %s",
                current_path,
                dest_path,
                e,
            )
            return False

    def _find_copied_item(
        self,
        target_dir: FileItem,
        known_ids: Set[str],
        source_item: FileItem,
        max_attempts: int = 8,
    ) -> Optional[FileItem]:
        for attempt in range(max_attempts):
            children = self.list(target_dir)
            if children is not None:
                candidates = [
                    child
                    for child in children
                    if child.fileid
                    and child.fileid not in known_ids
                    and child.type == source_item.type
                ]
                same_name = [
                    child for child in candidates if child.name == source_item.name
                ]
                if len(same_name) == 1:
                    return same_name[0]
                if source_item.type == "file":
                    same_size = [
                        child for child in candidates if child.size == source_item.size
                    ]
                    if len(same_size) == 1:
                        return same_size[0]
                if len(candidates) == 1:
                    return candidates[0]
            if attempt < max_attempts - 1:
                sleep(0.5)
        return None

    def copy(self, fileitem: FileItem, path: Path, new_name: str) -> bool:
        """
        复制文件或目录到目标位置

        :param fileitem (FileItem): 要复制的文件项
        :param path (Path): 目标目录路径
        :param new_name (str): 复制后的文件名

        :return bool: 成功返回 True，失败返回 False
        """
        dest_path = (
            Path(path).as_posix().rstrip("/") if path is not None else "/"
        ) or "/"
        try:
            target_dir = FileItem(
                storage=self._disk_name,
                fileid="",
                path=dest_path + "/" if dest_path != "/" else "/",
                name=Path(dest_path).name if dest_path != "/" else "",
                basename=Path(dest_path).name if dest_path != "/" else "",
                type="dir",
            )
            existing_items = self.list(target_dir)
            if existing_items is None:
                return False
            known_ids = {item.fileid for item in existing_items if item.fileid}
            result = self.client.copy_file([fileitem.path], dest_path)
            if not result or not result.success:
                logger.error(
                    "【CloudDrive】复制失败 %s -> %s: %s",
                    fileitem.path,
                    dest_path,
                    getattr(result, "errorMessage", "") if result else "",
                )
                return False
            new_item = self._find_copied_item(
                target_dir=target_dir,
                known_ids=known_ids,
                source_item=fileitem,
            )
            if not new_item:
                logger.error("【CloudDrive】复制后未找到新增对象: %s", fileitem.path)
                return False
            if new_item.name != new_name:
                if not self._rename_with_verify(new_item.path, new_name):
                    return False
            return True
        except Exception as e:
            logger.error(
                "【CloudDrive】复制失败 %s -> %s: %s",
                fileitem.path,
                dest_path,
                e,
            )
            return False

    def download(
        self, fileitem: FileItem, path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        下载文件到本地

        :param fileitem (FileItem): 文件项
        :param path (Path): 本地目录，None 则使用临时目录

        :return Path: 本地文件路径，失败返回 None
        """
        detail = self.get_item(Path(fileitem.path))
        if not detail:
            logger.error("【CloudDrive】获取文件详情失败: %s", fileitem.name)
            return None
        try:
            url_info = self.client.get_download_url(fileitem.path, get_direct_url=True)
            download_url = None
            headers: Dict[str, str] = {}
            if url_info and url_info.directUrl:
                download_url = url_info.directUrl
                headers["User-Agent"] = (
                    url_info.userAgent if url_info.userAgent else settings.USER_AGENT
                )
                if getattr(url_info, "additionalHeaders", None):
                    for k, v in url_info.additionalHeaders.items():
                        if k and v:
                            headers[k] = v
            elif url_info and url_info.downloadUrlPath:
                headers["User-Agent"] = settings.USER_AGENT
                host_part = self._download_base.replace("http://", "").replace(
                    "https://", ""
                )
                path_part = (
                    url_info.downloadUrlPath.replace("{SCHEME}", "http")
                    .replace("{HOST}", host_part)
                    .replace("{PREVIEW}", "false")
                )
                download_url = self._download_base + path_part
            if not download_url:
                logger.error("【CloudDrive】下载链接为空: %s", fileitem.name)
                return None
            local_path = _build_download_path(fileitem, path or settings.TEMP_PATH)
            if not local_path:
                logger.error("【CloudDrive】下载文件名无效: %s", fileitem.name)
                return None
        except Exception as e:
            logger.error("【CloudDrive】获取下载链接失败 %s: %s", fileitem.path, e)
            return None
        file_size = detail.size
        logger.info("【CloudDrive】开始下载: %s -> %s", fileitem.name, local_path)
        progress_callback = transfer_process(Path(fileitem.path).as_posix())
        try:
            with httpx_stream("GET", download_url, headers=headers) as r:
                r.raise_for_status()
                downloaded_size = 0
                with open(local_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=10 * 1024 * 1024):
                        if global_vars.is_transfer_stopped(fileitem.path):
                            logger.info("【CloudDrive】%s 下载已取消", fileitem.path)
                            r.close()
                            raise InterruptedError
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if file_size:
                            progress = (downloaded_size * 100) / file_size
                            progress_callback(progress)
                progress_callback(100)
                logger.info("【CloudDrive】下载完成: %s", fileitem.name)
        except InterruptedError:
            if local_path.exists():
                local_path.unlink()
            return None
        except RequestError as e:
            logger.error("【CloudDrive】下载网络错误 %s: %s", fileitem.name, e)
            if local_path.exists():
                local_path.unlink()
            return None
        except Exception as e:
            logger.error("【CloudDrive】下载失败 %s: %s", fileitem.name, e)
            if local_path.exists():
                local_path.unlink()
            return None
        return local_path

    def _compute_file_hash(self, path: Path, hash_type: int) -> str:
        """
        计算文件 MD5(1)、SHA1(2) 或 PikPakSha1(3)，返回十六进制字符串

        :param path (Path): 文件路径
        :param hash_type (int): 哈希类型 (HashType.MD5 / SHA1 / PIKPAK_SHA1)

        :return str: 十六进制字符串（PikPakSha1 为大写，其余小写）
        """
        if hash_type == HashType.PIKPAK_SHA1:
            return self._compute_pikpak_sha1(path)
        algo = hashes.MD5() if hash_type == HashType.MD5 else hashes.SHA1()
        h = hashes.Hash(algo)
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.finalize().hex()

    def _compute_pikpak_sha1(self, path: Path) -> str:
        """
        PikPakSha1：按文件大小动态分段，每段 SHA1 后连接再对连接做 SHA1，输出大写十六进制
        分段规则：<=128MiB 用 256KiB；128-256 用 512KiB；256-512 用 1024KiB；>512 用 2048KiB

        :param path (Path): 文件路径

        :return str: 大写十六进制字符串
        """
        size = path.stat().st_size
        if size <= 128 << 20:
            seg_size = 256 << 10
        elif size <= 256 << 20:
            seg_size = 512 << 10
        elif size <= 512 << 20:
            seg_size = 1024 << 10
        else:
            seg_size = 2048 << 10
        final_sha1 = hashes.Hash(hashes.SHA1())
        with open(path, "rb") as f:
            while chunk := f.read(seg_size):
                seg = hashes.Hash(hashes.SHA1())
                seg.update(chunk)
                final_sha1.update(seg.finalize())
        return final_sha1.finalize().hex().upper()

    def _compute_all_hashes_one_pass(
        self, path: Path, cancel_path: Optional[str] = None
    ) -> Dict[int, str]:
        """
        单遍读取文件同时计算 MD5、SHA1、PikPakSha1

        :param path (Path): 文件路径
        :param cancel_path (str): V3 整理取消信号使用的本地源路径

        :return Dict: {HashType.MD5: hex, HashType.SHA1: hex, HashType.PIKPAK_SHA1: hex}
        """
        total_size = path.stat().st_size
        if total_size <= 128 << 20:
            seg_size = 256 << 10
        elif total_size <= 256 << 20:
            seg_size = 512 << 10
        elif total_size <= 512 << 20:
            seg_size = 1024 << 10
        else:
            seg_size = 2048 << 10
        file_md5 = hashes.Hash(hashes.MD5())
        file_sha1 = hashes.Hash(hashes.SHA1())
        final_sha1 = hashes.Hash(hashes.SHA1())
        with open(path, "rb") as f:
            while chunk := f.read(seg_size):
                if cancel_path and global_vars.is_transfer_stopped(cancel_path):
                    raise InterruptedError("上传已取消")
                file_md5.update(chunk)
                file_sha1.update(chunk)
                seg = hashes.Hash(hashes.SHA1())
                seg.update(chunk)
                final_sha1.update(seg.finalize())
        return {
            HashType.MD5: file_md5.finalize().hex(),
            HashType.SHA1: file_sha1.finalize().hex(),
            HashType.PIKPAK_SHA1: final_sha1.finalize().hex().upper(),
        }

    def _compute_file_md5_with_blocks(
        self,
        path: Path,
        block_size: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancelled_ref: Optional[List[bool]] = None,
    ) -> Tuple[str, List[str]]:
        """
        计算文件 MD5 及按 block_size 的每块 MD5（小写十六进制，按序）
        协议要求计算过程中定期上报进度，避免约 60 秒无 RemoteHashProgress 导致会话失效

        :param path (Path): 文件路径
        :param block_size (int): 块大小（字节）
        :param progress_callback (Callable): 可选，(bytes_hashed, total_bytes) 回调，建议约 0.25s 节流
        :param cancelled_ref (List): 可选，[False] 的列表；若在回调中被设为 [True] 则提前结束

        :return Tuple: (文件 MD5 十六进制, 块 MD5 列表)
        """
        total_bytes = path.stat().st_size
        file_md5 = hashes.Hash(hashes.MD5())
        blocks: List[str] = []
        bytes_hashed = 0
        last_report = 0.0
        with open(path, "rb") as f:
            while chunk := f.read(block_size):
                if cancelled_ref and cancelled_ref[0]:
                    break
                file_md5.update(chunk)
                block_hasher = hashes.Hash(hashes.MD5())
                block_hasher.update(chunk)
                blocks.append(block_hasher.finalize().hex())
                bytes_hashed += len(chunk)
                if progress_callback:
                    now = monotonic()
                    if now - last_report >= 0.25:
                        last_report = now
                        progress_callback(bytes_hashed, total_bytes)
        return file_md5.finalize().hex(), blocks

    @staticmethod
    def _iter_stream_with_timeout(stream, timeout: int = 300) -> Iterator:
        """
        包装 gRPC 服务端流，为每条消息添加超时

        :param stream (Iterator): gRPC 服务端流迭代器
        :param timeout (int): 每条消息的超时秒数，默认 300 秒

        :return Iterator: 包装后的迭代器
        """
        q: Queue = Queue()
        _SENTINEL = object()

        def _reader() -> None:
            try:
                for msg in stream:
                    q.put(msg)
                q.put(_SENTINEL)
            except Exception as e:
                q.put(e)

        t = Thread(target=_reader, daemon=True, name="cd2-stream-reader")
        t.start()

        while True:
            try:
                item = q.get(timeout=timeout)
            except Empty:
                try:
                    stream.cancel()
                except Exception:
                    pass
                raise TimeoutError(f"gRPC 流超时：{timeout} 秒内未收到服务端消息")
            if item is _SENTINEL:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    def _cancel_upload(self, upload_id: str) -> None:
        """
        安全取消远程上传会话，忽略取消过程中的异常

        :param upload_id (str): StartRemoteUpload 返回的上传会话 ID
        """
        try:
            self.client.remote_upload_control_cancel(upload_id)
        except Exception:
            pass

    def upload(
        self,
        target_dir: FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[FileItem]:
        """
        上传文件到 CloudDrive

        upload_mode:
        - remote_upload: Remote Upload 协议（StartRemoteUpload → RemoteUploadChannel）
        - direct_write: CreateFile/WriteToFile/CloseFile 直写上传，并等待云端上传完成

        :param target_dir (FileItem): 目标目录 FileItem
        :param local_path (Path): 本地文件路径
        :param new_name (str): 云端文件名，None 则用 local_path.name

        :return FileItem: 上传成功返回云端文件 FileItem，失败返回 None
        """
        mode = (self._upload_mode or "direct_write").strip() or "direct_write"
        if mode == "direct_write":
            return self._upload_direct_write(target_dir, local_path, new_name)
        return self._upload_remote_upload(target_dir, local_path, new_name)

    def _upload_remote_upload(
        self,
        target_dir: FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[FileItem]:
        """
        上传文件到 CloudDrive（Remote Upload 协议）

        协议参考: https://www.clouddrive2.com/api/CloudDrive2_gRPC_API_Guide.html
        （远程上传协议：StartRemoteUpload → RemoteUploadChannel 流 → 响应 ReadData/HashData）

        :param target_dir (FileItem): 目标目录 FileItem
        :param local_path (Path): 本地文件路径
        :param new_name (str): 云端文件名，None 则用 local_path.name

        :return FileItem: 上传成功返回云端文件 FileItem，失败返回 None
        """
        max_retries = 3
        if not local_path.exists() or not local_path.is_file():
            logger.error("【CloudDrive】上传文件不存在或非文件: %s", local_path)
            return None
        file_size = local_path.stat().st_size
        target_name = new_name or local_path.name
        parent_path = (target_dir.path or "").rstrip("/") or "/"
        target_path = f"{parent_path.rstrip('/')}/{target_name}"
        cancel_path = local_path.as_posix()

        logger.info("【CloudDrive】预计算文件哈希: %s", target_name)
        try:
            precomputed_hashes = self._compute_all_hashes_one_pass(
                local_path, cancel_path=cancel_path
            )
        except InterruptedError:
            logger.info("【CloudDrive】上传已取消: %s", local_path)
            return None

        for attempt in range(1, max_retries + 1):
            if global_vars.is_transfer_stopped(cancel_path):
                logger.info("【CloudDrive】上传已取消: %s", target_path)
                return None
            result = self._upload_once(
                target_path=target_path,
                local_path=local_path,
                file_size=file_size,
                precomputed_hashes=precomputed_hashes,
            )
            if result is not None:
                return result
            if result is None and attempt < max_retries:
                if global_vars.is_transfer_stopped(cancel_path):
                    return None
                logger.warning(
                    "【CloudDrive】上传失败，第 %d/%d 次重试: %s",
                    attempt,
                    max_retries,
                    target_path,
                )
        logger.error(
            "【CloudDrive】上传最终失败（已重试 %d 次）: %s",
            max_retries,
            target_path,
        )
        return None

    def _wait_upload_complete(
        self,
        remote_path: str,
        cancel_path: str,
        timeout: int = 3600,
        interval: int = 5,
        stall_timeout: int = 1800,
    ) -> bool:
        """
        等待 CloudDrive2 将直写文件上传到云端完成

        通过轮询 get_upload_file_list 查找 destPath 匹配项的终态

        :param remote_path (str): 云端目标路径
        :param cancel_path (str): V3 整理取消信号使用的本地源路径
        :param timeout (int): 总超时时间（秒）
        :param interval (int): 轮询间隔（秒）
        :param stall_timeout (int): 无进度超时（秒）

        :return bool: 成功完成返回 True，否则 False
        """
        terminal, finish_value = self.client.upload_terminal_enums()

        normalized = Path(remote_path).as_posix() if remote_path else "/"
        deadline = monotonic() + timeout
        found_ever = False
        last_observed_state = None
        last_activity_time = monotonic()

        while monotonic() < deadline:
            if global_vars.is_transfer_stopped(cancel_path):
                logger.info("【CloudDrive】等待云端上传已取消: %s", normalized)
                self._cancel_upload_by_path(normalized)
                return False
            try:
                resp = self.client.get_upload_file_list(get_all=True)
                upload_files = getattr(resp, "uploadFiles", None) or []

                found = False
                for uf in upload_files:
                    raw_dest = getattr(uf, "destPath", "") or ""
                    dest = Path(raw_dest).as_posix() if raw_dest else "/"
                    if dest != normalized and dest.rstrip("/") != normalized.rstrip(
                        "/"
                    ):
                        continue
                    found = True
                    found_ever = True

                    status_enum = getattr(uf, "statusEnum", None)
                    status_str = getattr(uf, "status", "")
                    transferred = int(getattr(uf, "transferedBytes", 0) or 0)
                    total = int(getattr(uf, "size", 0) or 0)
                    observed_state = (status_enum, status_str, transferred, total)

                    if terminal and status_enum in terminal:
                        if finish_value is not None and status_enum == finish_value:
                            logger.info("【CloudDrive】云端上传完成: %s", normalized)
                            return True
                        logger.warning(
                            "【CloudDrive】云端上传终态非成功: %s, status=%s, enum=%s",
                            normalized,
                            status_str,
                            status_enum,
                        )
                        return False

                    now = monotonic()
                    if observed_state != last_observed_state:
                        last_activity_time = now
                        last_observed_state = observed_state

                    dynamic_stall_timeout = stall_timeout
                    status_lc = str(status_str).lower()
                    if status_lc == "waitingforpreprocessing":
                        dynamic_stall_timeout = None

                    if dynamic_stall_timeout is not None and (
                        now - last_activity_time >= dynamic_stall_timeout
                    ):
                        logger.warning(
                            "【CloudDrive】云端上传停滞超时(%ss 无状态/进度变化): %s, status=%s",
                            dynamic_stall_timeout,
                            normalized,
                            status_str,
                        )
                        return False

                    if total > 0:
                        logger.debug(
                            "【CloudDrive】等待云端上传: %s, status=%s, progress=%.1f%%, %d/%d",
                            normalized,
                            status_str,
                            transferred / total * 100,
                            transferred,
                            total,
                        )
                    else:
                        logger.debug(
                            "【CloudDrive】等待云端上传: %s, status=%s, transferred=%d",
                            normalized,
                            status_str,
                            transferred,
                        )
                    break

                if not found and found_ever:
                    logger.info(
                        "【CloudDrive】上传任务已从队列消失，视为完成: %s", normalized
                    )
                    return True
            except Exception as e:
                logger.debug("【CloudDrive】查询上传状态失败: %s, %s", normalized, e)

            sleep(max(int(interval), 1))

        logger.warning("【CloudDrive】等待云端上传超时(%ss): %s", timeout, normalized)
        return False

    def _cancel_upload_by_path(
        self, remote_path: str, retries: int = 5, interval: int = 1
    ) -> bool:
        """
        按远端路径查找并取消 CloudDrive2 上传队列任务

        :param remote_path (str): 远端目标路径
        :param retries (int): 查询上传队列的最大次数
        :param interval (int): 查询间隔秒数

        :return bool: 找到并提交取消请求返回 True，否则返回 False
        """
        normalized = Path(remote_path).as_posix() if remote_path else "/"
        for attempt in range(max(retries, 1)):
            try:
                resp = self.client.get_upload_file_list(get_all=True)
                upload_files = getattr(resp, "uploadFiles", None) or []
                keys = [
                    str(getattr(upload_file, "key", ""))
                    for upload_file in upload_files
                    if (
                        Path(getattr(upload_file, "destPath", "") or "/").as_posix()
                        == normalized
                        or Path(getattr(upload_file, "destPath", "") or "/")
                        .as_posix()
                        .rstrip("/")
                        == normalized.rstrip("/")
                    )
                    and getattr(upload_file, "key", "")
                ]
                if keys:
                    self.client.cancel_upload_files(keys)
                    logger.info("【CloudDrive】已取消云端上传任务: %s", normalized)
                    return True
            except Exception as e:
                logger.debug(
                    "【CloudDrive】取消云端上传任务失败: %s, %s", normalized, e
                )
            if attempt < max(retries, 1) - 1:
                sleep(max(interval, 1))
        logger.warning("【CloudDrive】未找到可取消的云端上传任务: %s", normalized)
        return False

    def _upload_direct_write(
        self,
        target_dir: FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[FileItem]:
        """
        直写上传

        :param target_dir (FileItem): 目标目录 FileItem
        :param local_path (Path): 本地文件路径
        :param new_name (str): 云端文件名，None 则用 local_path.name

        :return FileItem: 上传成功返回云端文件 FileItem，失败返回 None
        """
        if not local_path.exists() or not local_path.is_file():
            logger.error("【CloudDrive】上传文件不存在或非文件: %s", local_path)
            return None

        target_name = new_name or local_path.name
        raw_dir = (target_dir.path or "/").rstrip("/") or "/"
        remote_dir = Path(raw_dir).as_posix() if raw_dir else "/"
        remote_path = (PurePosixPath(remote_dir) / target_name).as_posix()
        file_size = local_path.stat().st_size
        cancel_path = local_path.as_posix()
        progress_callback = transfer_process(cancel_path)

        if global_vars.is_transfer_stopped(cancel_path):
            logger.info("【CloudDrive】上传已取消: %s", remote_path)
            return None

        if not self.get_folder(Path(remote_dir)):
            logger.error("【CloudDrive】上传失败，目标目录创建失败: %s", remote_dir)
            return None

        file_handle = 0
        cancelled = False
        try:
            file_handle = self.client.create_file(remote_dir, target_name)
            if file_handle <= 0:
                logger.error(
                    "【CloudDrive】上传失败，创建远端文件句柄失败: %s", remote_path
                )
                return None

            chunk_size = 3 * 1024 * 1024
            offset = 0
            with open(local_path, "rb") as f:
                while True:
                    if global_vars.is_transfer_stopped(cancel_path):
                        logger.info("【CloudDrive】上传已取消: %s", remote_path)
                        cancelled = True
                        return None
                    data = f.read(chunk_size)
                    if not data:
                        break
                    bytes_written = self.client.write_to_file(file_handle, offset, data)
                    if bytes_written != len(data):
                        logger.error(
                            "【CloudDrive】上传失败，写入长度不匹配: %s, expect=%d, actual=%d",
                            remote_path,
                            len(data),
                            bytes_written,
                        )
                        return None
                    offset += bytes_written
                    if file_size:
                        progress_callback(offset * 100.0 / file_size)

            if not self.client.close_file(file_handle):
                logger.error("【CloudDrive】上传失败，关闭文件失败: %s", remote_path)
                return None

            file_handle = 0

            if not self._wait_upload_complete(remote_path, cancel_path=cancel_path):
                logger.error("【CloudDrive】等待云端上传完成失败: %s", remote_path)
                return None

            progress_callback(100)
            return self.get_item(Path(remote_path))
        except Exception as e:
            logger.error("【CloudDrive】直写上传失败 %s: %s", remote_path, e)
            return None
        finally:
            if file_handle > 0:
                try:
                    self.client.close_file(file_handle)
                except Exception:
                    pass
            if cancelled:
                self._cancel_upload_by_path(remote_path)

    def _upload_once(
        self,
        target_path: str,
        local_path: Path,
        file_size: int,
        precomputed_hashes: Dict[int, str],
    ) -> Optional[FileItem]:
        """
        执行一次上传尝试

        :param target_path (str): 云端目标路径
        :param local_path (Path): 本地文件路径
        :param file_size (int): 文件大小
        :param precomputed_hashes (Dict): 预计算的哈希字典

        :return FileItem: 上传成功返回 FileItem，失败返回 None
        """
        cancel_path = local_path.as_posix()
        progress_callback = transfer_process(cancel_path)
        stream = None
        upload_id = None
        upload_finished = False
        try:
            stream = self.client.remote_upload_channel(
                device_id=f"moviepilot-{uuid4().hex[:12]}"
            )
            stream.initial_metadata()
            started = self.client.start_remote_upload(
                file_path=target_path,
                file_size=file_size,
                known_hashes=precomputed_hashes,
                client_can_calculate_hashes=True,
            )
            upload_id = started.upload_id
            with open(local_path, "rb") as f:
                for reply in self._iter_stream_with_timeout(stream, timeout=300):
                    if global_vars.is_transfer_stopped(cancel_path):
                        logger.info("【CloudDrive】上传已取消: %s", target_path)
                        self._cancel_upload(upload_id)
                        return None
                    which = reply.WhichOneof("request")
                    if not which:
                        continue
                    if reply.upload_id != upload_id:
                        continue
                    if which == "read_data":
                        req = reply.read_data
                        offset = req.offset
                        length = req.length
                        f.seek(offset)
                        data = f.read(length)
                        is_last = (offset + len(data)) >= file_size
                        try:
                            resp = self.client.remote_read_data(
                                upload_id=upload_id,
                                offset=offset,
                                length=len(data),
                                data=data,
                                is_last_chunk=is_last,
                                lazy_read=getattr(req, "lazy_read", False),
                            )
                            logger.info(
                                f"【CloudDrive】RemoteReadData 成功: {offset} {len(data)}"
                            )
                        except Exception as e:
                            logger.error("【CloudDrive】RemoteReadData 失败: %s", e)
                            self._cancel_upload(upload_id)
                            return None
                        if not resp.success:
                            logger.error(
                                "【CloudDrive】RemoteReadData 服务端失败: %s",
                                resp.error_message,
                            )
                            return None
                        if file_size:
                            progress_callback((offset + len(data)) * 100.0 / file_size)
                    elif which == "hash_data":
                        req = reply.hash_data
                        ht = req.hash_type
                        block_size = getattr(req, "block_size", 0) or 0

                        def _report_hash_progress(
                            bytes_hashed: int,
                            total_bytes: int,
                            hash_value: str = "",
                            blocks: Optional[List[str]] = None,
                        ) -> None:
                            try:
                                resp = self.client.remote_hash_progress(
                                    upload_id=upload_id,
                                    bytes_hashed=bytes_hashed,
                                    total_bytes=total_bytes,
                                    hash_type=ht,
                                    hash_value=hash_value,
                                    block_hashes=blocks,
                                )
                                logger.info(
                                    "【CloudDrive】上报本地哈希计算状态: %s", resp
                                )
                            except Exception as e:
                                logger.error(
                                    "【CloudDrive】上报本地哈希计算状态失败: %s", e
                                )

                        if global_vars.is_transfer_stopped(cancel_path):
                            _report_hash_progress(0, file_size)
                            logger.info("【CloudDrive】上传已取消: %s", target_path)
                            self._cancel_upload(upload_id)
                            return None
                        hash_val: Optional[str]
                        block_hashes: Optional[List[str]] = None
                        cancelled_ref: List[bool] = [False]

                        def _hash_progress_callback(bh: int, tb: int) -> None:
                            if global_vars.is_transfer_stopped(cancel_path):
                                cancelled_ref[0] = True
                                _report_hash_progress(bh, tb)
                                return
                            _report_hash_progress(bh, tb)

                        if ht == HashType.MD5 and block_size > 0:
                            hash_val, block_hashes = self._compute_file_md5_with_blocks(
                                local_path,
                                block_size,
                                progress_callback=_hash_progress_callback,
                                cancelled_ref=cancelled_ref,
                            )
                            if cancelled_ref[0]:
                                self._cancel_upload(upload_id)
                                return None
                        else:
                            hash_val = precomputed_hashes.get(ht)
                            if hash_val is None:
                                hash_val = self._compute_file_hash(local_path, ht)
                        if global_vars.is_transfer_stopped(cancel_path):
                            _report_hash_progress(file_size, file_size)
                            self._cancel_upload(upload_id)
                            return None
                        try:
                            resp = self.client.remote_hash_progress(
                                upload_id=upload_id,
                                bytes_hashed=file_size,
                                total_bytes=file_size,
                                hash_type=ht,
                                hash_value=hash_val or "",
                                block_hashes=block_hashes,
                            )
                            logger.info(f"【CloudDrive】上报本地哈希计算状态: {resp}")
                        except Exception as e:
                            logger.warning(
                                "【CloudDrive】RemoteHashProgress 失败: %s", e
                            )
                            self._cancel_upload(upload_id)
                            return None
                    elif which == "status_changed":
                        st = reply.status_changed.status
                        if st == UploadStatus.FINISH:
                            progress_callback(100)
                            upload_finished = True
                            logger.info(f"【CloudDrive】上传完成状态码: {st}")
                            break
                        if st in (UploadStatus.ERROR, UploadStatus.FATAL_ERROR):
                            msg = reply.status_changed.error_message or "上传失败"
                            logger.error("【CloudDrive】上传状态错误: %s", msg)
                            self._cancel_upload(upload_id)
                            return None
        except TimeoutError as e:
            logger.warning("【CloudDrive】上传流超时: %s", e)
            if upload_id:
                self._cancel_upload(upload_id)
            return None
        except Exception as e:
            logger.error("【CloudDrive】上传过程异常: %s", e)
            if upload_id:
                self._cancel_upload(upload_id)
            return None
        finally:
            if stream is not None:
                if upload_finished:
                    _stream_ref = stream

                    def _drain_stream() -> None:
                        try:
                            for _ in _stream_ref:
                                pass
                        except Exception:
                            pass

                    Thread(
                        target=_drain_stream, daemon=True, name="cd2-stream-drain"
                    ).start()
                else:
                    try:
                        stream.cancel()
                    except Exception:
                        pass
        if not upload_finished:
            return None
        logger.info(f"【CloudDrive】上传完成: {target_path}")
        return self.get_item(Path(target_path))

    def link(self, fileitem: FileItem, target_file: Path) -> bool:
        """
        硬链接文件
        云盘存储不支持硬链接操作

        :param fileitem (FileItem): 文件项
        :param target_file (Path): 目标文件路径

        :return bool: 始终返回False，表示不支持此操作
        """
        return False

    def softlink(self, fileitem: FileItem, target_file: Path) -> bool:
        """
        软链接文件
        云盘存储不支持软链接操作

        :param fileitem (FileItem): 文件项
        :param target_file (Path): 目标文件路径

        :return bool: 始终返回False，表示不支持此操作
        """
        return False

    def usage(self) -> Optional[StorageUsage]:
        """
        获取存储空间用量

        :return StorageUsage: 存储空间用量，如果获取失败则返回None
        """
        try:
            info = self.client.get_space_info("/")
            if not info:
                return None
            return StorageUsage(
                total=info.totalSpace or 0,
                available=info.freeSpace if info.freeSpace is not None else 0,
            )
        except Exception as e:
            logger.warning("【CloudDrive】GetSpaceInfo 失败: %s", e)
            return None

    def support_transtype(self) -> dict:
        """
        支持的整理方式

        :return dict: 支持的整理方式字典
        """
        return self.transtype

    def is_support_transtype(self, transtype: str) -> bool:
        """
        是否支持整理方式

        :param transtype (str): 整理方式 (move/copy)

        :return bool: 是否支持
        """
        return transtype in self.transtype
