from time import localtime, strftime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.log import logger

from ..config import configer


PLUGIN_DATA_KEY = "strm_sync_exec_history"
MAX_RECORDS = 500


class StrmExecHistoryManager:
    """
    STRM 全量/增量/分享等同步任务的执行历史读写
    """

    @classmethod
    def append_run(
        cls,
        *,
        kind: str,
        success: bool,
        stats: Dict[str, Any],
        elapsed_sec: float,
        total_iterated: int,
        api_requests: int,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        追加一条执行记录（自动生成 unique、finished_at）

        :param kind: full / increment / share / share_interactive / full_partial 等
        :param success: 是否成功完成
        :param stats: strm 与 mediainfo 等计数
        :param elapsed_sec: 耗时（秒）
        :param total_iterated: 迭代条目数
        :param api_requests: API 请求次数（非增量场景可为 0）
        :param error: 失败时的错误摘要
        :param extra: 可选扩展字段
        """
        record: Dict[str, Any] = {
            "unique": str(uuid4()),
            "kind": kind,
            "finished_at": strftime("%Y-%m-%d %H:%M:%S", localtime()),
            "success": success,
            "error": error if not success else None,
            "elapsed_sec": float(elapsed_sec),
            "total_iterated": int(total_iterated),
            "api_requests": int(api_requests),
            "stats": stats,
        }
        if extra:
            record["extra"] = extra
        cls.append(record)

    @classmethod
    def append(cls, record: Dict[str, Any]) -> None:
        """
        追加一条完整记录（需已含 schema 约定字段；若缺 unique 则补全）

        :param record: 历史记录字典
        """
        try:
            if not record.get("unique"):
                record = {**record, "unique": str(uuid4())}
            history: List[Dict[str, Any]] = (
                configer.get_plugin_data(key=PLUGIN_DATA_KEY) or []
            )
            if not isinstance(history, list):
                history = []
            history.append(record)
            while len(history) > MAX_RECORDS:
                history.pop(0)
            configer.save_plugin_data(key=PLUGIN_DATA_KEY, value=history)
        except Exception as e:
            logger.error(f"【STRM执行历史】保存失败: {e}")

    @classmethod
    def list_records(
        cls,
        page: int = 1,
        limit: int = 20,
        kind: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        按完成时间倒序分页列出记录

        :param page: 页码（从 1 开始）
        :param limit: 每页条数；-1 表示全部
        :param kind: 若指定则只保留该 kind
        :return: (总数, 当前页列表)
        """
        history: List[Dict[str, Any]] = (
            configer.get_plugin_data(key=PLUGIN_DATA_KEY) or []
        )
        if not isinstance(history, list):
            history = []
        if kind:
            history = [h for h in history if h.get("kind") == kind]
        history = sorted(history, key=lambda x: x.get("finished_at", ""), reverse=True)
        total = len(history)
        if limit == -1:
            return total, history
        start = (page - 1) * limit
        end = start + limit
        return total, history[start:end]

    @classmethod
    def delete_one(cls, unique: str) -> None:
        """
        按 unique 删除单条记录

        :param unique: 记录唯一 ID
        """
        try:
            history: List[Dict[str, Any]] = (
                configer.get_plugin_data(key=PLUGIN_DATA_KEY) or []
            )
            if not isinstance(history, list):
                return
            history = [h for h in history if h.get("unique") != unique]
            configer.save_plugin_data(key=PLUGIN_DATA_KEY, value=history)
        except Exception as e:
            logger.error(f"【STRM执行历史】删除单条失败: {e}")

    @classmethod
    def clear_all(cls) -> None:
        """
        清空全部 STRM 执行历史
        """
        try:
            configer.save_plugin_data(key=PLUGIN_DATA_KEY, value=[])
        except Exception as e:
            logger.error(f"【STRM执行历史】清空失败: {e}")
