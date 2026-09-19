from pathlib import Path
from time import time as time_unix
from typing import Any, Dict, List, Optional, Tuple

from app.schemas import NotificationType
from app.log import logger

from ....core.config import configer
from ....core.i18n import i18n
from ....core.message import post_message
from ....utils.path import PathRemoveUtils
from ....utils.sentry import sentry_manager


class StrmCleanupInteraction:
    """
    全量同步「失效 STRM」待删队列与 Telegram 二次确认交互

    通过模块级单例 ``strm_cleanup_interaction`` 使用，本模块不导出上述交互相关的模块级函数
    """

    _PENDING_KEY = "pending_strm_cleanup_batches"
    _CB_PREFIX = "p115scc"

    @staticmethod
    def _normalize_plugin_callback_text(text: str) -> str:
        """
        规范化 ``MessageAction`` 中的文本

        MoviePilot 在 ``message._handle_callback`` 里对 ``[PLUGIN]插件ID|内容`` 只拆一次 ``|``，
        转发给插件的 ``text`` 一般为「内容」部分（即 ``p115scc|...``）；若整段仍带 ``[PLUGIN]`` 则去掉
        """
        t = (text or "").strip()
        if t.startswith("CALLBACK:"):
            t = t[9:].strip()
        if not t.startswith("[PLUGIN]"):
            return t
        rest = t.split("|", 1)
        if len(rest) < 2:
            return t
        return rest[1].strip()

    def _parse_callback_text(self, raw: str) -> Optional[Tuple[str, bool]]:
        """
        解析 STRM 清理二次验证回调

        :param raw (str): 规范化后的回调文本，形如 p115scc|request_id|y 或 |n

        :return Optional[Tuple]: (request_id, True 为确认删除) 或 None
        """
        parts = raw.strip().split("|")
        if len(parts) != 3 or parts[0] != self._CB_PREFIX:
            return None
        if parts[2] not in ("y", "n"):
            return None
        return parts[1], parts[2] == "y"

    def _format_callback(self, request_id: str, approve: bool) -> str:
        """
        生成 Telegram 等渠道 inline 按钮 callback_data

        MoviePilot 仅当 callback_data 以 ``[PLUGIN]`` 开头时才会把回调转发为 ``MessageAction``；
        格式为 ``[PLUGIN]{PLUSIN_NAME}|`` + ``p115scc|request_id|y|n``（主站再拆成插件 ID 与 payload）
        Telegram 单键 callback_data 长度上限 64 字节，payload 须保持简短
        """
        payload = f"{self._CB_PREFIX}|{request_id}|{'y' if approve else 'n'}"
        return f"[PLUGIN]{configer.PLUSIN_NAME}|{payload}"

    def _load_store(self) -> Dict[str, Any]:
        raw = configer.get_plugin_data(self._PENDING_KEY)
        if not raw or not isinstance(raw, dict):
            return {"batches": []}
        batches = raw.get("batches")
        if not isinstance(batches, list):
            raw["batches"] = []
        return raw

    def _save_store(self, data: Dict[str, Any]) -> None:
        configer.save_plugin_data(self._PENDING_KEY, data)

    def append_batch(
        self,
        request_id: str,
        paths: List[str],
        remove_unless_file: bool,
        remove_unless_dir: bool,
    ) -> None:
        """
        追加一批待确认删除记录
        """
        store = self._load_store()
        batches: List[Dict[str, Any]] = store.get("batches") or []
        batches.append(
            {
                "request_id": request_id,
                "created_at": time_unix(),
                "paths": paths,
                "remove_unless_file": bool(remove_unless_file),
                "remove_unless_dir": bool(remove_unless_dir),
            }
        )
        store["batches"] = batches
        self._save_store(store)

    def list_batches(self) -> List[Dict[str, Any]]:
        """
        返回待确认批次列表（供插件 API）
        """
        store = self._load_store()
        batches = store.get("batches") or []
        if not isinstance(batches, list):
            return []
        return list(batches)

    def cancel_batch(self, request_id: str) -> bool:
        """
        取消待删除批次（仅从队列移除，不删文件）

        :return bool: 是否找到并移除
        """
        store = self._load_store()
        batches: List[Dict[str, Any]] = store.get("batches") or []
        if not isinstance(batches, list):
            return False
        for i, b in enumerate(batches):
            if isinstance(b, dict) and b.get("request_id") == request_id:
                batches.pop(i)
                store["batches"] = batches
                self._save_store(store)
                return True
        return False

    def _execute_paths(
        self,
        paths: List[str],
        remove_unless_file: bool,
        remove_unless_dir: bool,
    ) -> Tuple[int, Optional[str]]:
        """
        物理删除 STRM 及关联清理

        :return Tuple: (成功删除数, 最后一则错误摘要)
        """
        ok = 0
        last_err: Optional[str] = None
        for remove_path in paths:
            try:
                logger.info(
                    f"【全量STRM生成】清理无效 STRM 文件（已确认）: {remove_path}"
                )
                Path(remove_path).unlink(missing_ok=True)
                if remove_unless_file:
                    PathRemoveUtils.clean_related_files(
                        file_path=Path(remove_path),
                        func_type="【全量STRM生成】",
                    )
                if remove_unless_dir:
                    PathRemoveUtils.remove_parent_dir(
                        file_path=Path(remove_path),
                        mode="mixed",
                        func_type="【全量STRM生成】",
                    )
                ok += 1
            except Exception as e:
                sentry_manager.sentry_hub.capture_exception(e)
                last_err = str(e)
                logger.error(
                    f"【全量STRM生成】清理无效 STRM 文件（已确认）失败: {remove_path} {e}",
                    exc_info=True,
                )
        return ok, last_err

    def execute_batch(self, request_id: str) -> Tuple[int, Optional[str]]:
        """
        执行一批待确认的 STRM 删除（从队列移除后执行）

        :return Tuple: (删除条数, 错误摘要；全部成功则为 None，未找到批次为 batch_not_found)
        """
        store = self._load_store()
        batches: List[Dict[str, Any]] = store.get("batches") or []
        if not isinstance(batches, list):
            return 0, "batch_not_found"
        idx: Optional[int] = None
        batch: Optional[Dict[str, Any]] = None
        for i, b in enumerate(batches):
            if isinstance(b, dict) and b.get("request_id") == request_id:
                batch = b
                idx = i
                break
        if batch is None or idx is None:
            return 0, "batch_not_found"
        paths = batch.get("paths") or []
        if not isinstance(paths, list) or len(paths) == 0:
            batches.pop(idx)
            store["batches"] = batches
            self._save_store(store)
            return 0, "invalid_batch"
        batches.pop(idx)
        store["batches"] = batches
        self._save_store(store)
        return self._execute_paths(
            paths=[str(p) for p in paths],
            remove_unless_file=bool(batch.get("remove_unless_file")),
            remove_unless_dir=bool(batch.get("remove_unless_dir")),
        )

    def notify_telegram_pending(
        self,
        request_id: str,
        path_count: int,
        sample_paths: List[str],
    ) -> None:
        """
        发送待确认 STRM 清理 Telegram（及支持按钮的渠道）通知
        """
        lines = [
            i18n.translate("strm_cleanup_pending_body", count=path_count),
        ]
        if sample_paths:
            preview = "\n".join(sample_paths[:5])
            lines.append(
                i18n.translate("strm_cleanup_pending_preview", preview=preview)
            )
        text = "\n".join(lines)
        buttons = [
            [
                {
                    "text": i18n.translate("strm_cleanup_btn_confirm"),
                    "callback_data": self._format_callback(request_id, True),
                },
                {
                    "text": i18n.translate("strm_cleanup_btn_cancel"),
                    "callback_data": self._format_callback(request_id, False),
                },
            ]
        ]
        post_message(
            mtype=NotificationType.Plugin,
            title=i18n.translate("strm_cleanup_pending_title"),
            text=text,
            buttons=buttons,
        )

    def try_handle_message_action(self, event_data: Optional[Dict[str, Any]]) -> bool:
        """
        处理 MessageAction 中的 STRM 清理二次验证回调（无 interactive session）

        :return bool: 已处理则为 True，否则 False
        """
        if not event_data:
            return False
        raw = (event_data.get("text") or "").strip()
        if not raw:
            return False
        norm = self._normalize_plugin_callback_text(raw)
        parsed = self._parse_callback_text(norm)
        if not parsed:
            return False
        request_id, approve = parsed
        channel = event_data.get("channel")
        source = event_data.get("source")
        userid = event_data.get("userid") or event_data.get("user")
        if approve:
            removed, err = self.execute_batch(request_id)
            if err == "batch_not_found":
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_not_found_title"),
                    text=i18n.translate("strm_cleanup_msg_not_found_body"),
                )
            elif err == "invalid_batch":
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_exec_fail_title"),
                    text=i18n.translate("strm_cleanup_msg_invalid_batch_body"),
                )
            elif err:
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_exec_fail_title"),
                    text=i18n.translate("strm_cleanup_msg_exec_fail_body", err=err),
                )
            else:
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_done_title"),
                    text=i18n.translate("strm_cleanup_msg_done_body", count=removed),
                )
        else:
            if self.cancel_batch(request_id):
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_cancelled_title"),
                    text=i18n.translate("strm_cleanup_msg_cancelled_body"),
                )
            else:
                post_message(
                    channel=channel,
                    source=source,
                    userid=userid,
                    mtype=NotificationType.Plugin,
                    title=i18n.translate("strm_cleanup_msg_not_found_title"),
                    text=i18n.translate("strm_cleanup_msg_not_found_body"),
                )
        return True


strm_cleanup_interaction = StrmCleanupInteraction()
