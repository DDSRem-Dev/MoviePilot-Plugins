"""Plex API 轻封装：枚举媒体库、列出条目、抽取 STRM part 信息。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from httpx import Client

from app.sdk.logging import logger


class PlexClient:
    """封装 Plex 服务器只读查询，用于枚举需要补全媒体信息的 STRM 条目。"""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        """
        初始化 Plex 客户端。

        :param base_url: Plex 服务器根地址（可直连真实后端，如 http://192.168.0.122:32400）
        :param token: X-Plex-Token
        :param timeout: 请求超时秒数
        """
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _get(self, path: str) -> Optional[dict]:
        """
        发起 GET 请求并解析 JSON。

        :param path: 相对路径（含查询串）
        :return: 解析后的 JSON，失败返回 None
        """
        sep = "&" if "?" in path else "?"
        url = f"{self._base}{path}{sep}X-Plex-Token={quote(self._token, safe='')}"
        try:
            with Client(timeout=self._timeout) as client:
                resp = client.get(url, headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("Plex API %s 返回 %s", path, resp.status_code)
        except Exception as e:
            logger.warning("Plex API 请求失败 %s: %s", path, e)
        return None

    def _put(self, path: str) -> bool:
        """
        发起 PUT 请求（用于 unmatch 等写操作）。

        :param path: 相对路径（含查询串）
        :return: 2xx 返回 True
        """
        sep = "&" if "?" in path else "?"
        url = f"{self._base}{path}{sep}X-Plex-Token={quote(self._token, safe='')}"
        try:
            with Client(timeout=self._timeout) as client:
                resp = client.put(url, headers={"Accept": "application/json"})
                if 200 <= resp.status_code < 300:
                    return True
                logger.warning("Plex PUT %s 返回 %s", path, resp.status_code)
        except Exception as e:
            logger.warning("Plex PUT 请求失败 %s: %s", path, e)
        return False

    def section_type(self, section_key: str) -> str:
        """
        获取分区类型（movie/show 等）。

        :param section_key: 分区 key
        :return: 类型字符串，未知返回空串
        """
        for s in self.list_sections():
            if str(s.get("key")) == str(section_key):
                return s.get("type") or ""
        return ""

    def iter_top_items(self, section_key: str) -> List[Dict[str, Any]]:
        """
        列出分区下顶层条目（电影或剧集），带封面标记与文件路径信息。

        :param section_key: 分区 key
        :return: [{rating_key, type, title, has_thumb, has_art}]
        """
        data = self._get(f"/library/sections/{section_key}/all")
        if not data:
            return []
        items = data.get("MediaContainer", {}).get("Metadata", [])
        result: List[Dict[str, Any]] = []
        for m in items:
            if not m.get("ratingKey"):
                continue
            result.append(
                {
                    "rating_key": m.get("ratingKey"),
                    "type": m.get("type"),
                    "title": m.get("title"),
                    "has_thumb": bool(m.get("thumb")),
                    "has_art": bool(m.get("art")),
                }
            )
        return result

    def unmatch(self, rating_key: str) -> bool:
        """
        取消某条目的匹配（打回未匹配，重读时按当前代理识别）。

        :param rating_key: 条目 ratingKey
        :return: 成功返回 True
        """
        return self._put(f"/library/metadata/{rating_key}/unmatch")

    def refresh_metadata(self, rating_key: str) -> bool:
        """
        触发条目按当前代理刷新元数据（用于 unmatch 后重读 NFO）。

        :param rating_key: 条目 ratingKey
        :return: 成功返回 True
        """
        return self._put(f"/library/metadata/{rating_key}/refresh")

    def first_file_path(self, rating_key: str, item_type: str) -> str:
        """
        取条目第一个媒体文件的真实路径（用于定位 STRM 目录）。

        电影直接取自身 Part；剧集下钻到第一集取 Part。

        :param rating_key: 条目 ratingKey
        :param item_type: 条目类型（movie/show）
        :return: 文件路径，取不到返回空串
        """
        metas: List[Dict[str, Any]] = []
        if item_type == "show":
            for season in self._children(rating_key):
                skey = season.get("ratingKey")
                if not skey:
                    continue
                eps = self._children(skey)
                if eps:
                    metas = self._metadata(eps[0].get("ratingKey"))
                    break
        else:
            metas = self._metadata(rating_key)
        for meta in metas:
            for p in self._extract_parts(meta):
                if p.get("file"):
                    return p["file"]
        return ""

    def list_sections(self) -> List[Dict[str, Any]]:
        """
        列出所有媒体库分区。

        :return: [{key, title, type}]，type 为 movie/show 等
        """
        data = self._get("/library/sections")
        if not data:
            return []
        dirs = data.get("MediaContainer", {}).get("Directory", [])
        return [
            {"key": d.get("key"), "title": d.get("title"), "type": d.get("type")}
            for d in dirs
            if d.get("key")
        ]

    def _iter_section_items(self, section_key: str) -> List[Dict[str, Any]]:
        """
        列出某分区下全部条目的 ratingKey 与类型。

        :param section_key: 分区 key
        :return: [{rating_key, type, title}]
        """
        data = self._get(f"/library/sections/{section_key}/all")
        if not data:
            return []
        items = data.get("MediaContainer", {}).get("Metadata", [])
        return [
            {
                "rating_key": m.get("ratingKey"),
                "type": m.get("type"),
                "title": m.get("title"),
            }
            for m in items
            if m.get("ratingKey")
        ]

    def _metadata(self, rating_key: str) -> List[Dict[str, Any]]:
        """
        获取条目元数据的 Metadata 数组。

        :param rating_key: 条目 ratingKey
        :return: Metadata 列表
        """
        data = self._get(f"/library/metadata/{rating_key}")
        if not data:
            return []
        return data.get("MediaContainer", {}).get("Metadata", [])

    def _children(self, rating_key: str) -> List[Dict[str, Any]]:
        """
        获取条目的子项（剧集的季、季的集）。

        :param rating_key: 父条目 ratingKey
        :return: 子项 Metadata 列表
        """
        data = self._get(f"/library/metadata/{rating_key}/children")
        if not data:
            return []
        return data.get("MediaContainer", {}).get("Metadata", [])

    @staticmethod
    def _build_label(metadata: Dict[str, Any]) -> str:
        """
        构建条目的人类可读标签：剧集为「剧名 SxxExx 集名」，电影为「片名 (年份)」。

        :param metadata: 条目 Metadata
        :return: 标签字符串
        """
        title = metadata.get("title") or ""
        if metadata.get("type") == "episode":
            show = metadata.get("grandparentTitle") or ""
            s, e = metadata.get("parentIndex"), metadata.get("index")
            se = ""
            try:
                if s is not None and e is not None:
                    se = f"S{int(s):02d}E{int(e):02d}"
            except (TypeError, ValueError):
                se = ""
            return " ".join(x for x in (show, se, title) if x)
        year = metadata.get("year")
        return f"{title} ({year})" if year else title

    def item_label(self, rating_key: str) -> str:
        """
        取单个条目的可读标签（用于补全结果展示）。

        :param rating_key: 条目 ratingKey
        :return: 标签，取不到返回空串
        """
        metas = self._metadata(rating_key)
        return self._build_label(metas[0]) if metas else ""

    def item_section_key(self, rating_key: str) -> str:
        """返回单个条目所属的 Plex 媒体库 key。"""
        metas = self._metadata(rating_key)
        if not metas:
            return ""
        meta = metas[0]
        return str(
            meta.get("librarySectionID")
            or meta.get("librarySectionKey")
            or ""
        ).strip()

    @staticmethod
    def _extract_parts(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从单个条目元数据中抽取所有 Part 的关键字段。

        :param metadata: 条目 Metadata
        :return: [{part_id, file, container, title, label, duration_hint}]
        """
        result: List[Dict[str, Any]] = []
        title = metadata.get("title") or ""
        label = PlexClient._build_label(metadata)
        for media in metadata.get("Media", []) or []:
            for part in media.get("Part", []) or []:
                pid = part.get("id")
                pfile = part.get("file")
                if pid and pfile:
                    result.append(
                        {
                            "part_id": pid,
                            "file": pfile,
                            "container": part.get("container"),
                            "title": title,
                            "label": label,
                            "existing_duration": part.get("duration"),
                            # children 列表接口的 Part 不含 Stream 字段，
                            # 置 None 表示未知，区别于确认为空的 0
                            "existing_streams": (
                                len(part.get("Stream") or [])
                                if "Stream" in part else None
                            ),
                        }
                    )
        return result

    def collect_strm_parts(
        self, section_key: str, only_missing: bool = True
    ) -> List[Dict[str, Any]]:
        """
        枚举某分区下所有 STRM 文件对应的 Part 信息。

        对电影分区直接取条目 Part；对剧集分区逐层下钻到集再取 Part。
        only_missing 为 True 时仅返回缺失媒体流信息（无 Stream 或无时长）的 part。

        :param section_key: 分区 key
        :param only_missing: 是否仅返回缺失媒体信息的 part
        :return: STRM part 列表
        """
        parts: List[Dict[str, Any]] = []
        for item in self._iter_section_items(section_key):
            rating_key = item["rating_key"]
            itype = item.get("type")
            if itype in ("show",):
                # 剧集：show -> season -> episode
                for season in self._children(rating_key):
                    skey = season.get("ratingKey")
                    if not skey:
                        continue
                    for episode in self._children(skey):
                        parts.extend(self._collect_from_meta(episode, only_missing))
            else:
                for meta in self._metadata(rating_key):
                    parts.extend(
                        self._collect_from_meta(meta, only_missing, detailed=True)
                    )
        return parts

    def collect_strm_parts_by_rating_key(
        self, rating_key: str, only_missing: bool = True
    ) -> List[Dict[str, Any]]:
        """
        按单个条目 ratingKey 枚举其 STRM part（用于播放停止后的针对性补全）。

        播放上报/Webhook 给到的 ratingKey 通常是叶子条目（电影或单集），
        直接取其元数据 Part 即可，无需下钻季/集。

        :param rating_key: 条目 ratingKey
        :param only_missing: 是否仅返回缺失媒体信息的 part
        :return: STRM part 列表
        """
        parts: List[Dict[str, Any]] = []
        for meta in self._metadata(rating_key):
            parts.extend(self._collect_from_meta(meta, only_missing, detailed=True))
        return parts

    def collect_window_parts_by_rating_key(
        self,
        rating_key: str,
        forward: int = 5,
        only_missing: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        播放驱动的增量窗口收集：给定当前播放条目，返回需补全的 STRM part。

        规则：
        - 电影：仅收当前这一条（不做预取）。
        - 单集：以当前集为起点，向后取 forward 集（含当前集，共 forward+1 集）
          组成窗口，收集窗口内各集的 STRM part。窗口不跨季，季末即止。
        - only_missing=True 时，窗口内已有媒体信息（已补全）的集自动跳过，
          从而实现「命中已写过的跳过、只写新缺集」的增量效果。

        :param rating_key: 当前播放条目的 ratingKey（电影或单集）
        :param forward: 单集场景下向后预取的集数
        :param only_missing: 是否仅返回缺失媒体信息的 part
        :return: 窗口内待补全的 STRM part 列表
        """
        metas = self._metadata(rating_key)
        if not metas:
            return []
        meta = metas[0]
        itype = meta.get("type")

        # 电影或非剧集叶子：仅当前条目
        if itype != "episode":
            parts: List[Dict[str, Any]] = []
            for m in metas:
                parts.extend(self._collect_from_meta(m, only_missing, detailed=True))
            return parts

        # 单集：定位所在季，按集号取「当前集 + 后 forward 集」窗口
        season_key = meta.get("parentRatingKey")
        cur_index = meta.get("index")
        if not season_key or cur_index is None:
            # 缺少定位信息时退化为仅当前集
            return self._collect_from_meta(meta, only_missing, detailed=True)

        siblings = self._children(season_key)
        # 按集号排序，过滤出当前集及其后 forward 集
        indexed = [
            e for e in siblings
            if e.get("ratingKey") and e.get("index") is not None
        ]
        indexed.sort(key=lambda e: e.get("index"))
        window = [
            e for e in indexed
            if cur_index <= e.get("index") <= cur_index + forward
        ]
        if not window:
            window = [meta]

        parts = []
        for e in window:
            ek = e.get("ratingKey")
            if not ek:
                continue
            for m in self._metadata(ek):
                parts.extend(self._collect_from_meta(m, only_missing, detailed=True))
        return parts


    def _collect_from_meta(
        self, metadata: Dict[str, Any], only_missing: bool, detailed: bool = False
    ) -> List[Dict[str, Any]]:
        """
        从条目元数据抽取 STRM part，按需过滤已有媒体信息的项。

        :param metadata: 条目 Metadata
        :param only_missing: 是否仅返回缺失媒体信息的 part
        :param detailed: metadata 是否来自详情接口（/library/metadata/{rk}）。
            详情接口会返回 Stream；缺失即代表真的没有流（如被 Plex 清空），
            需要重写。列表/children 接口不含 Stream，缺失代表未知。
        :return: STRM part 列表
        """
        out: List[Dict[str, Any]] = []
        for p in self._extract_parts(metadata):
            fpath = (p.get("file") or "").lower()
            if not fpath.endswith(".strm"):
                continue
            if only_missing and p.get("existing_duration"):
                streams = p.get("existing_streams")
                if detailed:
                    # 详情数据：有时长且流数 >0 才算已补全
                    if streams:
                        continue
                else:
                    # 列表数据：流数未知(None)时沿用时长判断，避免全库重扫
                    if streams is None or streams > 0:
                        continue
            out.append(p)
        return out

    @staticmethod
    def _external_guid(guids: List[Dict[str, Any]]) -> Optional[str]:
        """
        从条目的 Guid 数组中提取 tmdb id。

        Plex 的 Guid 形如 ``{"id": "tmdb://94664"}``，这里只取 tmdb 段。
        电影与剧集共用 tmdb id 作为去重依据。

        :param guids: Plex 条目 Guid 数组
        :return: tmdb id 字符串，取不到返回 None
        """
        for g in guids or []:
            idv = g.get("id") or ""
            m = re.search(r"tmdb://(\d+)", idv)
            if m:
                return m.group(1)
        return None

    def scan_duplicate_items(
        self, media_types: Optional[tuple] = ("movie", "show")
    ) -> List[Dict[str, Any]]:
        """
        扫描媒体库中 tmdb id 相同的重复条目。

        列表接口的 includeGuids 不可靠，这里对每个顶层条目逐个调用详情接口
        确认外部 GUID，再按 tmdb id 分组，返回重复组供前端确认后合并。

        :param media_types: 限定媒体类型，默认 ("movie", "show")
        :return: [{guid_id, media_type, title, items:[{rating_key, title, year, leaf_count, section_key, section_title}]}]
        """
        wanted = set(media_types or ())
        grouped: Dict[str, Dict[str, Any]] = {}
        for sec in self.list_sections():
            stype = sec.get("type") or ""
            if wanted and stype not in wanted:
                continue
            skey = str(sec.get("key") or "")
            stitle = sec.get("title") or ""
            if not skey:
                continue
            for item in self._iter_section_items(skey):
                rk = str(item.get("rating_key") or "")
                if not rk:
                    continue
                metas = self._metadata(rk)
                if not metas:
                    continue
                meta = metas[0]
                guid_id = self._external_guid(meta.get("Guid") or [])
                if not guid_id:
                    continue
                entry = {
                    "rating_key": rk,
                    "title": meta.get("title") or "",
                    "year": meta.get("year"),
                    "leaf_count": meta.get("leafCount") or 0,
                    "section_key": skey,
                    "section_title": stitle,
                }
                bucket = grouped.setdefault(
                    guid_id,
                    {
                        "guid_id": guid_id,
                        "media_type": stype,
                        "title": meta.get("title") or "",
                        "items": [],
                    },
                )
                bucket["items"].append(entry)

        result: List[Dict[str, Any]] = []
        for bucket in grouped.values():
            if len(bucket["items"]) < 2:
                continue
            # 标题取集数/条目数最多的那个条目，避免误用残缺副本的名称
            top = max(bucket["items"], key=lambda x: int(x.get("leaf_count") or 0))
            bucket["title"] = top["title"]
            bucket["items"].sort(
                key=lambda x: int(x.get("leaf_count") or 0), reverse=True
            )
            result.append(bucket)
        return result

    def merge_items(self, primary: str, others: List[str]) -> bool:
        """
        将多个条目合并到主条目（主条目保留，其余条目并入）。

        :param primary: 保留的主条目 ratingKey
        :param others: 需并入的条目 ratingKey 列表
        :return: 成功返回 True
        """
        ids = ",".join(str(x) for x in others if str(x))
        if not ids:
            return False
        return self._put(f"/library/metadata/{primary}/merge?ids={ids}")
