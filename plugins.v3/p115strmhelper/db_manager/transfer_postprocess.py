from copy import deepcopy
from hashlib import sha256
from os.path import normcase
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import func, select

from . import ct_db_manager
from .models.transfer_postprocess import TransferPostprocess, TransferResource


def resource_key(path: Path) -> str:
    """
    将本地规范路径转换为跨数据库可索引的资源键
    """
    return sha256(normcase(str(path.resolve())).encode("utf-8")).hexdigest()


class TransferPostprocessStore:
    """
    使用当前插件实例的宿主数据库持久化后处理状态
    """

    def __init__(self) -> None:
        self._handle = ct_db_manager.get_database()

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """
        读取脱离数据库会话的事件快照
        """
        with self._handle.session() as db:
            record = db.get(TransferPostprocess, key)
            if record is None:
                return None
            return {"state": record.state, "plan": deepcopy(record.plan)}

    def save(self, key: str, plan: Dict[str, Any], state: str = "pending") -> None:
        """
        在文件副作用前后提交独立检查点
        """
        with self._handle.session() as db:
            db.merge(TransferPostprocess(key=key, state=state, plan=deepcopy(plan)))
            db.commit()

    def list_records(
        self, state: str = "unfinished", page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """
        分页查询当前实例的事件摘要，避免返回完整执行计划

        :param state (str): unfinished、all 或具体事件状态
        :param page (int): 从 1 开始的页码
        :param page_size (int): 每页记录数，最多 100 条

        :return Dict: 事件摘要列表、总数和分页信息
        """
        if state not in {"unfinished", "all", "pending", "superseded", "done"}:
            raise ValueError("无效的后处理状态")
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("无效的分页参数")
        conditions = []
        if state == "unfinished":
            conditions.append(TransferPostprocess.state.in_(("pending", "superseded")))
        elif state != "all":
            conditions.append(TransferPostprocess.state == state)
        with self._handle.session() as db:
            total = db.scalar(
                select(func.count()).select_from(TransferPostprocess).where(*conditions)
            )
            records = db.scalars(
                select(TransferPostprocess)
                .where(*conditions)
                .order_by(TransferPostprocess.key)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = []
            for record in records:
                plan = record.plan
                identity = plan.get("identity", {})
                operations = plan.get("operations", [])
                items.append(
                    {
                        "key": record.key,
                        "state": record.state,
                        "cloud_path": identity.get("path"),
                        "local_path": operations[0].get("path") if operations else None,
                        "size": identity.get("size"),
                        "reason": plan.get("superseded_reason"),
                    }
                )
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def owner(self, path: Path) -> Optional[Dict[str, Any]]:
        """
        读取本地路径的最近归属，删除后的墓碑继续保留
        """
        with self._handle.session() as db:
            record = db.get(TransferResource, resource_key(path))
            if record is None:
                return None
            return {
                "event_key": record.event_key,
                "identity": deepcopy(record.identity),
                "fingerprint": deepcopy(record.fingerprint),
            }

    def complete_file(
        self, key: str, plan: Dict[str, Any], operation: Dict[str, Any]
    ) -> None:
        """
        原子提交文件归属与该操作的完成检查点
        """
        path = Path(operation["path"])
        with self._handle.session() as db:
            db.merge(
                TransferResource(
                    key=resource_key(path),
                    path=str(path.resolve()),
                    event_key=key,
                    identity=operation["identity"],
                    fingerprint=operation.get("after"),
                )
            )
            db.merge(TransferPostprocess(key=key, state="pending", plan=deepcopy(plan)))
            db.commit()
