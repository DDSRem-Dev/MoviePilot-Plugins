from itertools import batched
from pathlib import Path
from threading import Lock
from time import perf_counter, time as time_unix
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.schemas import NotificationType

from share_strm_scan import Pair, ShareStrmScanCache

from ....core.config import configer
from ....core.i18n import i18n
from ....core.message import post_message
from ....helper.mediasyncdel import MediaSyncDelHelper
from ....utils.path import PathRemoveUtils
from ....utils.sharded_list import ShardedPluginListStore
from ....utils.sentry import sentry_manager

from .oof import ShareOOPServerHelper


class ShareStrmPendingCleanupQueue:
    """
    待确认删除批次队列
    """

    _PENDING_KEY = "pending_share_strm_cleanup_batches"

    def _load_store(self) -> Dict[str, Any]:
        """
        读取待确认删除批次的 ``plugin_data`` 结构

        :return Dict: 至少含 ``batches`` 列表的字典
        """
        raw = configer.get_plugin_data(self._PENDING_KEY)
        if not raw or not isinstance(raw, dict):
            return {"batches": []}
        batches = raw.get("batches")
        if not isinstance(batches, list):
            raw["batches"] = []
        return raw

    def _save_store(self, data: Dict[str, Any]) -> None:
        """
        持久化待确认批次存储

        :param data (Dict): 含 ``batches`` 的完整存储对象
        """
        configer.save_plugin_data(self._PENDING_KEY, data)

    def append_batch(
        self,
        request_id: str,
        paths: List[str],
        remove_related_mediainfo: bool,
        remove_empty_parent_dirs: bool,
        remove_stale_transfer_history: bool,
    ) -> None:
        """
        追加一批待用户确认的删除任务

        :param request_id (str): 批次唯一标识
        :param paths (List): 待删 STRM 路径列表
        :param remove_related_mediainfo (bool): 确认执行时是否清理关联媒体信息文件
        :param remove_empty_parent_dirs (bool): 确认执行时是否清理无效 STRM 目录
        :param remove_stale_transfer_history (bool): 确认执行时是否删除 MP 整理记录
        """
        store = self._load_store()
        store["batches"].append(
            {
                "request_id": request_id,
                "created_at": time_unix(),
                "paths": paths,
                "remove_related_mediainfo": bool(remove_related_mediainfo),
                "remove_empty_parent_dirs": bool(remove_empty_parent_dirs),
                "remove_stale_transfer_history": bool(remove_stale_transfer_history),
            }
        )
        self._save_store(store)

    def clear_all_batches(self) -> None:
        """
        清空全部待确认批次（不删磁盘文件）
        """
        self._save_store({"batches": []})

    def replace_single_batch(
        self,
        request_id: str,
        paths: List[str],
        remove_related_mediainfo: bool,
        remove_empty_parent_dirs: bool,
        remove_stale_transfer_history: bool,
    ) -> None:
        """
        用单一批次替换整个队列（与「只保留最新一次扫描」一致）

        :param request_id (str): 批次唯一标识
        :param paths (List): 待删 STRM 路径列表
        :param remove_related_mediainfo (bool): 确认执行时是否清理关联媒体信息文件
        :param remove_empty_parent_dirs (bool): 确认执行时是否清理无效 STRM 目录
        :param remove_stale_transfer_history (bool): 确认执行时是否删除 MP 整理记录
        """
        self._save_store(
            {
                "batches": [
                    {
                        "request_id": request_id,
                        "created_at": time_unix(),
                        "paths": paths,
                        "remove_related_mediainfo": bool(remove_related_mediainfo),
                        "remove_empty_parent_dirs": bool(remove_empty_parent_dirs),
                        "remove_stale_transfer_history": bool(
                            remove_stale_transfer_history
                        ),
                    }
                ]
            }
        )

    @staticmethod
    def _pop_batch_by_id(
        store: Dict[str, Any], request_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        在 ``store['batches']`` 中按 ``request_id`` 原地弹出匹配批次

        :param store (Dict): ``_load_store`` 返回的存储对象
        :param request_id (str): 批次 ID
        :return Dict: 命中则返回被弹出的批次字典，否则 ``None``
        """
        batches: List[Dict[str, Any]] = store["batches"]
        for i, b in enumerate(batches):
            if isinstance(b, dict) and b.get("request_id") == request_id:
                return batches.pop(i)
        return None

    def list_pending_summaries(self) -> List[Dict[str, Any]]:
        """
        返回当前所有待确认批次的轻量摘要（不含 ``paths``，避免数万条路径拷贝）

        :return List: 每项含 ``request_id``、``created_at``、``path_count`` 及标志位
        """
        out: List[Dict[str, Any]] = []
        for b in self._load_store()["batches"]:
            if not isinstance(b, dict):
                continue
            paths = b.get("paths")
            out.append(
                {
                    "request_id": b.get("request_id"),
                    "created_at": b.get("created_at"),
                    "path_count": len(paths) if isinstance(paths, list) else 0,
                    "remove_related_mediainfo": bool(b.get("remove_related_mediainfo")),
                    "remove_empty_parent_dirs": bool(b.get("remove_empty_parent_dirs")),
                    "remove_stale_transfer_history": bool(
                        b.get("remove_stale_transfer_history")
                    ),
                }
            )
        return out

    def pending_batch_paths_page(
        self, request_id: str, page: int, limit: int
    ) -> Tuple[bool, List[str], int]:
        """
        分页返回某待确认批次内的 STRM 路径（服务端切片，避免一次返回数万条）

        :param request_id (str): 批次 ID
        :param page (int): 页码，从 1 开始
        :param limit (int): 每页条数，上限 500
        :return Tuple: ``(是否找到批次, 当前页路径字符串列表, 路径总条数)``
        """
        rid = (request_id or "").strip()
        if not rid:
            return False, [], 0
        for b in self._load_store()["batches"]:
            if not isinstance(b, dict) or b.get("request_id") != rid:
                continue
            paths = b.get("paths") or []
            if not isinstance(paths, list):
                return True, [], 0
            total = len(paths)
            lim = min(max(1, limit), 500)
            offset = (max(1, page) - 1) * lim
            if offset >= total:
                return True, [], total
            return True, paths[offset : offset + lim], total
        return False, [], 0

    def cancel_pending_batch(self, request_id: str) -> bool:
        """
        从队列移除指定批次，不删除磁盘文件

        :param request_id (str): 批次 ID
        :return bool: 是否找到并移除
        """
        store = self._load_store()
        if self._pop_batch_by_id(store, request_id) is None:
            return False
        self._save_store(store)
        return True

    def claim_pending_batch(
        self, request_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        从待确认队列中原子取出批次并持久化，供后续在后台执行删除

        :param request_id (str): 批次 ID
        :return Tuple: ``(批次字典, None)`` 表示已取出；``(None, 错误码)`` 为 ``batch_not_found`` 或 ``invalid_batch``
        """
        store = self._load_store()
        batch = self._pop_batch_by_id(store, request_id)
        if batch is None:
            return None, "batch_not_found"
        self._save_store(store)
        paths = batch.get("paths")
        if not isinstance(paths, list) or len(paths) == 0:
            return None, "invalid_batch"
        return batch, None


class ShareStrmMissingMediaStore:
    """
    失效分享对应的缺失媒体记录
    """

    _MISSING_IDX = "share_strm_missing_media__idx"
    _MISSING_SHARD_PREFIX = "share_strm_missing_media__s"

    def __init__(self) -> None:
        self._store = ShardedPluginListStore(
            self._MISSING_IDX,
            self._MISSING_SHARD_PREFIX,
            max_per_shard=200,
        )

    @staticmethod
    def row_from_transfer_history(
        th: Any,
        strm_path: str,
        share_code: str,
        receive_code: str,
    ) -> Dict[str, Any]:
        """
        组装写入分片存储的「缺失媒体」字典（含固定字段与整理记录子集）

        :param th (Any): ``TransferHistory`` 模型实例
        :param strm_path (str): STRM 路径
        :param share_code (str): 分享码
        :param receive_code (str): 接收码（提取码）
        :return Dict: 含 ``uid``、``reason``、``detected_at`` 及 ``id``/``title`` 等 API 字段的字典
        """
        uid = str(uuid4())
        base: Dict[str, Any] = {
            "uid": uid,
            "strm_path": strm_path,
            "share_code": share_code,
            "receive_code": receive_code,
            "detected_at": time_unix(),
            "reason": "invalid_share",
            "id": getattr(th, "id", None),
            "type": getattr(th, "type", None),
            "title": getattr(th, "title", None),
            "year": getattr(th, "year", None),
            "tmdbid": getattr(th, "tmdbid", None),
            "tvdbid": getattr(th, "tvdbid", None),
            "imdbid": getattr(th, "imdbid", None),
            "doubanid": getattr(th, "doubanid", None),
            "seasons": getattr(th, "seasons", None),
            "episodes": getattr(th, "episodes", None),
            "image": getattr(th, "image", None),
        }
        return base

    def extend(self, rows: List[Dict[str, Any]]) -> None:
        """
        追加缺失媒体记录

        :param rows (List): 由 ``row_from_transfer_history`` 等组装的行列表
        """
        self._store.extend(rows)

    def replace_all(self, rows: List[Dict[str, Any]]) -> None:
        """
        用本轮扫描结果替换全部缺失媒体记录（先清空再写入）

        :param rows (List): 由 ``row_from_transfer_history`` 等组装的行列表，可为空
        """
        self._store.clear_all()
        if rows:
            self._store.extend(rows)

    def page(self, page: int, limit: int) -> Tuple[List[Dict[str, Any]], int]:
        """
        分页读取缺失媒体分片列表（仅加载当前页涉及分片）

        :param page (int): 页码，从 1 开始
        :param limit (int): 每页条数
        :return Tuple: ``(当前页条目列表, 总条数)``
        """
        return self._store.page(page, limit)

    def clear(self, uid: Optional[str], clear_all: bool) -> bool:
        """
        清空全部分片或按 ``uid`` 删除单条

        :param uid (str): 记录 ``uid``，与 ``clear_all`` 互斥时生效
        :param clear_all (bool): 为真时删除索引及全部分片
        :return bool: 清空全量恒为 ``True``；按 ``uid`` 删除时是否找到并删除
        """
        if clear_all:
            self._store.clear_all()
            return True
        if uid:
            return self._store.delete_by_uid(uid)
        return False


class ShareStrmCleanupSummaryStore:
    """
    最近一次 ``run_full_cleanup`` 摘要
    """

    _LAST_SUMMARY_KEY = "share_strm_cleanup_last_summary"

    def save(self, summary: Dict[str, Any]) -> None:
        """
        将最近一次扫描摘要写入 ``plugin_data``

        :param summary (Dict): 摘要字典，供仪表盘等读取
        """
        configer.save_plugin_data(self._LAST_SUMMARY_KEY, summary)

    def get(self) -> Optional[Dict[str, Any]]:
        """
        读取最近一次 ``run_full_cleanup`` 写入的摘要

        :return Dict: 摘要字典，不存在或格式不对则为 ``None``
        """
        raw = configer.get_plugin_data(self._LAST_SUMMARY_KEY)
        if isinstance(raw, dict):
            return raw
        return None


class ShareStrmCleaner:
    """
    分享 STRM 清理器
    """

    _SHARE_VALIDATE_SNAP_BATCH = 2000
    _VALIDATE_PROGRESS_LOG_INTERVAL_SEC = 10.0

    @staticmethod
    def _format_log_progress_bar(ratio: float, width: int = 20) -> str:
        """
        将 0–1 比例格式化为日志用 ASCII 进度条

        :param ratio (float): 完成比例
        :param width (int): 进度条宽度（字符数）
        :return str: 形如 ``[████████░░░░] 42.5%`` 的字符串
        """
        ratio = max(0.0, min(1.0, ratio))
        filled = int(ratio * width)
        if filled >= width:
            bar = "=" * width
        elif ratio > 0:
            bar = "=" * filled + ">" + " " * (width - filled - 1)
        else:
            bar = " " * width
        return f"[{bar}] {ratio * 100:.1f}%"

    def __init__(
        self,
        pending_queue: ShareStrmPendingCleanupQueue,
        missing_media_store: ShareStrmMissingMediaStore,
        summary_store: ShareStrmCleanupSummaryStore,
    ) -> None:
        self.scaner = ShareStrmScanCache()
        self._run_lock = Lock()
        self._pending_queue = pending_queue
        self._missing_store = missing_media_store
        self._summary_store = summary_store

    def __del__(self) -> None:
        self.scaner.invalidate()

    def scan_invalid_shares(self, path: Path) -> Tuple[bool, Dict[Pair, List[str]]]:
        """
        扫描目录，校验分享有效性并返回失效 Pair 对应的 STRM 路径映射

        :param path (Path): 本地扫描根目录
        :return Tuple: 成功时为 ``(True, { (share_code, receive_code): [strm_paths...] })``，失败为 ``(False, {})``
        """
        try:
            client = ShareOOPServerHelper.get_client()
            valid_total = 0
            invalid_pairs: List[Tuple[str, str]] = []

            logger.info(f"【分享STRM清理】开始扫描目录: {path}")
            scan_t0 = perf_counter()
            pairs = self.scaner.scan(path)
            scan_elapsed = perf_counter() - scan_t0
            logger.info(
                f"【分享STRM清理】扫描完成，共 {len(pairs)} 个分享组，"
                f"耗时 {scan_elapsed:.1f}s"
            )

            total = len(pairs)
            if total == 0:
                logger.info("【分享STRM清理】无分享组，跳过校验")
            else:
                validated = 0
                last_log_t = 0.0
                for batch_idx, batch in enumerate(
                    batched(pairs, self._SHARE_VALIDATE_SNAP_BATCH),
                    start=1,
                ):
                    chunk = [
                        [share_code, receive_code] for share_code, receive_code in batch
                    ]
                    resp = client.share_validate_snap(chunk)
                    valid_total += resp.valid_count
                    for i in resp.invalid:
                        logger.warn(
                            f"【分享STRM清理】无效分享: {i.share_code} "
                            f"{i.receive_code} {i.error}"
                        )
                        invalid_pairs.append((i.share_code, i.receive_code))
                    validated += len(batch)
                    now = perf_counter()
                    if (
                        batch_idx == 1
                        or validated >= total
                        or (now - last_log_t)
                        >= self._VALIDATE_PROGRESS_LOG_INTERVAL_SEC
                    ):
                        ratio = validated / total
                        logger.info(
                            f"【分享STRM清理】验证分享 "
                            f"{self._format_log_progress_bar(ratio)} "
                            f"({validated}/{total}) 无效 {len(invalid_pairs)}"
                        )
                        last_log_t = now
            logger.info(
                f"【分享STRM清理】验证分享有效性成功，有效分享数量: {valid_total}，"
                f"无效分享数量: {len(invalid_pairs)}"
            )
        except Exception as e:
            logger.error(
                f"【分享STRM清理】扫描目录或验证分享有效性失败: {e}",
                exc_info=True,
            )
            return False, {}
        try:
            if invalid_pairs:
                logger.info(
                    f"【分享STRM清理】开始解析无效分享 STRM 路径，"
                    f"共 {len(invalid_pairs)} 组"
                )
            invalid_paths = self.scaner.paths_for_many(path, invalid_pairs)
            if invalid_pairs:
                strm_count = sum(len(v) for v in invalid_paths.values())
                logger.info(
                    f"【分享STRM清理】路径映射完成，共 {strm_count} 个 STRM 文件"
                )
        except Exception as e:
            logger.error(f"【分享STRM清理】获取无效分享路径失败: {e}")
            return False, {}
        return True, invalid_paths

    @staticmethod
    def _normalize_cleanup_roots(paths: List[str]) -> List[str]:
        """
        将配置中的路径转为绝对路径、去重并跳过非目录

        :param paths (List): 原始路径字符串列表
        :return List: 规范化后的绝对路径字符串列表（顺序保留首次出现）
        """
        seen: set[str] = set()
        out: List[str] = []
        for raw in paths or []:
            s = (raw or "").strip()
            if not s:
                continue
            try:
                p = Path(s).expanduser().resolve()
            except Exception:
                continue
            if not p.is_dir():
                logger.warning(f"【分享STRM清理】跳过不存在的目录: {s}")
                continue
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _execute_paths_physical(
        self,
        paths: List[str],
        remove_related_mediainfo: bool,
        remove_empty_parent_dirs: bool,
        remove_stale_transfer_history: bool = False,
    ) -> Tuple[int, Optional[str]]:
        """
        物理删除 STRM 并按配置清理关联媒体文件、空父目录与 MP 整理记录

        :param paths (List): 待删除 STRM 绝对路径列表
        :param remove_related_mediainfo (bool): 是否调用 ``clean_related_files``
        :param remove_empty_parent_dirs (bool): 是否 ``remove_parent_dir``（strm 模式）
        :param remove_stale_transfer_history (bool): 是否按路径清理 MP 整理记录
        :return Tuple: ``(成功删除条数, 最后一则错误信息；全部成功为 None)``
        """
        ok = 0
        last_err: Optional[str] = None
        sync_del_helper = (
            MediaSyncDelHelper() if remove_stale_transfer_history else None
        )
        for remove_path in paths:
            try:
                logger.info(f"【分享STRM清理】删除无效 STRM: {remove_path}")
                Path(remove_path).unlink(missing_ok=True)
                if remove_related_mediainfo:
                    PathRemoveUtils.clean_related_files(
                        file_path=Path(remove_path),
                        func_type="【分享STRM清理】",
                    )
                if remove_empty_parent_dirs:
                    PathRemoveUtils.remove_parent_dir(
                        file_path=Path(remove_path),
                        mode="mixed",
                        func_type="【分享STRM清理】",
                    )
                ok += 1
            except Exception as e:
                sentry_manager.sentry_hub.capture_exception(e)
                last_err = str(e)
                logger.error(
                    f"【分享STRM清理】删除失败: {remove_path} {e}",
                    exc_info=True,
                )
            if sync_del_helper is not None:
                try:
                    sync_del_helper.remove_by_path(remove_path, del_source=False)
                except Exception as e:
                    logger.error(
                        f"【分享STRM清理】整理记录删除失败: {remove_path} {e}",
                        exc_info=True,
                    )
        return ok, last_err

    @staticmethod
    def _should_notify_cleanup_result(summary: Dict[str, Any]) -> bool:
        """
        是否发送分享 STRM 清理摘要通知（全局通知开启且本次有失效或异常）

        :param summary (Dict): ``run_full_cleanup`` 产出的摘要字典
        :return bool: 是否发送
        """
        if not configer.get_config("notify"):
            return False
        if summary.get("message") == "already_running":
            return False
        if int(summary.get("invalid_strm_count") or 0) > 0:
            return True
        if summary.get("ok") is False:
            return True
        return False

    def _format_share_strm_cleanup_notify_text(self, summary: Dict[str, Any]) -> str:
        """
        拼接分享 STRM 清理通知正文（多行）

        :param summary (Dict): 摘要字典
        :return str: 纯文本正文
        """
        lines: List[str] = []
        lines.append(
            i18n.translate(
                "share_strm_cleanup_line_roots",
                n=int(summary.get("roots_scanned") or 0),
            )
        )
        lines.append(
            i18n.translate(
                "share_strm_cleanup_line_invalid",
                n=int(summary.get("invalid_strm_count") or 0),
            )
        )
        dm = summary.get("delete_mode")
        if dm == "immediate":
            label = i18n.translate("share_strm_cleanup_mode_immediate")
        else:
            label = i18n.translate("share_strm_cleanup_mode_plugin_ui")
        lines.append(i18n.translate("share_strm_cleanup_line_delete_mode", label=label))
        if dm == "immediate":
            lines.append(
                i18n.translate(
                    "share_strm_cleanup_line_deleted",
                    n=int(summary.get("deleted_count") or 0),
                )
            )
            msg = (summary.get("message") or "").strip()
            if msg:
                lines.append(i18n.translate("share_strm_cleanup_line_error", err=msg))
        elif summary.get("queued_batch"):
            lines.append(
                i18n.translate(
                    "share_strm_cleanup_line_queue",
                    rid=summary.get("request_id") or "",
                    n=int(summary.get("invalid_strm_count") or 0),
                )
            )
        rec = int(summary.get("missing_recorded") or 0)
        skip = int(summary.get("missing_skipped_no_history") or 0)
        if rec or skip:
            lines.append(
                i18n.translate(
                    "share_strm_cleanup_line_missing",
                    recorded=rec,
                    skipped=skip,
                )
            )
        return "\n".join(lines)

    def _notify_cleanup_result(self, summary: Dict[str, Any]) -> None:
        """
        按全局通知开关与摘要内容发送单条插件消息

        :param summary (Dict): 已持久化的摘要字典
        """
        if not self._should_notify_cleanup_result(summary):
            return
        try:
            text = self._format_share_strm_cleanup_notify_text(summary)
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("share_strm_cleanup_notify_title"),
                text="\n" + text,
            )
        except Exception as e:
            logger.error(f"【分享STRM清理】发送通知失败: {e}", exc_info=True)

    def _notify_claimed_batch_executed(
        self,
        batch: Dict[str, Any],
        path_total: int,
        removed: int,
        last_err: Optional[str],
    ) -> None:
        """
        插件内确认队列取出后，物理删除完成时发送单条摘要（需全局通知开启）

        :param batch (Dict): 已 claim 的批次字典（含 ``request_id``）
        :param path_total (int): 本批次 STRM 路径总数
        :param removed (int): ``_execute_paths_physical`` 成功删除数
        :param last_err (str): 最后一则删除错误，无则为 ``None``
        """
        if not configer.get_config("notify"):
            return
        try:
            rid = (batch.get("request_id") or "").strip() or "-"
            lines = [
                i18n.translate("share_strm_cleanup_batch_exec_line_rid", rid=rid),
                i18n.translate(
                    "share_strm_cleanup_batch_exec_line_total", n=path_total
                ),
                i18n.translate("share_strm_cleanup_batch_exec_line_removed", n=removed),
            ]
            if last_err:
                lines.append(
                    i18n.translate(
                        "share_strm_cleanup_batch_exec_line_error", err=last_err
                    )
                )
            post_message(
                mtype=NotificationType.Plugin,
                title=i18n.translate("share_strm_cleanup_batch_exec_title"),
                text="\n" + "\n".join(lines),
            )
        except Exception as e:
            logger.error(
                f"【分享STRM清理】批次执行通知发送失败: {e}",
                exc_info=True,
            )

    def run_full_cleanup(self) -> Dict[str, Any]:
        """
        执行完整清理流程：多根扫描、可选缺失媒体写入、立即删除或入队待确认

        结束时释放扫描缓存与运行锁；若已有实例在跑则返回 ``message=already_running``

        :return Dict: 摘要字典，常见键含 ``ok``、``roots_scanned``、``invalid_strm_count``、
            ``deleted_count``、``queued_batch``、``request_id``、``delete_mode``、``message``
        """
        cfg = configer.share_strm_cleanup_config
        roots = self._normalize_cleanup_roots(list(cfg.cleanup_paths or []))
        record_missing = bool(cfg.record_missing_media_from_history)
        summary: Dict[str, Any] = {
            "ok": True,
            "roots_scanned": 0,
            "invalid_strm_count": 0,
            "deleted_count": 0,
            "missing_recorded": 0,
            "missing_skipped_no_history": 0,
            "queued_batch": False,
            "request_id": None,
            "delete_mode": cfg.delete_mode,
            "message": "",
        }
        if not self._run_lock.acquire(blocking=False):
            summary["ok"] = False
            summary["message"] = "already_running"
            return summary
        try:
            if not roots:
                logger.info("【分享STRM清理】cleanup_paths 为空或无效，跳过")
                summary["message"] = "no_cleanup_paths"
                self._summary_store.save(summary)
                return summary

            paths_only: List[str] = []
            missing_rows: List[Dict[str, Any]] = []
            oper = TransferHistoryOper() if record_missing else None
            skipped_no_history = 0

            for root in roots:
                ok, inv = self.scan_invalid_shares(Path(root))
                summary["roots_scanned"] += 1
                if not (ok and inv):
                    continue
                for (sc, rc), pths in inv.items():
                    for p in pths:
                        paths_only.append(p)
                        if oper is None:
                            continue
                        th = oper.get_by_dest(p)
                        if th is None:
                            skipped_no_history += 1
                            continue
                        missing_rows.append(
                            ShareStrmMissingMediaStore.row_from_transfer_history(
                                th, p, sc, rc
                            )
                        )
                inv = None

            summary["invalid_strm_count"] = len(paths_only)

            if record_missing:
                self._missing_store.replace_all(missing_rows)
                summary["missing_recorded"] = len(missing_rows)
                summary["missing_skipped_no_history"] = skipped_no_history
            missing_rows = []

            if cfg.delete_mode == "immediate":
                deleted, last_err = self._execute_paths_physical(
                    paths_only,
                    cfg.remove_related_mediainfo,
                    cfg.remove_empty_parent_dirs,
                    cfg.remove_stale_transfer_history,
                )
                summary["deleted_count"] = deleted
                if last_err:
                    summary["message"] = last_err
            elif paths_only:
                rid = uuid4().hex[:16]
                self._pending_queue.replace_single_batch(
                    rid,
                    paths_only,
                    cfg.remove_related_mediainfo,
                    cfg.remove_empty_parent_dirs,
                    cfg.remove_stale_transfer_history,
                )
                summary["queued_batch"] = True
                summary["request_id"] = rid
            else:
                self._pending_queue.clear_all_batches()

            self._summary_store.save(summary)
            self._notify_cleanup_result(summary)
            return summary
        finally:
            self.scaner.invalidate()
            self._run_lock.release()

    def execute_claimed_batch(self, batch: Dict[str, Any]) -> Tuple[int, Optional[str]]:
        """
        对已脱离队列的批次执行物理删除及可选整理记录清理

        :param batch (Dict): ``claim_pending_batch`` 返回的字典
        :return Tuple: ``(删除成功条数, 最后一则物理删除错误；全部成功为 None)``
        """
        paths = batch.get("paths")
        if not isinstance(paths, list) or len(paths) == 0:
            return 0, "invalid_batch"
        path_total = len(paths)
        removed, last_err = self._execute_paths_physical(
            paths,
            bool(batch.get("remove_related_mediainfo")),
            bool(batch.get("remove_empty_parent_dirs")),
            bool(batch.get("remove_stale_transfer_history")),
        )
        self._notify_claimed_batch_executed(batch, path_total, removed, last_err)
        return removed, last_err

    def execute_pending_batch(self, request_id: str) -> Tuple[int, Optional[str]]:
        """
        从队列取出批次并同步执行物理删除（claim + execute_claimed_batch）

        :param request_id (str): 批次 ID
        :return Tuple: ``(删除成功条数, 错误码或错误信息)``
        """
        batch, cerr = self._pending_queue.claim_pending_batch(request_id)
        if cerr:
            return 0, cerr
        assert batch is not None
        return self.execute_claimed_batch(batch)


share_strm_pending_queue = ShareStrmPendingCleanupQueue()
share_strm_missing_media_store = ShareStrmMissingMediaStore()
share_strm_cleanup_summary_store = ShareStrmCleanupSummaryStore()
share_strm_cleaner = ShareStrmCleaner(
    pending_queue=share_strm_pending_queue,
    missing_media_store=share_strm_missing_media_store,
    summary_store=share_strm_cleanup_summary_store,
)
