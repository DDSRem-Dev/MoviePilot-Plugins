from typing import Dict, Optional, List, Set
from pathlib import Path

from . import DbOper
from .models.folder import Folder
from .models.file import File
from ..utils.exception import PathNotInKey

from app.schemas import FileItem


class FileDbHelper(DbOper):
    """
    文件类数据库操作
    """

    @staticmethod
    def process_item(item: Dict) -> List[Dict]:
        """
        处理单个规范化项目，分离文件夹和文件数据

        :param item (Dict): 规范化后的文件或文件夹信息，必须包含 path 键

        :return List: 处理后的数据列表，每项包含 table 和 data 字段

        :raises PathNotInKey: 当 item 中缺少 path 键时抛出
        """
        if not item.get("path"):
            raise PathNotInKey("键中不包含 path 项")

        results = []
        ancestors = item.get("ancestors", [])

        for i, ancestor in enumerate(ancestors[1:-1], start=1):
            path = "/" + "/".join(a["name"] for a in ancestors[1 : i + 1])
            results.append(
                {
                    "table": "folders",
                    "data": {
                        "id": ancestor["id"],
                        "parent_id": ancestor["parent_id"],
                        "name": ancestor["name"],
                        "path": path,
                    },
                }
            )

        if item["is_dir"]:
            results.append(
                {
                    "table": "folders",
                    "data": {
                        "id": item["id"],
                        "parent_id": item["parent_id"],
                        "name": item["name"],
                        "path": item["path"],
                    },
                }
            )
            return results

        results.append(
            {
                "table": "files",
                "data": {
                    "id": item["id"],
                    "parent_id": item["parent_id"],
                    "name": item["name"],
                    "sha1": item.get("sha1", ""),
                    "size": item.get("size", 0),
                    "pickcode": item.get("pickcode", item.get("pick_code", "")),
                    "ctime": item.get("ctime", 0),
                    "mtime": item.get("mtime", 0),
                    "path": item.get("path"),
                    "extra": str(item) if item else None,
                },
            }
        )

        return results

    @staticmethod
    def process_life_file_item(event, file_path: str) -> List[Dict]:
        """
        处理115生活事件文件 event

        :param event (Dict): 115 生活事件中的文件数据
        :param file_path (str): 文件路径

        :return List: 处理后的数据列表
        """
        return [
            {
                "table": "files",
                "data": {
                    "id": event["file_id"],
                    "parent_id": event["parent_id"],
                    "name": event["file_name"],
                    "sha1": event.get("sha1", ""),
                    "size": event.get("file_size", 0),
                    "pickcode": event.get("pick_code", ""),
                    "ctime": event.get("create_time", 0),
                    "mtime": event.get("update_time", 0),
                    "path": str(file_path),
                    "extra": str(event),
                },
            }
        ]

    @staticmethod
    def process_life_dir_item(event, file_path: str) -> List[Dict]:
        """
        处理115生活事件文件夹 event

        :param event (Dict): 115 生活事件中的文件夹数据
        :param file_path (str): 文件夹路径

        :return List: 处理后的数据列表
        """
        return [
            {
                "table": "folders",
                "data": {
                    "id": event["file_id"],
                    "parent_id": event["parent_id"],
                    "name": event["file_name"],
                    "path": str(file_path),
                },
            }
        ]

    @staticmethod
    def process_fs_files_item(item) -> List[Dict]:
        """
        处理115原始返回数据

        :param item (Dict): 115 原始 API 返回的文件或文件夹数据

        :return List: 处理后的数据列表

        :raises PathNotInKey: 当 item 中缺少 path 键时抛出
        """
        if not item.get("path"):
            raise PathNotInKey("键中不包含 path 项")

        if "fid" not in item:
            return [
                {
                    "table": "folders",
                    "data": {
                        "id": int(item.get("cid")),
                        "parent_id": int(item.get("pid")),
                        "name": item.get("n"),
                        "path": item.get("path"),
                    },
                }
            ]
        else:
            return [
                {
                    "table": "files",
                    "data": {
                        "id": int(item.get("fid")),
                        "parent_id": int(item.get("cid")),
                        "name": item.get("n"),
                        "sha1": item.get("sha"),
                        "size": item.get("s"),
                        "pickcode": item.get("pc"),
                        "ctime": item.get("tp", 0),
                        "mtime": item.get("tu", 0),
                        "path": item.get("path"),
                        "extra": str(item),
                    },
                }
            ]

    @staticmethod
    def process_fileitem(fileitem: Optional[FileItem]) -> List[Dict]:
        """
        处理MP fileitem 类型数据

        :param fileitem (FileItem): MoviePilot 的文件项对象

        :return List: 处理后的数据列表，fileitem 为空时返回空列表
        """
        if not fileitem:
            return []
        if fileitem.type == "file":
            return [
                {
                    "table": "files",
                    "data": {
                        "id": int(fileitem.fileid),
                        "parent_id": int(fileitem.parent_fileid)
                        if fileitem.parent_fileid is not None
                        else -1,
                        "name": fileitem.name,
                        "sha1": "",
                        "size": fileitem.size if fileitem.size is not None else -1,
                        "pickcode": fileitem.pickcode,
                        "ctime": 0,
                        "mtime": int(fileitem.modify_time),
                        "path": str(Path(fileitem.path)),
                        "extra": "",
                    },
                }
            ]
        else:
            return [
                {
                    "table": "folders",
                    "data": {
                        "id": int(fileitem.fileid),
                        "parent_id": int(fileitem.parent_fileid)
                        if fileitem.parent_fileid is not None
                        else -1,
                        "name": fileitem.name,
                        "path": str(Path(fileitem.path)),
                    },
                }
            ]

    def upsert_batch(self, batch: List[Dict]):
        """
        批量写入或更新数据

        :param batch (List): 待处理的数据列表，每项包含 table 和 data 字段

        :return bool: 操作成功返回 True
        """
        files_data_map = {
            entry["data"]["id"]: entry["data"]
            for entry in batch
            if entry.get("table") == "files" and "id" in entry.get("data", {})
        }

        if files_data_map:
            files_data = list(files_data_map.values())
            self.upsert_batch_by_list("files", files_data)

        folders_data_map = {
            entry["data"]["id"]: entry["data"]
            for entry in batch
            if entry.get("table") == "folders" and "id" in entry.get("data", {})
        }

        if folders_data_map:
            folders_data = list(folders_data_map.values())
            self.upsert_batch_by_list("folders", folders_data)

        return True

    def upsert_batch_by_list(self, list_type: str, batch: List[Dict]):
        """
        通过列表批量写入或更新数据

        :param list_type (str): 数据类型，files 或 folders
        :param batch (List): 待写入的数据列表

        :return bool: 操作成功返回 True
        """
        if list_type == "files":
            File.upsert_batch_by_list(self._db, batch)
        else:
            Folder.upsert_batch_by_list(self._db, batch)
        return True

    def get_by_path(self, path: str) -> Optional[Dict]:
        """
        通过路径获取项目

        :param path (str): 文件或文件夹路径

        :return Dict: 匹配的文件或文件夹信息字典，未找到返回 None
        """
        file = File.get_by_path(self._db, path)
        if file:
            return {
                **file.__dict__,
                "type": "file",
                "_sa_instance_state": None,
            }
        folder = Folder.get_by_path(self._db, path)
        if folder:
            return {**folder.__dict__, "type": "folder", "_sa_instance_state": None}
        return None

    def get_by_id(self, id: int) -> Optional[Dict]:
        """
        通过ID获取项目

        :param id (int): 文件或文件夹 ID

        :return Dict: 匹配的文件或文件夹信息字典，未找到返回 None
        """
        file = File.get_by_id(self._db, id)
        if file:
            return {
                **file.__dict__,
                "type": "file",
                "_sa_instance_state": None,
            }
        folder = Folder.get_by_id(self._db, id)
        if folder:
            return {**folder.__dict__, "type": "folder", "_sa_instance_state": None}
        return None

    def get_children(self, path: str) -> Dict:
        """
        获取路径下的所有子项

        :param path (str): 父目录路径

        :return Dict: 包含 files、subfolders 和 meta 信息的字典
        """
        parent = Folder.get_by_path(self._db, path)
        if not parent:
            return {"files": [], "subfolders": []}
        parent_id = parent.id

        files = File.get_by_parent_id(self._db, parent_id)
        subfolders = Folder.get_by_parent_id(self._db, parent_id)

        def clean_record(record):
            """
            清洗数据库记录，移除内部状态并添加类型标记

            :param record: File 或 Folder 的 ORM 实例

            :return dict: 清理后的字典
            """
            d = record.__dict__
            d.pop("_sa_instance_state", None)
            d["type"] = "file" if isinstance(record, File) else "folder"
            return d

        return {
            "files": [clean_record(f) for f in files],
            "subfolders": [clean_record(sf) for sf in subfolders],
            "meta": {
                "parent_path": path,
                "parent_id": parent_id,
                "total_count": len(files) + len(subfolders),
            },
        }

    def remove_by_path_batch(self, path: str, only_file: bool = False):
        """
        通过路径批量删除

        :param path (str): 要删除的路径前缀
        :param only_file (bool): 仅删除文件而不删除文件夹

        :return bool: 操作成功返回 True
        """
        File.remove_by_path_batch(self._db, path)
        if not only_file:
            Folder.remove_by_path_batch(self._db, path)
        return True

    def remove_by_id_batch(self, id: int, only_file: bool = False):
        """
        通过文件夹 ID 批量删除

        :param id (int): 文件夹 ID
        :param only_file (bool): 仅删除文件而不删除文件夹

        :return bool: 操作成功返回 True
        """
        folder = Folder.get_by_id(self._db, id)
        if not folder:
            return True
        path = folder.path
        File.remove_by_path_batch(self._db, path)
        if not only_file:
            Folder.remove_by_path_batch(self._db, path)
        return True

    def remove_by_path(self, path_type: str, path: str):
        """
        删除指定路径的记录

        :param path_type (str): 路径类型，file 或 folder
        :param path (str): 要删除的路径
        """
        if path_type == "file":
            File.delete_by_path(self._db, path)
        else:
            Folder.delete_by_path(self._db, path)

    def remove_by_id(self, id_type: str, id: int):
        """
        通过 ID 删除记录

        :param id_type (str): ID 类型，file 或 folder
        :param id (int): 要删除的记录 ID
        """
        if id_type == "file":
            File.delete_by_id(self._db, id)
        else:
            Folder.delete_by_id(self._db, id)

    def update_path_by_id(self, id: int, new_path: str) -> bool:
        """
        通过ID匹配数据并修改path

        :param id (int): 文件 ID
        :param new_path (str): 新的路径

        :return bool: 更新成功返回 True，项目不存在或类型不匹配返回 False
        """
        item = self.get_by_id(id)
        if not item:
            return False

        if item["type"] == "file":
            File.update_path(self._db, id, new_path)
        else:
            return False

        return True

    def update_name_by_id(self, id: int, new_name: str) -> bool:
        """
        通过ID匹配数据并修改name

        :param id (int): 文件 ID
        :param new_name (str): 新的名称

        :return bool: 更新成功返回 True，项目不存在或类型不匹配返回 False
        """
        item = self.get_by_id(id)
        if not item:
            return False

        if item["type"] == "file":
            File.update_name(self._db, id, new_name)
        else:
            return False

        return True

    def update_path_prefix_batch(
        self, old_prefix: str, new_prefix: str, only_file: bool = False
    ) -> bool:
        """
        批量更新以旧前缀开头的路径

        :param old_prefix (str): 旧的路径前缀
        :param new_prefix (str): 新的路径前缀
        :param only_file (bool): 仅更新文件而不更新文件夹

        :return bool: 操作成功返回 True
        """
        File.update_path_prefix(self._db, old_prefix, new_prefix)
        if not only_file:
            Folder.update_path_prefix(self._db, old_prefix, new_prefix)
        return True

    def remove_ghost_records(
        self, path_prefix: str, seen_file_ids: Set[int], seen_folder_ids: Set[int]
    ) -> int:
        """
        清除指定路径前缀下、未出现在本次扫描中的幽灵数据库记录，返回实际删除总行数

        :param path_prefix (str): 网盘路径前缀（末尾带 /）
        :param seen_file_ids (Set): 本次扫描到的文件 ID 集合
        :param seen_folder_ids (Set): 本次扫描到的目录 ID 集合

        :return int: 实际删除的总行数
        """
        file_count = File.remove_by_path_prefix_not_in_ids(
            self._db, path_prefix, seen_file_ids
        )
        folder_count = Folder.remove_by_path_prefix_not_in_ids(
            self._db, path_prefix, seen_folder_ids
        )
        return (file_count or 0) + (folder_count or 0)

    def get_any_pickcode(self) -> Optional[str]:
        """
        从文件表中任意获取一条 pickcode 不为空的数据的 pickcode

        :return str: pickcode 字符串，未找到返回 None
        """
        pickcode = File.get_any_pickcode(self._db)
        if pickcode:
            return pickcode

        return None
