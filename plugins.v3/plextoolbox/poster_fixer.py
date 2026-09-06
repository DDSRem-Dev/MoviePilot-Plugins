"""缺 poster.jpg 修复：扫描并为缺封面的电影/剧集补齐剧根/影片级 poster.jpg。

场景：
- 电影目录有 backdrop/fanart 等图但独缺 poster.jpg → Plex 显示无封面。
- 剧集剧根缺 poster.jpg，但季目录 Season X/poster.jpg 存在（季海报）→ 剧集列表无封面。

修复策略：
- 电影：从目录名 {tmdb-xxx} 拉 TMDB movie 海报写 poster.jpg，
  选图优先级：原产语言 original_language → 中文 zh → 无字 null → 任意最高分。
- 剧集：优先把季内 Season X/poster.jpg（优先 Season 1）复制到剧根；季内没有再退回
  TMDB tv 海报（同上优先级）。
  注意：剧根的 seasonXX-poster.jpg 是季海报命名，不算剧根海报，也不作为复制来源。

写入采用临时文件 + os.replace 原子落地，属主/权限对齐同目录既有图片。
修复后触发 Plex refresh 让封面生效。
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

from httpx import Client

from app.sdk.config import settings
from app.sdk.logging import logger

from .plex_client import PlexClient

# 剧根/影片级有效海报文件名（小写比较）；seasonXX-poster.jpg 不算
ROOT_POSTER_NAMES = ("poster.jpg", "poster.png", "folder.jpg", "cover.jpg", "show.jpg")
TMDB_DIR_RE = re.compile(r"\{tmdb-(\d+)\}")
SEASON_DIR_RE = re.compile(r"^season[ _]?(\d+)$", re.IGNORECASE)


def _dir_has_root_poster(dir_path: str) -> bool:
    """
    判断目录是否已有剧根/影片级海报文件。

    :param dir_path: 目录绝对路径
    :return: 已有海报返回 True
    """
    try:
        for name in os.listdir(dir_path):
            if name.lower() in ROOT_POSTER_NAMES:
                return True
    except OSError as exc:
        logger.debug("读取目录失败 %s: %s", dir_path, exc)
    return False


def _extract_tmdbid(dir_path: str) -> Optional[int]:
    """
    从目录路径中提取 {tmdb-xxxx} 的 TMDB ID。

    :param dir_path: 目录路径
    :return: TMDB ID，无则 None
    """
    m = TMDB_DIR_RE.search(os.path.basename(dir_path)) or TMDB_DIR_RE.search(dir_path)
    return int(m.group(1)) if m else None


def _find_season_poster(show_dir: str) -> Optional[str]:
    """
    在剧根下寻找季目录内的 poster.jpg（优先季号最小的季）。

    :param show_dir: 剧根目录
    :return: 季内 poster.jpg 路径，找不到返回 None
    """
    seasons: List[Tuple[int, str]] = []
    try:
        for name in os.listdir(show_dir):
            sub = os.path.join(show_dir, name)
            if not os.path.isdir(sub):
                continue
            m = SEASON_DIR_RE.match(name)
            if m:
                seasons.append((int(m.group(1)), sub))
    except OSError as exc:
        logger.debug("读取剧根失败 %s: %s", show_dir, exc)
        return None
    for _, sdir in sorted(seasons, key=lambda x: x[0]):
        for cand in ("poster.jpg", "poster.png"):
            p = os.path.join(sdir, cand)
            if os.path.isfile(p):
                return p
    return None


def _align_owner_perm(target: str, ref_dir: str) -> None:
    """
    将 target 的属主/权限对齐 ref_dir 中既有图片文件；无参照时 0644。

    :param target: 目标文件路径
    :param ref_dir: 参照目录
    """
    ref: Optional[os.stat_result] = None
    try:
        for name in os.listdir(ref_dir):
            if name.lower().endswith((".jpg", ".png")) and \
                    os.path.abspath(os.path.join(ref_dir, name)) != os.path.abspath(target):
                ref = os.stat(os.path.join(ref_dir, name))
                break
    except OSError:
        pass
    try:
        if ref:
            os.chown(target, ref.st_uid, ref.st_gid)
            os.chmod(target, ref.st_mode & 0o777)
        else:
            os.chmod(target, 0o644)
    except OSError as exc:
        logger.debug("对齐属主权限失败 %s: %s", target, exc)


def _atomic_write(target: str, data: bytes) -> None:
    """
    临时文件 + os.replace 原子写入。

    :param target: 目标路径
    :param data: 文件内容
    """
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, target)


class TmdbPosterSource:
    """按「原产语言 → zh → 无字 → 任意」优先级从 TMDB 取海报。"""

    def __init__(self, timeout: float = 30.0) -> None:
        """
        初始化 TMDB 海报源。

        :param timeout: 请求超时秒数
        """
        self._api = f"https://{settings.TMDB_API_DOMAIN}/3"
        self._img = f"https://{settings.TMDB_IMAGE_DOMAIN}/t/p/original"
        self._key = settings.TMDB_API_KEY
        self._proxy = None
        try:
            proxies = settings.PROXY
            if isinstance(proxies, dict):
                self._proxy = proxies.get("https") or proxies.get("http")
            elif isinstance(proxies, str):
                self._proxy = proxies
        except Exception:
            self._proxy = None
        self._timeout = timeout

    def _client(self) -> Client:
        """构建 httpx 客户端（httpx>=0.28 使用 proxy 参数）。"""
        return Client(timeout=self._timeout, proxy=self._proxy)

    def _get_json(self, path: str) -> Optional[dict]:
        """
        GET TMDB API 并解析 JSON。

        :param path: 相对路径（不含 api_key）
        :return: JSON，失败返回 None
        """
        sep = "&" if "?" in path else "?"
        url = f"{self._api}{path}{sep}api_key={self._key}"
        try:
            with self._client() as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("TMDB %s 返回 %s", path, resp.status_code)
        except Exception as exc:
            logger.warning("TMDB 请求失败 %s: %s", path, exc)
        return None

    @staticmethod
    def _pick(posters: List[dict], lang: Optional[str]) -> Optional[str]:
        """
        在海报列表中按语言过滤并取评分最高的一张。

        :param posters: TMDB posters 列表
        :param lang: 语言代码；None 表示无字（iso_639_1 为 null）
        :return: poster file_path，无匹配返回 None
        """
        group = [p for p in posters if p.get("iso_639_1") == lang]
        if not group:
            return None
        group.sort(
            key=lambda p: (p.get("vote_average") or 0, p.get("vote_count") or 0),
            reverse=True,
        )
        return group[0].get("file_path")

    def fetch_poster(self, tmdbid: int, media: str) -> Optional[bytes]:
        """
        取指定条目的最佳海报图片字节。

        :param tmdbid: TMDB ID
        :param media: 'movie' 或 'tv'
        :return: 图片字节，失败返回 None
        """
        detail = self._get_json(f"/{media}/{tmdbid}")
        if not detail:
            return None
        orig_lang = detail.get("original_language")
        images = self._get_json(f"/{media}/{tmdbid}/images")
        posters = (images or {}).get("posters") or []
        file_path = None
        for lang in (orig_lang, "zh", None):
            file_path = self._pick(posters, lang)
            if file_path:
                break
        if not file_path:
            # images 无结果时退回 detail 的默认 poster_path
            file_path = detail.get("poster_path")
        if not file_path:
            return None
        url = f"{self._img}{file_path}"
        try:
            with self._client() as client:
                resp = client.get(url)
                if resp.status_code == 200 and resp.content:
                    return resp.content
                logger.warning("TMDB 海报下载失败 %s: %s", url, resp.status_code)
        except Exception as exc:
            logger.warning("TMDB 海报下载异常 %s: %s", url, exc)
        return None


class PosterFixer:
    """编排「缺 poster.jpg 扫描 + 补全 + Plex 刷新」流程。"""

    def __init__(self, plex: PlexClient) -> None:
        """
        初始化。

        :param plex: Plex 客户端（直连）
        """
        self._plex = plex
        self._tmdb = TmdbPosterSource()

    def _media_dir(self, rating_key: str, itype: str) -> str:
        """
        根据条目类型定位媒体目录（电影=文件上级；剧集=文件上两级即剧根）。

        :param rating_key: 条目 ratingKey
        :param itype: 分区类型 movie/show
        :return: 目录路径，取不到返回空串
        """
        file_path = self._plex.first_file_path(rating_key, itype)
        if not file_path:
            return ""
        if itype == "show":
            return os.path.dirname(os.path.dirname(file_path))
        return os.path.dirname(file_path)

    def scan(self, section_key: str) -> Dict[str, Any]:
        """
        扫描分区内「目录缺剧根/影片级 poster.jpg」的条目。

        :param section_key: Plex 分区 key
        :return: {checked, total, missing: [{rating_key, title, dir, tmdbid, media}]}
        """
        itype = self._plex.section_type(section_key)
        media = "tv" if itype == "show" else "movie"
        items = self._plex.iter_top_items(section_key)
        missing: List[Dict[str, Any]] = []
        for it in items:
            rk = it["rating_key"]
            d = self._media_dir(rk, itype)
            if not d or not os.path.isdir(d):
                continue
            if _dir_has_root_poster(d):
                continue
            missing.append(
                {
                    "rating_key": rk,
                    "title": it.get("title"),
                    "dir": d,
                    "tmdbid": _extract_tmdbid(d),
                    "media": media,
                }
            )
        return {
            "section": section_key,
            "type": itype,
            "checked": len(items),
            "total": len(missing),
            "missing": missing,
        }

    def _fix_one(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        修复单个缺 poster 条目。

        :param item: scan 产出的 missing 项
        :return: {ok, source, error?}
        """
        d = item["dir"]
        target = os.path.join(d, "poster.jpg")
        # TV 优先季内复制
        if item.get("media") == "tv":
            season_poster = _find_season_poster(d)
            if season_poster:
                try:
                    tmp = target + ".tmp"
                    shutil.copyfile(season_poster, tmp)
                    os.replace(tmp, target)
                    _align_owner_perm(target, d)
                    return {"ok": True, "source": "season_copy"}
                except OSError as exc:
                    logger.warning("季海报复制失败 %s: %s", d, exc)
        # TMDB 回退
        tmdbid = item.get("tmdbid")
        if not tmdbid:
            return {"ok": False, "error": "目录名无 {tmdb-id}，且无季内海报可用"}
        data = self._tmdb.fetch_poster(tmdbid, item.get("media") or "movie")
        if not data:
            return {"ok": False, "error": f"TMDB 未取到海报 (tmdbid={tmdbid})"}
        try:
            _atomic_write(target, data)
            _align_owner_perm(target, d)
            return {"ok": True, "source": "tmdb"}
        except OSError as exc:
            return {"ok": False, "error": f"写入失败: {exc}"}

    def fix(
        self, section_key: str, dry_run: bool = True, limit: int = 0
    ) -> Dict[str, Any]:
        """
        对分区执行缺 poster 补全：扫描 → 补全 → Plex refresh。

        :param section_key: Plex 分区 key
        :param dry_run: 为 True 时仅列出待修复条目，不写入
        :param limit: 最多处理条数，0 表示不限制
        :return: 汇总结果
        """
        scan = self.scan(section_key)
        targets = scan["missing"]
        if limit:
            targets = targets[:limit]
        summary: Dict[str, Any] = {
            "section": section_key,
            "type": scan["type"],
            "dry_run": dry_run,
            "checked": scan["checked"],
            "candidates": len(targets),
            "fixed": 0,
            "failed": 0,
            "refreshed": 0,
            "details": [],
        }
        if dry_run:
            summary["targets"] = [
                {"title": t["title"], "dir": t["dir"], "tmdbid": t["tmdbid"]}
                for t in targets
            ]
            return summary
        for t in targets:
            res = self._fix_one(t)
            detail = {
                "title": t["title"],
                "dir": t["dir"],
                "ok": res.get("ok", False),
                "source": res.get("source"),
            }
            if res.get("ok"):
                summary["fixed"] += 1
                if self._plex.refresh_metadata(t["rating_key"]):
                    summary["refreshed"] += 1
            else:
                summary["failed"] += 1
                detail["error"] = res.get("error")
                logger.warning(
                    "缺 poster 修复失败 %s: %s", t["dir"], res.get("error")
                )
            summary["details"].append(detail)
        return summary
