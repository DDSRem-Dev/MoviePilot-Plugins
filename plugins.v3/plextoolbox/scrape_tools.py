"""目录匹配/刮削工具：Plex 一键 unmatch 重读 NFO、扫描缺封面并交给 MP 刮削。"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from app.sdk.logging import logger

from .plex_client import PlexClient


# 视为“已刮削/已有封面”的元数据文件（大小写不敏感匹配后缀/文件名）
COVER_FILE_NAMES = ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg")
NFO_SUFFIX = ".nfo"


def _dir_has_metadata(dir_path: str) -> bool:
    """
    判断某目录是否已有封面或 NFO 元数据文件。

    :param dir_path: 目录绝对路径
    :return: 目录内含 poster/nfo 等元数据返回 True
    """
    try:
        for name in os.listdir(dir_path):
            low = name.lower()
            if low in COVER_FILE_NAMES or low.endswith(NFO_SUFFIX):
                return True
            # 兼容 <名字>-poster.jpg 命名
            if "poster" in low and low.endswith((".jpg", ".png")):
                return True
    except OSError as exc:
        logger.debug("读取目录失败 %s: %s", dir_path, exc)
    return False


def _dir_only_strm(dir_path: str) -> bool:
    """
    判断某目录（含子目录）是否只有 .strm 视频而无任何元数据文件。

    仅检查该目录及其一层子目录（季目录）内是否存在 poster/nfo。

    :param dir_path: 剧集/电影目录绝对路径
    :return: 只有 strm 无元数据返回 True
    """
    if _dir_has_metadata(dir_path):
        return False
    try:
        for name in os.listdir(dir_path):
            sub = os.path.join(dir_path, name)
            if os.path.isdir(sub) and _dir_has_metadata(sub):
                return False
    except OSError as exc:
        logger.debug("读取目录失败 %s: %s", dir_path, exc)
    return True


class ScrapeTools:
    """封装 Plex 一键取消匹配与缺封面刮削的编排逻辑。"""

    def __init__(self, plex: PlexClient) -> None:
        """
        初始化。

        :param plex: Plex 客户端
        """
        self._plex = plex

    def unmatch_section(
        self,
        section_key: str,
        dry_run: bool = True,
        rematch: bool = True,
        limit: int = 0,
    ) -> Dict[str, Any]:
        """
        对指定分区一键取消匹配，让条目按当前 NFO 代理重读。

        :param section_key: Plex 分区 key
        :param dry_run: 为 True 时仅统计将影响的条目数，不执行
        :param rematch: 取消匹配后是否触发刷新以重读 NFO
        :param limit: 最多处理条目数，0 表示不限制
        :return: 汇总结果
        """
        items = self._plex.iter_top_items(section_key)
        summary: Dict[str, Any] = {
            "section": section_key,
            "dry_run": dry_run,
            "rematch": rematch,
            "total_items": len(items),
            "unmatched": 0,
            "refreshed": 0,
            "failed": 0,
        }
        if dry_run:
            summary["will_affect"] = len(items) if not limit else min(limit, len(items))
            return summary
        count = 0
        for it in items:
            if limit and count >= limit:
                break
            rk = it["rating_key"]
            if self._plex.unmatch(rk):
                summary["unmatched"] += 1
                if rematch and self._plex.refresh_metadata(rk):
                    summary["refreshed"] += 1
            else:
                summary["failed"] += 1
            count += 1
        return summary

    def scan_missing_cover(
        self,
        section_key: str,
        strm_roots: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        扫描分区内缺封面的条目：Plex 无 thumb 或 STRM 目录只有 strm。

        :param section_key: Plex 分区 key
        :param strm_roots: STRM 根目录列表（用于判断目录是否只有 strm），可为空
        :return: {missing: [{rating_key, title, dir, reason}], total, checked}
        """
        items = self._plex.iter_top_items(section_key)
        itype = self._plex.section_type(section_key)
        missing: List[Dict[str, Any]] = []
        for it in items:
            rk = it["rating_key"]
            reason = ""
            if not it.get("has_thumb"):
                reason = "plex_no_thumb"
            file_path = self._plex.first_file_path(rk, itype)
            media_dir = ""
            if file_path:
                # STRM 剧集下钻到集，取剧目录（file 的上两级）；电影取上一级
                if itype == "show":
                    media_dir = os.path.dirname(os.path.dirname(file_path))
                else:
                    media_dir = os.path.dirname(file_path)
                if os.path.isdir(media_dir) and _dir_only_strm(media_dir):
                    reason = reason or "dir_only_strm"
            if reason:
                missing.append(
                    {
                        "rating_key": rk,
                        "title": it.get("title"),
                        "dir": media_dir,
                        "reason": reason,
                    }
                )
        return {
            "section": section_key,
            "type": itype,
            "checked": len(items),
            "total": len(missing),
            "missing": missing,
        }

    def scrape_missing(
        self,
        section_key: str,
        scrape_cb: Callable[[str], Dict[str, Any]],
        strm_roots: Optional[List[str]] = None,
        dry_run: bool = True,
        limit: int = 0,
        unmatch_after: bool = False,
    ) -> Dict[str, Any]:
        """
        对缺封面条目调用 MP 刮削回调，可选刮削后 unmatch 让 Plex 重读。

        :param section_key: Plex 分区 key
        :param scrape_cb: 刮削回调，入参为目录路径，返回结果字典
        :param strm_roots: STRM 根目录列表
        :param dry_run: 为 True 时仅列出将刮削的目录，不执行
        :param limit: 最多处理条目数，0 表示不限制
        :param unmatch_after: 刮削后是否 unmatch+refresh 让 Plex 重读
        :return: 汇总结果
        """
        scan = self.scan_missing_cover(section_key, strm_roots)
        targets = [m for m in scan["missing"] if m.get("dir")]
        summary: Dict[str, Any] = {
            "section": section_key,
            "dry_run": dry_run,
            "candidates": len(targets),
            "scraped": 0,
            "unmatched": 0,
            "refreshed": 0,
            "failed": 0,
            "details": [],
        }
        if dry_run:
            summary["targets"] = [
                {"title": t["title"], "dir": t["dir"], "reason": t["reason"]}
                for t in (targets[:limit] if limit else targets)
            ]
            return summary
        count = 0
        for t in targets:
            if limit and count >= limit:
                break
            d = t["dir"]
            try:
                res = scrape_cb(d)
                ok = bool(res.get("success", True))
                if ok:
                    summary["scraped"] += 1
                    if unmatch_after and self._plex.unmatch(t["rating_key"]):
                        summary["unmatched"] += 1
                    # 刮削成功后始终刷新条目，让 Plex 重读新生成的 NFO/图片
                    if self._plex.refresh_metadata(t["rating_key"]):
                        summary["refreshed"] += 1
                else:
                    summary["failed"] += 1
                summary["details"].append({"dir": d, "ok": ok})
            except Exception as exc:
                summary["failed"] += 1
                logger.error("刮削目录失败 %s: %s", d, exc, exc_info=True)
                summary["details"].append({"dir": d, "ok": False, "error": str(exc)})
            count += 1
        return summary
