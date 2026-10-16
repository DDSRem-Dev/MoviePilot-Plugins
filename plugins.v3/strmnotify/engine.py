"""STRM 文件发现与 NFO 通知内容解析"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree


def scan(root: Path) -> Dict[str, float]:
    """完整扫描目录，失败时抛错以保留上次记录，不跟随目录符号链接"""
    if not root.is_dir():
        raise OSError("监控目录不可用")
    result = {}

    def fail(error):
        raise error

    for directory, _, files in os.walk(root, followlinks=False, onerror=fail):
        for name in sorted(files, key=str.casefold):
            path = Path(directory) / name
            if path.suffix.lower() == ".strm" and not path.is_symlink():
                try:
                    result[str(path)] = path.stat().st_mtime
                except OSError:
                    # 文件可能在扫描过程中被整理器移动，跳过本次观察即可。
                    continue
    return dict(sorted(result.items()))


def metadata(path: Path, now: float) -> Optional[dict]:
    """优先匹配同名 NFO，单文件电影目录才允许使用 movie.nfo"""
    nfo = path.with_suffix(".nfo")
    if not nfo.is_file():
        siblings = [p for p in path.parent.iterdir() if p.suffix.lower() == ".strm"]
        if len(siblings) != 1:
            return None
        nfo = path.parent / "movie.nfo"
    if not nfo.is_file():
        return None
    try:
        stat = nfo.stat()
        raw = nfo.read_bytes()
    except OSError:
        return None
    if now - stat.st_mtime < 2 or stat.st_size > 2 * 1024 * 1024:
        return None
    try:
        raw = raw.decode("utf-8-sig").encode("utf-8")
    except UnicodeDecodeError:
        return None
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return None
    try:
        tree = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None
    if tree.tag not in {"movie", "episodedetails", "musicvideo"}:
        return None

    def value(tag):
        return (tree.findtext(tag) or "").strip()

    title = value("title")
    if not title:
        return None
    image = value("cover") or value("thumb") or value("fanart/thumb")
    if urlparse(image).scheme not in {"http", "https"}:
        image = None
    return {
        "title": title,
        "year": value("year"),
        "actors": [n.text.strip() for n in tree.findall("actor/name") if n.text][:5],
        "tags": [n.text.strip() for n in tree.findall("tag") if n.text][:6],
        "image": image,
        "file": path.name,
    }


def reconcile(previous: Optional[dict], files: Dict[str, float], now: float) -> dict:
    """首次仅建立基线，后续只为新增路径加入待通知队列"""
    if previous is None:
        return {"known": sorted(files), "pending": {}}
    known = {str(path) for path in previous.get("known", []) if str(path).strip()}
    previous_pending = previous.get("pending", {})
    pending = {
        str(path): started
        for path, started in previous_pending.items()
        if str(path) in files
    } if isinstance(previous_pending, dict) else {}
    for path in sorted(files.keys() - known):
        pending.setdefault(path, now)
    return {
        "known": sorted(files),
        "pending": {path: pending[path] for path in sorted(pending)},
    }


def pending_candidates(state: Dict[str, dict]) -> List[Tuple[float, str, str]]:
    """按进入待处理队列的时间返回所有目录候选，保证多目录轮询公平。"""
    candidates: List[Tuple[float, str, str]] = []
    for root, record in state.items():
        if not isinstance(record, dict) or not isinstance(record.get("pending"), dict):
            continue
        for path, started in record["pending"].items():
            try:
                timestamp = float(started)
            except (TypeError, ValueError):
                continue
            candidates.append((timestamp, str(root), str(path)))
    return sorted(candidates, key=lambda item: (item[0], item[1], item[2]))
