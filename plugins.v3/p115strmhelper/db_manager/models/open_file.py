from typing import Optional, Set, List, Dict

from sqlalchemy import Integer, String, BigInteger, Text, select
from sqlalchemy.orm import Session, Mapped, mapped_column

from ...db_manager import P115StrmHelperBase, db_query, db_update
from ...db_manager.replace import replace_rows


class OpenFile(P115StrmHelperBase):
    """
    Open 文件类
    """

    __tablename__ = "open_files"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), primary_key=True
    )
    parent_id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), default="", nullable=True)
    sha1: Mapped[Optional[str]] = mapped_column(String(40), default="", nullable=True)
    size: Mapped[Optional[int]] = mapped_column(BigInteger, default=0, nullable=True)
    pick_code: Mapped[Optional[str]] = mapped_column(
        String(50), default="", nullable=True
    )
    ico: Mapped[Optional[str]] = mapped_column(String(40), default="", nullable=True)
    ctime: Mapped[Optional[int]] = mapped_column(BigInteger, default=0, nullable=True)
    mtime: Mapped[Optional[int]] = mapped_column(BigInteger, default=0, nullable=True)
    utime: Mapped[Optional[int]] = mapped_column(BigInteger, default=0, nullable=True)
    file_type: Mapped[Optional[int]] = mapped_column(
        BigInteger, default=0, nullable=True
    )
    type: Mapped[Optional[int]] = mapped_column(BigInteger, default=0, nullable=True)
    path: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, default="", nullable=True)

    @staticmethod
    @db_query
    def get_all_id(db: Session) -> Set[int]:
        """
        获取所有 ID

        :param db (Session): 数据库会话

        :return Set: ID 集合
        """
        stmt = select(OpenFile.id)
        return set(db.scalars(stmt).all())

    @staticmethod
    @db_update
    def upsert_batch_by_list(db: Session, batch: List[Dict]) -> None:
        """
        通过列表批量写入或更新数据

        :param db (Session): 数据库会话
        :param batch (List): 待写入的数据列表
        """
        replace_rows(db, OpenFile, batch)

    @staticmethod
    @db_query
    def get_by_ids(db: Session, ids: Set[int]) -> List["OpenFile"]:
        """
        通过一组 ID 获取一组文件信息

        :param db (Session): 数据库会话
        :param ids (Set): 文件 ID 集合

        :return List: 匹配的文件信息列表
        """
        if not ids:
            return []
        stmt = select(OpenFile).where(OpenFile.id.in_(ids))
        return list(db.scalars(stmt).all())
