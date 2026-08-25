import ast
import time
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Dict, List, Optional, Set
from hashlib import md5
from datetime import datetime

import requests
from p123client import check_response

from app import schemas
from app.modules.filemanager.storages import transfer_process
from app.schemas.exception import StorageQueryError
from app.sdk.config import global_vars, settings
from app.sdk.logging import logger
from app.sdk.utilities import StringUtils

from .tool import P123AutoClient


def _build_download_path(fileitem: schemas.FileItem, base_path: Path) -> Optional[Path]:
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


class P123Api:
    """
    123云盘基础操作类
    """

    def __init__(self, client: P123AutoClient, disk_name: str):
        """
        初始化123云盘API

        :param client: 123云盘客户端实例
        :param disk_name: 云盘名称
        """
        self.client = client
        self._disk_name = disk_name
        self.transtype = {"move": "移动", "copy": "复制"}
        self._id_cache: Dict[str, str] = {}
        self._folder_lock = RLock()

    def _path_to_id(self, path: str) -> str:
        """
        通过路径获取文件ID

        :param path: 文件或目录路径
        :return: 文件ID字符串
        :raises FileNotFoundError: 当路径不存在时抛出异常
        """
        # 根目录
        if path == "/":
            return "0"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        # 检查缓存
        if path in self._id_cache:
            return self._id_cache[path]
        # 逐级查找缓存
        current_id = 0
        parent_path = "/"
        for p in Path(path).parents:
            if str(p) in self._id_cache:
                parent_path = str(p)
                current_id = self._id_cache[parent_path]
                break
        # 计算相对路径
        rel_path = Path(path).relative_to(parent_path)
        for part in Path(rel_path).parts:
            find_part = False
            page = 1
            _next = 0
            first_find = True
            while True:
                payload = {
                    "limit": 100,
                    "next": _next,
                    "Page": page,
                    "parentFileId": int(current_id),
                    "inDirectSpace": "false",
                }
                if first_find:
                    first_find = False
                else:
                    time.sleep(1)
                resp = self.client.fs_list(payload)
                check_response(resp)
                item_list = resp.get("data").get("InfoList")
                if not item_list:
                    break
                for item in item_list:
                    if item["FileName"] == part:
                        current_id = item["FileId"]
                        find_part = True
                        break
                if find_part:
                    break
                if resp.get("data").get("Next") == "-1":
                    break
                else:
                    page += 1
                    _next = resp.get("data").get("Next")
            if not find_part:
                raise FileNotFoundError(f"【123】{path} 不存在")
        if not current_id:
            raise FileNotFoundError(f"【123】{path} 不存在")
        # 缓存路径
        self._id_cache[path] = str(current_id)
        return str(current_id)

    def _invalidate_path_cache(self, path: str) -> None:
        normalized = PurePosixPath(path).as_posix().rstrip("/") or "/"
        for cached_path in list(self._id_cache):
            cached_normalized = PurePosixPath(cached_path).as_posix().rstrip("/") or "/"
            if cached_normalized == normalized or PurePosixPath(
                cached_normalized
            ).is_relative_to(PurePosixPath(normalized)):
                self._id_cache.pop(cached_path, None)

    def list(self, fileitem: schemas.FileItem) -> Optional[List[schemas.FileItem]]:
        """
        浏览文件或目录

        :param fileitem: 文件项，可以是文件或目录
        :return: 文件项列表，如果是文件则返回包含该文件的列表，如果是目录则返回目录下的所有文件和子目录
        """
        if fileitem.type == "file":
            item = self.detail(fileitem)
            if item:
                return [item]
            return []
        try:
            if fileitem.path == "/":
                file_id = "0"
            else:
                file_id = fileitem.fileid
                if not file_id:
                    file_id = self._path_to_id(fileitem.path)

            items = []
            page = 1
            _next = 0
            first_find = True
            while True:
                payload = {
                    "limit": 100,
                    "next": _next,
                    "Page": page,
                    "parentFileId": int(file_id),
                    "inDirectSpace": "false",
                }
                if first_find:
                    first_find = False
                else:
                    time.sleep(1)
                resp = self.client.fs_list(payload)
                check_response(resp)
                item_list = resp.get("data").get("InfoList")
                if not item_list:
                    break
                for item in item_list:
                    path = f"{fileitem.path}{item['FileName']}"
                    self._id_cache[path] = str(item["FileId"])

                    file_path = path + ("/" if item["Type"] == 1 else "")
                    items.append(
                        schemas.FileItem(
                            storage=self._disk_name,
                            fileid=str(item["FileId"]),
                            parent_fileid=str(item["ParentFileId"]),
                            name=item["FileName"],
                            basename=Path(item["FileName"]).stem,
                            extension=Path(item["FileName"]).suffix[1:]
                            if item["Type"] == 0
                            else None,
                            type="dir" if item["Type"] == 1 else "file",
                            path=file_path,
                            size=item["Size"] if item["Type"] == 0 else None,
                            modify_time=int(
                                datetime.fromisoformat(item["UpdateAt"]).timestamp()
                            ),
                            pickcode=str(item),
                        )
                    )
                if resp.get("data").get("Next") == "-1":
                    break
                else:
                    page += 1
                    _next = resp.get("data").get("Next")
        except Exception as e:
            logger.debug(f"【123】获取信息失败: {str(e)}")
            return None
        return items

    def create_folder(
        self, fileitem: schemas.FileItem, name: str
    ) -> Optional[schemas.FileItem]:
        """
        创建目录

        :param fileitem: 父目录文件项
        :param name: 要创建的目录名称
        :return: 创建成功返回目录文件项，失败返回None
        """
        try:
            new_path = Path(fileitem.path) / name
            resp = self.client.fs_mkdir(name, parent_id=self._path_to_id(fileitem.path))
            check_response(resp)
            logger.debug(f"【123】创建目录: {resp}")
            data = resp["data"]["Info"]
            # 缓存新目录
            self._id_cache[str(new_path)] = str(data["FileId"])
            return schemas.FileItem(
                storage=self._disk_name,
                fileid=str(data["FileId"]),
                path=str(new_path) + "/",
                name=name,
                basename=name,
                type="dir",
                modify_time=int(datetime.fromisoformat(data["UpdateAt"]).timestamp()),
                pickcode=str(data),
            )
        except Exception as e:
            logger.debug(f"【123】创建目录失败: {str(e)}")
            return None

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取目录，如目录不存在则创建

        :param path: 目录路径
        :return: 目录文件项，如果创建失败则返回None
        """

        with self._folder_lock:
            return self._get_folder_unlocked(path)

    def _get_folder_unlocked(self, path: Path) -> Optional[schemas.FileItem]:
        path = path if path.is_absolute() else Path("/") / path
        try:
            folder = self.get_item_strict(path)
        except StorageQueryError as e:
            logger.error(f"【123】查询目录失败: {path} - {e}")
            return None
        if folder:
            if folder.type == "dir":
                return folder
            logger.error(f"【123】目标路径不是目录: {path}")
            return None
        fileitem = schemas.FileItem(
            storage=self._disk_name,
            fileid="0",
            path="/",
            name="",
            basename="",
            type="dir",
        )
        for part in path.parts[1:]:
            sub_folders = self.list(fileitem)
            if sub_folders is None:
                logger.error(f"【123】查询子目录失败: {fileitem.path}")
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
                    logger.warn(f"【123】创建目录 {fileitem.path}{part} 失败！")
                    return None
                fileitem = dir_file
        return fileitem

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取文件或目录，不存在返回None

        :param path: 文件或目录路径
        :return: 文件项，如果不存在则返回None
        """
        try:
            return self._query_item(path)
        except Exception as e:
            logger.debug(f"【123】获取文件信息失败: {str(e)}")
            return None

    def get_item_strict(self, path: Path) -> Optional[schemas.FileItem]:
        """
        严格获取文件或目录，无法确认状态时抛出存储查询异常

        :param path (Path): 文件或目录路径

        :return FileItem: 文件项，确认不存在时返回 None

        :raises StorageQueryError: 网络或接口异常导致无法确认文件状态
        """
        try:
            return self._query_item(path)
        except FileNotFoundError:
            return None
        except StorageQueryError:
            raise
        except Exception as e:
            raise StorageQueryError(f"【123】查询文件信息失败: {path} - {e}") from e

    def _query_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        查询远端文件项

        :param path (Path): 文件或目录路径

        :return FileItem: 查询到的文件项

        :raises FileNotFoundError: 文件或目录确认不存在
        """
        file_id = self._path_to_id(str(path))
        if not file_id:
            return None
        resp = self.client.fs_info(int(file_id))
        check_response(resp)
        logger.debug(f"【123】获取文件信息: {resp}")
        data = resp["data"]["infoList"][0]
        return schemas.FileItem(
            storage=self._disk_name,
            fileid=str(data["FileId"]),
            path=str(path) + ("/" if data["Type"] == 1 else ""),
            type="file" if data["Type"] == 0 else "dir",
            name=data["FileName"],
            basename=Path(data["FileName"]).stem,
            extension=Path(data["FileName"]).suffix[1:] if data["Type"] == 0 else None,
            pickcode=str(data),
            size=data["Size"] if data["Type"] == 0 else None,
            modify_time=int(datetime.fromisoformat(data["UpdateAt"]).timestamp()),
        )

    def get_parent(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取父目录

        :param fileitem: 文件项
        :return: 父目录文件项，如果不存在则返回None
        """
        return self.get_item(Path(fileitem.path).parent)

    def delete(self, fileitem: schemas.FileItem) -> bool:
        """
        删除文件或目录
        此操作将文件移动到回收站，不会永久删除

        :param fileitem: 要删除的文件项
        :return: 删除成功返回True，失败返回False
        """
        try:
            resp = self.client.fs_trash(int(fileitem.fileid), event="intoRecycle")
            check_response(resp)
            self._invalidate_path_cache(fileitem.path)
            logger.debug(f"【123】删除文件: {resp}")
            return True
        except Exception:
            return False

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        """
        重命名文件或目录

        :param fileitem: 要重命名的文件项
        :param name: 新名称
        :return: 重命名成功返回True，失败返回False
        """
        try:
            payload = {
                "FileId": int(fileitem.fileid),
                "fileName": name,
                "duplicate": 2,
            }
            resp = self.client.fs_rename(payload)
            check_response(resp)
            old_path = Path(fileitem.path)
            new_path = old_path.parent / name
            self._invalidate_path_cache(fileitem.path)
            self._id_cache[new_path.as_posix()] = str(fileitem.fileid)
            logger.debug(f"【123】重命名文件: {resp}")
            return True
        except Exception:
            return False

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
        """
        下载文件，保存到本地，返回本地临时文件地址

        :param fileitem: 要下载的文件项
        :param path: 文件保存路径，如果为None则保存到临时目录
        :return: 下载成功返回本地文件路径，失败返回None
        """
        try:
            detail = self.get_item(Path(fileitem.path))
            if not detail or not detail.pickcode:
                logger.error(f"【123】获取文件详情失败: {fileitem.name}")
                return None
            json_obj = ast.literal_eval(detail.pickcode)
            payload = {
                "Etag": json_obj["Etag"],
                "FileID": int(detail.fileid),
                "FileName": detail.name,
                "S3KeyFlag": json_obj["S3KeyFlag"],
                "Size": int(json_obj["Size"]),
            }
            resp = self.client.download_info(payload)
            check_response(resp)
            download_url = resp["data"]["DownloadUrl"]
            local_path = _build_download_path(fileitem, path or settings.TEMP_PATH)
            if not local_path:
                logger.error(f"【123】下载文件名无效: {fileitem.name}")
                return None
        except Exception as e:
            logger.error(f"【123】获取下载链接失败: {fileitem.name} - {str(e)}")
            return None

        # 获取文件大小
        file_size = detail.size

        # 初始化进度条
        logger.info(f"【123】开始下载: {fileitem.name} -> {local_path}")
        progress_callback = transfer_process(Path(fileitem.path).as_posix())

        try:
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                downloaded_size = 0

                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=10 * 1024 * 1024):
                        if global_vars.is_transfer_stopped(fileitem.path):
                            logger.info(f"【123】{fileitem.path} 下载已取消！")
                            raise InterruptedError
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            # 更新进度
                            if file_size:
                                progress = (downloaded_size * 100) / file_size
                                progress_callback(progress)

                # 完成下载
                progress_callback(100)
                logger.info(f"【123】下载完成: {fileitem.name}")

        except InterruptedError:
            if local_path.exists():
                local_path.unlink()
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"【123】下载网络错误: {fileitem.name} - {str(e)}")
            if local_path.exists():
                local_path.unlink()
            return None
        except Exception as e:
            logger.error(f"【123】下载失败: {fileitem.name} - {str(e)}")
            if local_path.exists():
                local_path.unlink()
            return None

        return local_path

    def upload(
        self,
        target_dir: schemas.FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[schemas.FileItem]:
        """
        上传文件到云盘
        支持秒传、分块上传和普通上传，自动根据文件大小选择上传方式

        :param target_dir: 上传目标目录项
        :param local_path: 本地文件路径
        :param new_name: 上传后的文件名，如果为None则使用本地文件名
        :return: 上传成功返回文件项，失败返回None
        """
        if not local_path.exists() or not local_path.is_file():
            logger.error(f"【123】本地文件不存在或非文件: {local_path}")
            return None

        cancel_path = local_path.as_posix()
        if global_vars.is_transfer_stopped(cancel_path):
            logger.info(f"【123】{local_path} 上传已取消！")
            return None

        target_name = new_name or local_path.name
        target_path = Path(target_dir.path) / target_name

        file_size = local_path.stat().st_size

        logger.debug(f"【123】{local_path} 开始计算 md5 值...")
        file_md5 = ""
        with open(local_path, "rb") as f:
            hash_md5 = md5()
            for chunk in iter(lambda: f.read(4096), b""):
                if global_vars.is_transfer_stopped(cancel_path):
                    logger.info(f"【123】{local_path} 上传已取消！")
                    return None
                hash_md5.update(chunk)
            file_md5 = hash_md5.hexdigest()

        try:
            # 秒传文件
            resp = self.client.upload_request(
                {
                    "etag": file_md5,
                    "fileName": target_name,
                    "size": file_size,
                    "parentFileId": int(target_dir.fileid),
                    "type": 0,
                    "duplicate": 2,
                }
            )
            check_response(resp)
            if resp.get("data").get("Reuse"):
                logger.info(f"【123】{target_name} 秒传成功")
                logger.debug(resp)
                data = resp.get("data", {}).get("Info", {})
                return schemas.FileItem(
                    storage=self._disk_name,
                    fileid=str(data["FileId"]),
                    path=str(target_path) + ("/" if data["Type"] == 1 else ""),
                    type="file" if data["Type"] == 0 else "dir",
                    name=data["FileName"],
                    basename=Path(data["FileName"]).stem,
                    extension=Path(data["FileName"]).suffix[1:]
                    if data["Type"] == 0
                    else None,
                    pickcode=str(data),
                    size=data["Size"] if data["Type"] == 0 else None,
                    modify_time=int(
                        datetime.fromisoformat(data["UpdateAt"]).timestamp()
                    ),
                )
        except Exception as e:
            logger.error(f"【123】{target_name} 秒传出现未知错误：{e}")
            return None

        try:
            # 上传信息
            upload_data = resp["data"]
            # 分块大小
            slice_size = int(upload_data["SliceSize"])

            upload_request_kwargs = {
                "method": "PUT",
                "headers": {"authorization": ""},
                "parse": ...,
                "timeout": 300,  # 设置5分钟超时
            }

            if file_size > slice_size:
                # 大文件分块上传
                logger.info(
                    f"【123】开始上传: {local_path} -> {target_path}，分片大小：{StringUtils.str_filesize(slice_size)}"
                )
                # 初始化进度条
                progress_callback = transfer_process(cancel_path)

                with open(local_path, "rb") as f:
                    slice_no = 1
                    offset = 0
                    for chunk in iter(lambda: f.read(slice_size), b""):
                        if global_vars.is_transfer_stopped(cancel_path):
                            logger.info(f"【123】{local_path} 上传已取消！")
                            return None

                        if not chunk:
                            break

                        num_to_upload = min(slice_size, file_size - offset)

                        # 准备分片信息
                        upload_data["partNumberStart"] = slice_no
                        upload_data["partNumberEnd"] = slice_no + 1
                        upload_url_resp = self.client.upload_prepare(
                            upload_data,
                        )
                        check_response(upload_url_resp)

                        logger.info(
                            f"【123】开始上传 {target_name} 分片 {slice_no}: {offset} -> {offset + num_to_upload}"
                        )
                        logger.debug(f"{upload_url_resp} {upload_data}")

                        # 上传分片，失败时重试5次，每次重新获取上传URL
                        max_retries = 6
                        retry_count = 0
                        upload_success = False
                        current_upload_url_resp = upload_url_resp

                        while retry_count < max_retries and not upload_success:
                            if global_vars.is_transfer_stopped(cancel_path):
                                logger.info(f"【123】{local_path} 上传已取消！")
                                return None
                            try:
                                self.client.request(
                                    current_upload_url_resp["data"]["presignedUrls"][
                                        str(slice_no)
                                    ],
                                    data=chunk,
                                    **upload_request_kwargs,
                                )
                                upload_success = True
                            except Exception as upload_err:
                                retry_count += 1
                                if retry_count < max_retries:
                                    logger.warning(
                                        f"【123】{target_name} 分片 {slice_no} "
                                        f"上传失败，正在重试 ({retry_count}/{max_retries}): {upload_err}"
                                    )
                                    for _ in range(10):
                                        time.sleep(1)
                                        if global_vars.is_transfer_stopped(cancel_path):
                                            logger.info(
                                                f"【123】{local_path} 上传已取消！"
                                            )
                                            return None

                                    # 重新获取上传URL
                                    try:
                                        logger.info(
                                            f"【123】重新获取分片 {slice_no} 的上传URL"
                                        )
                                        current_upload_url_resp = (
                                            self.client.upload_prepare(
                                                upload_data,
                                            )
                                        )
                                        check_response(current_upload_url_resp)
                                    except Exception as url_err:
                                        logger.error(
                                            f"【123】重新获取上传URL失败: {url_err}"
                                        )
                                        raise
                                else:
                                    logger.error(
                                        f"【123】{target_name} 分片 {slice_no} 上传失败，已达到最大重试次数: {upload_err}"
                                    )
                                    raise
                        slice_no += 1
                        offset += num_to_upload

                        # 更新进度
                        progress = (offset * 100) / file_size
                        progress_callback(progress)

                # 完成上传
                progress_callback(100)
            else:
                # 小文件直接上传
                logger.info(f"【123】开始上传: {local_path} -> {target_path}")

                resp = self.client.upload_auth(
                    upload_data,
                )
                check_response(resp)

                # 上传文件，失败时重试6次，每次重新获取上传URL
                max_retries = 6
                retry_count = 0
                upload_success = False
                current_resp = resp

                with open(local_path, "rb") as f:
                    file_data = f.read()

                if global_vars.is_transfer_stopped(cancel_path):
                    logger.info(f"【123】{local_path} 上传已取消！")
                    return None

                while retry_count < max_retries and not upload_success:
                    if global_vars.is_transfer_stopped(cancel_path):
                        logger.info(f"【123】{local_path} 上传已取消！")
                        return None
                    try:
                        self.client.request(
                            current_resp["data"]["presignedUrls"]["1"],
                            data=file_data,
                            **upload_request_kwargs,
                        )
                        upload_success = True
                    except Exception as upload_err:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(
                                f"【123】{target_name} 上传失败，正在重试 ({retry_count}/{max_retries}): {upload_err}"
                            )
                            for _ in range(10):
                                time.sleep(1)
                                if global_vars.is_transfer_stopped(cancel_path):
                                    logger.info(f"【123】{local_path} 上传已取消！")
                                    return None

                            # 重新获取上传URL
                            try:
                                logger.info("【123】重新获取上传URL")
                                current_resp = self.client.upload_auth(
                                    upload_data,
                                )
                                check_response(current_resp)
                            except Exception as url_err:
                                logger.error(f"【123】重新获取上传URL失败: {url_err}")
                                raise
                        else:
                            logger.error(
                                f"【123】{target_name} 上传失败，已达到最大重试次数: {upload_err}"
                            )
                            raise

            upload_data["isMultipart"] = file_size > slice_size
            complete_resp = self.client.upload_complete(
                upload_data,
            )
            check_response(complete_resp)

            data = complete_resp.get("data", {}).get("file_info", {})
            return schemas.FileItem(
                storage=self._disk_name,
                fileid=str(data["FileId"]),
                path=str(target_path) + ("/" if data["Type"] == 1 else ""),
                type="file" if data["Type"] == 0 else "dir",
                name=data["FileName"],
                basename=Path(data["FileName"]).stem,
                extension=Path(data["FileName"]).suffix[1:]
                if data["Type"] == 0
                else None,
                pickcode=str(data),
                size=data["Size"] if data["Type"] == 0 else None,
                modify_time=int(datetime.fromisoformat(data["UpdateAt"]).timestamp()),
            )
        except Exception as e:
            logger.error(f"【123】{target_name} 上传出现未知错误：{e}")
            return None

    def detail(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取文件详情

        :param fileitem: 文件项
        :return: 包含详细信息的文件项，如果获取失败则返回None
        """
        return self.get_item(Path(fileitem.path))

    def _find_copied_item(
        self,
        target_dir: schemas.FileItem,
        known_ids: Set[str],
        source_item: schemas.FileItem,
        max_attempts: int = 12,
    ) -> Optional[schemas.FileItem]:
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
                time.sleep(0.5)
        return None

    def copy(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        复制文件或目录到目标位置

        :param fileitem: 要复制的文件项
        :param path: 目标目录路径
        :param new_name: 复制后的新文件名
        :return: 复制成功返回True，失败返回False
        """
        try:
            parent_id = self._path_to_id(str(path))
            target_path = path.as_posix().rstrip("/") or "/"
            if target_path != "/":
                target_path = target_path + "/"
            target_dir = schemas.FileItem(
                storage=self._disk_name,
                fileid=str(parent_id),
                path=target_path,
                name=path.name if target_path != "/" else "",
                basename=path.name if target_path != "/" else "",
                type="dir",
            )
            existing_items = self.list(target_dir)
            if existing_items is None:
                return False
            known_ids = {item.fileid for item in existing_items if item.fileid}
            resp = self.client.fs_copy(fileitem.fileid, parent_id=parent_id)
            check_response(resp)
            logger.debug(f"【123】复制文件: {resp}")
            new_item = self._find_copied_item(
                target_dir=target_dir,
                known_ids=known_ids,
                source_item=fileitem,
            )
            if not new_item:
                logger.error(f"【123】复制后未找到新增对象: {fileitem.path}")
                return False
            if new_item.name != new_name and not self.rename(new_item, new_name):
                return False
            self._id_cache[(Path(path) / new_name).as_posix()] = str(new_item.fileid)
            return True
        except Exception:
            return False

    def move(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        移动文件或目录到目标位置

        :param fileitem: 要移动的文件项
        :param path: 目标目录路径
        :param new_name: 移动后的新文件名
        :return: 移动成功返回True，失败返回False
        """
        try:
            resp = self.client.fs_move(
                fileitem.fileid, parent_id=self._path_to_id(str(path))
            )
            check_response(resp)
            logger.debug(f"【123】移动文件: {resp}")
            self._invalidate_path_cache(fileitem.path)
            new_path = Path(path) / fileitem.name
            new_item = self.get_item(new_path)
            if not new_item:
                return False
            if new_item.name != new_name and not self.rename(new_item, new_name):
                return False
            self._id_cache[(Path(path) / new_name).as_posix()] = str(new_item.fileid)
            return True
        except Exception:
            return False

    def link(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        硬链接文件
        云盘存储不支持硬链接操作

        :param fileitem: 文件项
        :param target_file: 目标文件路径
        :return: 始终返回False，表示不支持此操作
        """
        return False

    def softlink(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        软链接文件
        云盘存储不支持软链接操作

        :param fileitem: 文件项
        :param target_file: 目标文件路径
        :return: 始终返回False，表示不支持此操作
        """
        return False

    def usage(self) -> Optional[schemas.StorageUsage]:
        """
        获取存储使用情况

        :return: 存储使用情况对象，包含总容量和可用容量，获取失败返回None
        """
        try:
            resp = self.client.user_info()
            check_response(resp)
            return schemas.StorageUsage(
                total=resp["data"]["SpacePermanent"],
                available=int(resp["data"]["SpacePermanent"])
                - int(resp["data"]["SpaceUsed"]),
            )
        except Exception:
            return None

    def support_transtype(self) -> dict:
        """
        支持的整理方式

        :return: 支持的整理方式字典
        """
        return self.transtype

    def is_support_transtype(self, transtype: str) -> bool:
        """
        是否支持整理方式

        :param transtype: 整理方式 (move/copy)

        :return: 是否支持
        """
        return transtype in self.transtype
