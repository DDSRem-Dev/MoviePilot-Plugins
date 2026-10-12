from typing import Optional, Set, List, Dict

from sqlalchemy import Integer, BigInteger, String, Text, select
from sqlalchemy.orm import Session, Mapped, mapped_column

from ...db_manager import P115StrmHelperBase, db_query, db_update
from ...db_manager.replace import replace_rows


class OpenFolder(P115StrmHelperBase):
    """
    Open 文件夹类
    """

    __tablename__ = "open_folders"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), primary_key=True
    )
    parent_id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), default="", nullable=True)
    path: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)

    @staticmethod
    @db_query
    def get_all_id(db: Session) -> Set[int]:
        """
        获取所有 ID

        :param db (Session): 数据库会话

        :return Set: ID 集合
        """
        stmt = select(OpenFolder.id)
        return set(db.scalars(stmt).all())

    @staticmethod
    @db_update
    def upsert_batch_by_list(db: Session, batch: List[Dict]) -> None:
        """
        通过列表批量写入或更新数据

        :param db (Session): 数据库会话
        :param batch (List): 待写入的数据列表
        """
        replace_rows(db, OpenFolder, batch)

    @staticmethod
    @db_query
    def get_by_id(db: Session, folder_id: int) -> Optional["OpenFolder"]:
        """
        通过ID获取

        :param db (Session): 数据库会话
        :param folder_id (int): 文件夹 ID

        :return OpenFolder: 匹配的文件夹模型实例，未找到返回 None
        """
        return db.scalars(select(OpenFolder).where(OpenFolder.id == folder_id)).first()
