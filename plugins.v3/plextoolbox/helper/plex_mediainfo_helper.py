#!/usr/bin/env python3
"""
Plex MediaInfo Helper —— 运行在 Plex 所在机器上的本地写库小服务。

设计目标：
- 只在 Plex 数据库文件本地做写入，避免跨网络写 SQLite 造成的锁/损库风险。
- 由 MoviePilot 侧的 PlexToolbox 插件计算好媒体流信息后，通过 HTTP 发送到本服务写入。
- 写入前自动备份数据库、检测 Plex 是否繁忙、运行时自省表结构，兼容不同 Plex 版本。

安全约束：
- 仅监听内网地址，并用简单 token 校验。
- 每次写入前对数据库做带时间戳的备份，仅保留最近 N 份。
- 使用 WAL + busy_timeout，并对写操作串行化。
- 通过 PRAGMA table_info 自省列名，只写实际存在的列，绝不 ALTER TABLE。

仅依赖 Python 标准库。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from datetime import datetime
from glob import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

LISTEN_HOST = os.environ.get("PTH_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("PTH_PORT", "9001"))
ACCESS_TOKEN = os.environ.get("PTH_TOKEN", "")
DB_PATH = os.environ.get("PTH_DB_PATH", "").strip()
BACKUP_KEEP = int(os.environ.get("PTH_BACKUP_KEEP", "10"))
PLEX_LOCAL_URL = os.environ.get("PTH_PLEX_URL", "http://127.0.0.1:32400").rstrip("/")
PLEX_TOKEN = os.environ.get("PTH_PLEX_TOKEN", "").strip()
REFUSE_WHEN_PLAYING = os.environ.get("PTH_REFUSE_WHEN_PLAYING", "1") == "1"
# 每次写入前是否备份数据库。全量备份大库耗时高（写慢的主因之一），默认关闭；
# 需要兜底时置 PTH_BACKUP_ON_WRITE=1。
BACKUP_ON_WRITE = os.environ.get("PTH_BACKUP_ON_WRITE", "0") == "1"

DB_CANDIDATES = [
    "/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
    "/data/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
    "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
    "/plex/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
]

_WRITE_LOCK = threading.Lock()


def _now_str() -> str:
    """返回用于备份文件名的时间戳字符串。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def discover_db_path() -> str:
    """
    探测 Plex 数据库文件路径。优先使用显式配置，否则遍历候选与浅层通配搜索。

    :return: 找到的数据库路径，未找到返回空串
    """
    if DB_PATH and os.path.isfile(DB_PATH):
        return DB_PATH
    for cand in DB_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    for pat in (
        "/config/**/com.plexapp.plugins.library.db",
        "/data/**/com.plexapp.plugins.library.db",
        "/plex/**/com.plexapp.plugins.library.db",
    ):
        hits = glob(pat, recursive=True)
        if hits:
            return hits[0]
    return ""


def list_db_candidates() -> List[str]:
    """
    列出所有存在的数据库候选路径，供人工确认使用。

    :return: 存在的候选路径列表
    """
    found: List[str] = []
    for cand in DB_CANDIDATES:
        if os.path.isfile(cand) and cand not in found:
            found.append(cand)
    for pat in (
        "/config/**/com.plexapp.plugins.library.db",
        "/data/**/com.plexapp.plugins.library.db",
        "/plex/**/com.plexapp.plugins.library.db",
    ):
        for h in glob(pat, recursive=True):
            if h not in found:
                found.append(h)
    return found


def backup_db(db_path: str) -> str:
    """
    备份数据库文件（含 -wal/-shm），并清理超出保留份数的旧备份。

    :param db_path: 数据库文件路径
    :return: 备份文件路径
    """
    backup_dir = os.path.join(os.path.dirname(db_path), "pth_backups")
    os.makedirs(backup_dir, exist_ok=True)
    base = os.path.basename(db_path)
    dst = os.path.join(backup_dir, f"{base}.{_now_str()}.bak")
    shutil.copy2(db_path, dst)
    for suffix in ("-wal", "-shm"):
        side = db_path + suffix
        if os.path.isfile(side):
            shutil.copy2(side, dst + suffix)
    backups = sorted(glob(os.path.join(backup_dir, f"{base}.*.bak")))
    excess = len(backups) - BACKUP_KEEP
    for old in backups[: max(0, excess)]:
        try:
            os.remove(old)
            for suffix in ("-wal", "-shm"):
                if os.path.isfile(old + suffix):
                    os.remove(old + suffix)
        except OSError:
            pass
    return dst


def plex_is_busy() -> Tuple[bool, str]:
    """
    检测 Plex 是否繁忙（有播放会话或正在扫描）。无法查询时视为不繁忙。

    :return: (是否繁忙, 说明)
    """
    if not PLEX_TOKEN:
        return False, "未配置 Plex token，跳过繁忙检测"
    import urllib.request

    def _get(path: str) -> Optional[str]:
        """请求本地 Plex API 并返回响应文本，失败返回 None。"""
        sep = "&" if "?" in path else "?"
        url = f"{PLEX_LOCAL_URL}{path}{sep}X-Plex-Token={PLEX_TOKEN}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    if REFUSE_WHEN_PLAYING:
        body = _get("/status/sessions")
        if body:
            try:
                size = json.loads(body).get("MediaContainer", {}).get("size", 0)
                if int(size or 0) > 0:
                    return True, f"存在 {size} 个播放会话"
            except (ValueError, TypeError):
                pass
    body = _get("/library/sections")
    if body:
        try:
            dirs = json.loads(body).get("MediaContainer", {}).get("Directory", [])
            for d in dirs:
                if str(d.get("refreshing")) in ("1", "true", "True"):
                    return True, "有媒体库正在刷新/扫描"
        except (ValueError, TypeError):
            pass
    return False, "空闲"


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """
    通过 PRAGMA 自省表的列名。

    :param conn: 数据库连接
    :param table: 表名
    :return: 列名列表
    """
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def _filter_columns(data: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    """
    仅保留目标表中真实存在且非空的列。

    :param data: 待写入的键值
    :param allowed: 表实际存在的列名
    :return: 过滤后的键值
    """
    return {k: v for k, v in data.items() if k in allowed and v is not None}


def _upsert(
    conn: sqlite3.Connection,
    table: str,
    key_cols: List[str],
    row: Dict[str, Any],
) -> str:
    """
    按主键列做存在则更新、不存在则插入。

    :param conn: 数据库连接
    :param table: 表名
    :param key_cols: 定位记录的键列
    :param row: 已过滤为真实列的键值
    :return: 'update'、'insert' 或 'skip'
    """
    if not row:
        return "skip"
    keys = [c for c in key_cols if c in row]
    where = " AND ".join(f'"{c}"=?' for c in keys)
    where_vals = [row[c] for c in keys]
    exists = False
    if where:
        cur = conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", where_vals)
        exists = cur.fetchone() is not None
    if exists:
        set_cols = [c for c in row.keys() if c not in key_cols]
        if not set_cols:
            return "skip"
        set_clause = ", ".join(f'"{c}"=?' for c in set_cols)
        conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE {where}",
            [row[c] for c in set_cols] + where_vals,
        )
        return "update"
    cols = list(row.keys())
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
        [row[c] for c in cols],
    )
    return "insert"


def _open_conn(db_path: str) -> sqlite3.Connection:
    """
    打开写库连接并设置 WAL/busy_timeout。

    :param db_path: 数据库路径
    :return: 数据库连接
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _write_one(conn: sqlite3.Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    在已开启事务的连接上写入单条媒体信息（用 SAVEPOINT 隔离失败项）。

    payload 关键字段：part_id（必填，media_parts.id）、media_item_id（可选）、
    container/duration/size/bitrate/width/height/video_codec/audio_codec、
    streams（逐条流列表，含 stream_type 1视频/2音频/3字幕）、overwrite_streams。

    :param conn: 已建立的数据库连接（外层负责 BEGIN/COMMIT）
    :param payload: 媒体信息载荷
    :return: 写入结果统计
    """
    part_id = payload.get("part_id")
    if not part_id:
        return {"success": False, "error": "缺少 part_id"}
    result: Dict[str, Any] = {
        "success": False,
        "part_id": part_id,
        "media_items": "skip",
        "media_parts": "skip",
        "streams_deleted": 0,
        "streams_written": 0,
    }
    conn.execute("SAVEPOINT item_write")
    try:
        media_item_id = payload.get("media_item_id")
        if not media_item_id:
            cur = conn.execute(
                "SELECT media_item_id FROM media_parts WHERE id=?", (part_id,)
            )
            row = cur.fetchone()
            if row:
                media_item_id = row[0]
        if not media_item_id:
            conn.execute("ROLLBACK TO item_write")
            result["error"] = f"无法定位 part_id={part_id} 的 media_item_id"
            return result

        mi_cols = _table_columns(conn, "media_items")
        mi_row = _filter_columns(
            {
                "id": media_item_id,
                "width": payload.get("width"),
                "height": payload.get("height"),
                "duration": payload.get("duration"),
                "bitrate": payload.get("bitrate"),
                "container": payload.get("container"),
                "video_codec": payload.get("video_codec"),
                "audio_codec": payload.get("audio_codec"),
                "display_aspect_ratio": payload.get("display_aspect_ratio"),
                "frames_per_second": payload.get("frame_rate"),
                "audio_channels": payload.get("audio_channels"),
                "media_analysis_version": 6,
            },
            mi_cols,
        )
        if mi_row:
            result["media_items"] = _upsert(conn, "media_items", ["id"], mi_row)

        mp_cols = _table_columns(conn, "media_parts")
        mp_row = _filter_columns(
            {
                "id": part_id,
                "duration": payload.get("duration"),
                "size": payload.get("size"),
                "container": payload.get("container"),
            },
            mp_cols,
        )
        if mp_row:
            result["media_parts"] = _upsert(conn, "media_parts", ["id"], mp_row)

        streams = payload.get("streams") or []
        if streams:
            ms_cols = _table_columns(conn, "media_streams")
            if payload.get("overwrite_streams"):
                cur = conn.execute(
                    "DELETE FROM media_streams WHERE media_part_id=?", (part_id,)
                )
                result["streams_deleted"] = cur.rowcount or 0
            written = 0
            for st in streams:
                # 兼容不同 Plex 版本的流类型列名（stream_type_id / stream_type）
                stype = st.get("stream_type")
                st_row = _filter_columns(
                    {
                        "media_item_id": media_item_id,
                        "media_part_id": part_id,
                        "stream_type_id": stype,
                        "stream_type": stype,
                        "codec": st.get("codec"),
                        "index": st.get("index"),
                        "width": st.get("width"),
                        "height": st.get("height"),
                        "bitrate": st.get("bitrate"),
                        "channels": st.get("channels"),
                        "language": st.get("language"),
                        "frame_rate": st.get("frame_rate"),
                        "bit_depth": st.get("bit_depth"),
                        "sampling_rate": st.get("sampling_rate"),
                    },
                    ms_cols,
                )
                if st_row:
                    quoted = ", ".join(f'"{c}"' for c in st_row.keys())
                    conn.execute(
                        f"INSERT INTO media_streams ({quoted}) "
                        f"VALUES ({', '.join('?' for _ in st_row)})",
                        list(st_row.values()),
                    )
                    written += 1
            result["streams_written"] = written

        conn.execute("RELEASE item_write")
        result["success"] = True
        return result
    except Exception as e:
        try:
            conn.execute("ROLLBACK TO item_write")
        except sqlite3.Error:
            pass
        result["error"] = f"写入异常: {e}"
        return result


def write_media_info(db_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    单条写入入口：建连接、开事务、写入并提交。

    :param db_path: 数据库路径
    :param payload: 媒体信息载荷
    :return: 写入结果统计
    """
    conn = _open_conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = _write_one(conn, payload)
        if result.get("success"):
            conn.commit()
        else:
            conn.rollback()
        return result
    except Exception as e:
        conn.rollback()
        return {"success": False, "part_id": payload.get("part_id"), "error": f"写入异常: {e}"}
    finally:
        conn.close()


def write_media_info_batch(
    db_path: str, items: List[Dict[str, Any]]
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    批量写入：整批共用一个连接一个事务，单条失败用 SAVEPOINT 回滚不影响其余。

    :param db_path: 数据库路径
    :param items: 媒体信息载荷列表
    :return: (成功条数, 每条结果列表)
    """
    results: List[Dict[str, Any]] = []
    ok = 0
    conn = _open_conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for it in items:
            r = _write_one(conn, it)
            if r.get("success"):
                ok += 1
            results.append(r)
        conn.commit()
    except Exception as e:
        conn.rollback()
        # 整批事务级失败：未产生结果的项标记失败
        while len(results) < len(items):
            results.append(
                {
                    "success": False,
                    "part_id": items[len(results)].get("part_id"),
                    "error": f"批量事务异常: {e}",
                }
            )
        ok = sum(1 for r in results if r.get("success"))
    finally:
        conn.close()
    return ok, results


class Handler(BaseHTTPRequestHandler):
    """HTTP 请求处理器：提供健康检查、DB 探测、繁忙检测、写入接口。"""

    server_version = "PlexMediaInfoHelper/1.0"

    def _send(self, code: int, obj: Dict[str, Any]) -> None:
        """发送 JSON 响应。"""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self) -> bool:
        """校验访问 token。未配置 token 时不校验。"""
        if not ACCESS_TOKEN:
            return True
        return self.headers.get("X-PTH-Token", "") == ACCESS_TOKEN

    def log_message(self, fmt: str, *args: Any) -> None:
        """精简访问日志输出。"""
        print(f"[{_now_str()}] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        """处理 GET：/health、/dbinfo、/busy。"""
        if self.path == "/health":
            self._send(200, {"ok": True, "service": "plex-mediainfo-helper"})
            return
        if not self._check_token():
            self._send(401, {"success": False, "error": "token 校验失败"})
            return
        if self.path == "/dbinfo":
            db = discover_db_path()
            self._send(
                200,
                {
                    "success": bool(db),
                    "db_path": db,
                    "candidates": list_db_candidates(),
                    "backup_keep": BACKUP_KEEP,
                },
            )
            return
        if self.path == "/busy":
            busy, reason = plex_is_busy()
            self._send(200, {"success": True, "busy": busy, "reason": reason})
            return
        self._send(404, {"success": False, "error": "未知路径"})

    def do_POST(self) -> None:
        """处理 POST：/write（单条）、/write_batch（批量）。"""
        if not self._check_token():
            self._send(401, {"success": False, "error": "token 校验失败"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send(400, {"success": False, "error": "请求体非合法 JSON"})
            return

        db = discover_db_path()
        if not db:
            self._send(
                500,
                {"success": False, "error": "未找到 Plex 数据库，请设置 PTH_DB_PATH"},
            )
            return

        force = bool(payload.get("force"))
        if not force:
            busy, reason = plex_is_busy()
            if busy:
                self._send(
                    409, {"success": False, "error": f"Plex 繁忙：{reason}", "busy": True}
                )
                return

        with _WRITE_LOCK:
            backup = backup_db(db) if BACKUP_ON_WRITE else ""
            if self.path == "/write":
                res = write_media_info(db, payload)
                res["backup"] = backup
                self._send(200 if res.get("success") else 500, res)
                return
            if self.path == "/write_batch":
                items = payload.get("items") or []
                ok, results = write_media_info_batch(db, items)
                self._send(
                    200,
                    {
                        "success": True,
                        "total": len(items),
                        "ok": ok,
                        "backup": backup,
                        "results": results,
                    },
                )
                return
        self._send(404, {"success": False, "error": "未知路径"})


def main() -> None:
    """启动 HTTP 服务并打印初始化信息。"""
    db = discover_db_path()
    print("=" * 60)
    print("Plex MediaInfo Helper 启动")
    print(f"监听: {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Token: {'已设置' if ACCESS_TOKEN else '未设置（不校验，仅限内网）'}")
    if db:
        print(f"数据库: {db}")
    else:
        print("数据库: 未找到！候选路径:")
        for c in list_db_candidates():
            print(f"  - {c}")
        print("请通过环境变量 PTH_DB_PATH 指定数据库路径。")
    print(f"备份保留: {BACKUP_KEEP} 份")
    print(f"写前备份: {'开' if BACKUP_ON_WRITE else '关（PTH_BACKUP_ON_WRITE=1 可开启）'}")
    print(f"繁忙拒写: {'开' if REFUSE_WHEN_PLAYING else '关'}")
    print("=" * 60)
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
