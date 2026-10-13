from typing import Any, Dict, Optional

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .. import P115StrmHelperBase


class TransferPostprocess(P115StrmHelperBase):
    """
    整理完成事件的固定执行计划及恢复检查点
    """

    __tablename__ = "transfer_postprocess"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)


class TransferResource(P115StrmHelperBase):
    """
    本地文件最近一次后处理归属及删除墓碑
    """

    __tablename__ = "transfer_resource"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    identity: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
