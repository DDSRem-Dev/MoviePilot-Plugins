from typing import Dict, List, Set

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    BigInteger,
    select,
    delete,
    and_,
    update,
    func,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ...db_manager import db_update, db_query, P115StrmHelperBase


class File(P115StrmHelperBase):
    """
    文件类
    """

    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, nullable=False)
    name = Column(String(255), default="")
    sha1 = Column(String(40), default="")
    size = Column(BigInteger, default=0)
    pickcode = Column(String(50), default="")
    ctime = Column(BigInteger, default=0)
    mtime = Column(BigInteger, default=0)
    path = Column(Text, unique=True)
    extra = Column(Text)

    @staticmethod
    @db_query
    def get_by_path(db: Session, file_path: str):
        """
        通过路径获取（当路径不唯一报错 MultipleResultsFound）

        :param db (Session): 数据库会话
        :param file_path (str): 文件路径
        """
        return db.execute(
            select(File).where(File.path == file_path)
        ).scalar_one_or_none()

    @staticmethod
    @db_query
    def get_by_id(db: Session, file_id: int):
        """
        通过ID获取

        :param db (Session): 数据库会话
        :param file_id (int): 文件 ID
        """
        return db.scalars(select(File).where(File.id == file_id)).first()

    @staticmethod
    @db_query
    def get_by_parent_id(db: Session, parent_id: int):
        """
        通过parent_id获取

        :param db (Session): 数据库会话
        :param parent_id (int): 父目录 ID
        """
        return (
            db.execute(select(File).where(File.parent_id == parent_id)).scalars().all()
        )

    @staticmethod
    @db_update
    def delete_by_path(db: Session, file_path: str):
        """
        通过路径删除（删除所有匹配值）

        :param db (Session): 数据库会话
        :param file_path (str): 文件路径
        """
        db.execute(delete(File).where(File.path == file_path))
        return True

    @staticmethod
    @db_update
    def delete_by_id(db: Session, file_id: int):
        """
        通过ID删除

        :param db (Session): 数据库会话
        :param file_id (int): 文件 ID
        """
        db.execute(delete(File).where(File.id == file_id))
        return True

    @staticmethod
    @db_update
    def upsert_batch_by_list(db: Session, batch: List[Dict]):
        """
        通过列表批量写入或更新数据

        :param db (Session): 数据库会话
        :param batch (List): 待写入的数据列表
        """
        stmt = sqlite_insert(File).prefix_with("OR REPLACE")
        db.execute(stmt, batch)
        return True

    @staticmethod
    @db_update
    def remove_by_path_batch(db: Session, path: str):
        """
        通过路径批量删除

        :param db (Session): 数据库会话
        :param path (str): 路径前缀
        """
        db.execute(delete(File).where(File.path.startswith(path)))
        return True

    @staticmethod
    @db_update
    def update_path(db: Session, file_id: int, new_path: str):
        """
        更新指定ID的路径

        :param db (Session): 数据库会话
        :param file_id (int): 文件 ID
        :param new_path (str): 新路径
        """
        db.query(File).filter(File.id == file_id).update(
            {"path": new_path}, synchronize_session=False
        )

    @staticmethod
    @db_update
    def update_name(db: Session, file_id: int, new_name: str):
        """
        更新指定ID的名称

        :param db (Session): 数据库会话
        :param file_id (int): 文件 ID
        :param new_name (str): 新名称
        """
        db.query(File).filter(File.id == file_id).update({"name": new_name})

    @staticmethod
    @db_update
    def update_path_prefix(db: Session, old_prefix: str, new_prefix: str):
        """
        批量更新以 old_prefix 开头的路径

        :param db (Session): 数据库会话
        :param old_prefix (str): 旧的路径前缀
        :param new_prefix (str): 新的路径前缀
        """
        db.execute(
            update(File)
            .where(File.path.startswith(old_prefix))
            .values(path=func.replace(File.path, old_prefix, new_prefix))
        )
        return True

    @staticmethod
    @db_update
    def remove_by_path_prefix_not_in_ids(
        db: Session, path_prefix: str, ids: Set[int]
    ) -> int:
        """
        删除路径前缀匹配但 ID 不在给定集合中的记录，返回实际删除行数

        :param db (Session): 数据库会话
        :param path_prefix (str): 路径前缀
        :param ids (Set): 需要保留的 ID 集合
        """
        all_ids = set(
            db.execute(select(File.id).where(File.path.startswith(path_prefix)))
            .scalars()
            .all()
        )
        ghost_ids = list(all_ids - ids)
        if not ghost_ids:
            return 0
        deleted = 0
        for i in range(0, len(ghost_ids), 900):
            chunk = ghost_ids[i : i + 900]
            result = db.execute(delete(File).where(File.id.in_(chunk)))
            deleted += result.rowcount
        return deleted

    @staticmethod
    @db_query
    def get_any_pickcode(db: Session):
        """
        获取任意一条 pickcode 不为空的记录的 pickcode

        :param db (Session): 数据库会话
        """
        stmt = (
            select(File.pickcode)
            .where(and_(File.pickcode != "", File.pickcode.isnot(None)))
            .limit(1)
        )
        result = db.scalar(stmt)
        return result
