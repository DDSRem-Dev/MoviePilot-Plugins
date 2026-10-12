from typing import Optional, List, Dict

from sqlalchemy import Integer, String, BigInteger, select
from sqlalchemy.orm import Session, Mapped, mapped_column

from ...db_manager import db_update, db_query, P115StrmHelperBase
from ...db_manager.replace import replace_rows


class LifeEvent(P115StrmHelperBase):
    """
    生活事件表
    """

    __tablename__ = "life_event"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), primary_key=True
    )
    type: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    file_id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), nullable=False, index=True
    )
    parent_id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), nullable=False, index=True
    )
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255), default="", nullable=True
    )
    file_category: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    file_size: Mapped[Optional[int]] = mapped_column(
        BigInteger, default=0, nullable=True
    )
    sha1: Mapped[Optional[str]] = mapped_column(String(40), default="", nullable=True)
    pick_code: Mapped[Optional[str]] = mapped_column(
        String(50), default="", nullable=True
    )
    update_time: Mapped[Optional[int]] = mapped_column(
        BigInteger, default=0, nullable=True
    )
    create_time: Mapped[Optional[int]] = mapped_column(
        BigInteger, default=0, nullable=True
    )

    @staticmethod
    @db_update
    def upsert_batch_by_list(db: Session, batch: List[Dict]) -> bool:
        """
        通过列表批量写入或更新数据

        :param db (Session): 数据库会话
        :param batch (List): 待写入的数据列表

        :return bool: 始终返回 True
        """
        replace_rows(db, LifeEvent, batch)
        return True

    @staticmethod
    @db_query
    def get_by_id(db: Session, file_id: int) -> Optional["LifeEvent"]:
        """
        通过ID获取

        :param db (Session): 数据库会话
        :param file_id (int): 记录 ID

        :return LifeEvent: 匹配的生活事件模型实例，未找到返回 None
        """
        return db.scalars(select(LifeEvent).where(LifeEvent.id == file_id)).first()

    @staticmethod
    @db_query
    def get_by_file_id(db: Session, file_id: int) -> List["LifeEvent"]:
        """
        通过 file_id 获取

        :param db (Session): 数据库会话
        :param file_id (int): 文件 ID

        :return List: 匹配的生活事件列表
        """
        return db.scalars(select(LifeEvent).where(LifeEvent.file_id == file_id)).all()

    @staticmethod
    @db_query
    def get_by_type(db: Session, type_id: int) -> List["LifeEvent"]:
        """
        通过 type 获取

        :param db (Session): 数据库会话
        :param type_id (int): 事件类型 ID

        :return List: 匹配的生活事件列表
        """
        return db.scalars(select(LifeEvent).where(LifeEvent.type == type_id)).all()
