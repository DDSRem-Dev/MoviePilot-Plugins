from copy import deepcopy
from hashlib import sha256
from os.path import normcase
from pathlib import Path
from typing import Any, Dict, Optional

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
