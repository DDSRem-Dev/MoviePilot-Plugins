"""Emby API 轻封装：按文件名/路径查询条目的 MediaStreams 媒体流信息。"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse, unquote

from httpx import Client

from app.sdk.logging import logger


class EmbyClient:
    """封装 Emby 只读查询，用于按文件名匹配媒体并取其媒体流信息作为数据源。"""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        """
        初始化 Emby 客户端。

        :param base_url: Emby 根地址，如 http://192.168.0.121:8096
        :param api_key: Emby API Key
        :param timeout: 请求超时秒数
        """
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout
        self._user_id: Optional[str] = None

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Optional[dict]:
        """
        发起 GET 请求并解析 JSON。

        :param path: 相对路径
        :param params: 查询参数
        :return: JSON 或 None
        """
        query = {"api_key": self._key}
        if params:
            query.update(params)
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in query.items())
        url = f"{self._base}{path}?{qs}"
        try:
            with Client(timeout=self._timeout) as client:
                resp = client.get(url, headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    return resp.json()
                logger.warning("Emby API %s 返回 %s", path, resp.status_code)
        except Exception as e:
            logger.warning("Emby API 请求失败 %s: %s", path, e)
        return None

    def find_streams_by_name(self, file_name: str) -> Optional[Dict[str, Any]]:
        """
        搜索 Emby 条目并返回其归一化媒体流信息。

        匹配策略（按优先级）：
        1) 从 STRM 路径的 {tmdb-xxxxx} 提取 TMDB ID，用 AnyProviderIdEquals 精确定位
           条目/剧集，再用文件名匹配具体 MediaSource（Emby 条目名是媒体标题而非
           带画质标签的长文件名，用文件名当 SearchTerm 往往搜不到）。
        2) 回退：用文件名 stem 作为 SearchTerm 模糊搜。

        :param file_name: STRM 文件路径或文件名
        :return: 归一化后的媒体信息 dict，未找到返回 None
        """
        stem = os.path.splitext(os.path.basename(file_name))[0]
        if not stem:
            return None

        # 策略1：按路径中的 TMDB ID 精确搜
        tmdb_id = self._extract_tmdb_id(file_name)
        if tmdb_id:
            data = self._get(
                "/Items",
                {
                    "Recursive": "true",
                    "AnyProviderIdEquals": f"tmdb.{tmdb_id}",
                    "Fields": "MediaSources,Path",
                    "Limit": "50",
                },
            )
            if data:
                items = data.get("Items", []) or []
                # 剧集的 tmdb-xxxx 是剧集级 ID，命中的是 Series 条目，本身没有
                # MediaSources，真正带流信息的是每个 Episode。需下钻到集再按文件名匹配。
                series_items = [
                    it for it in items
                    if it.get("Type") == "Series" or not (it.get("MediaSources"))
                ]
                for it in series_items:
                    sid = it.get("Id")
                    if not sid:
                        continue
                    info = self._find_in_series_episodes(sid, stem)
                    if info:
                        return info
                # 电影/直接可播放条目：先按文件名精确匹配 MediaSource
                for item in items:
                    info = self._extract_from_item(item, stem)
                    if info:
                        return info
                # 电影通常单条单源，未精确匹配上时取第一个有流的源兜底
                for item in items:
                    for src in item.get("MediaSources") or []:
                        info = self._normalize_source(src)
                        if info:
                            return info

        # 策略2：回退到文件名 SearchTerm 模糊搜
        data = self._get(
            "/Items",
            {
                "Recursive": "true",
                "SearchTerm": stem,
                "Fields": "MediaSources,Path",
                "Limit": "5",
            },
        )
        if not data:
            return None
        for item in data.get("Items", []) or []:
            info = self._extract_from_item(item, stem)
            if info:
                return info
        return None

    def _find_in_series_episodes(
        self, series_id: str, want_stem: str
    ) -> Optional[Dict[str, Any]]:
        """
        下钻某 Emby 剧集（Series）的所有集，按文件名 stem 精确匹配某一集的媒体流信息。

        剧集路径里的 tmdb-xxxx 是剧集级 ID，命中的 Series 条目本身无 MediaSources，
        真正带流信息的是每个 Episode，需用 /Shows/{id}/Episodes 下钻后匹配。

        :param series_id: Emby Series 条目 Id
        :param want_stem: 目标无扩展名文件名
        :return: 归一化媒体信息，未匹配返回 None
        """
        data = self._get(
            f"/Shows/{series_id}/Episodes",
            {"Fields": "MediaSources,Path", "Limit": "2000"},
        )
        if not data:
            return None
        for ep in data.get("Items", []) or []:
            info = self._extract_from_item(ep, want_stem)
            if info:
                return info
        return None

    @staticmethod
    def _extract_tmdb_id(path: str) -> Optional[str]:
        """
        从 STRM 路径中提取 {tmdb-xxxxx} 里的 TMDB ID。

        :param path: STRM 文件路径
        :return: TMDB ID 字符串，未找到返回 None
        """
        if not path:
            return None
        m = re.search(r"tmdb-(\d+)", path, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _basename_stem(path: str) -> str:
        """
        取路径的无扩展名文件名。

        兼容 STRM 直链场景：Emby 中 STRM 条目的 MediaSource.Path 常是
        P115StrmHelper 等插件的 302 直链（形如
        http://host/api/.../redirect_url?pickcode=xxx&file_name=真实文件名.mkv），
        此时 basename 会取到 query 串，需优先从 file_name 参数还原真实文件名。

        注意不能用 parse_qs：它按表单编码把 "+" 解成空格，会破坏
        "Disney+" 这类含加号的文件名。这里手动切 query 并只做百分号解码。
        """
        if not path:
            return ""
        # 直链场景：优先取 query 中的 file_name 参数
        if path.startswith(("http://", "https://")):
            try:
                query = urlparse(path).query
                for kv in query.split("&"):
                    for key in ("file_name=", "filename="):
                        if kv.startswith(key):
                            fname = unquote(kv[len(key):]).strip()
                            if fname:
                                return os.path.splitext(os.path.basename(fname))[0]
            except Exception:
                pass
        return os.path.splitext(os.path.basename(path))[0]

    def _extract_from_item(
        self, item: Dict[str, Any], want_stem: str
    ) -> Optional[Dict[str, Any]]:
        """
        从 Emby 条目中匹配文件名并抽取归一化媒体流信息。

        :param item: Emby 条目
        :param want_stem: 目标无扩展名文件名
        :return: 归一化媒体信息，不匹配返回 None
        """
        sources = item.get("MediaSources") or []
        for src in sources:
            src_stem = self._basename_stem(src.get("Path") or src.get("Name") or "")
            if src_stem and src_stem != want_stem:
                continue
            info = self._normalize_source(src)
            if info:
                return info
        return None

    def _normalize_source(self, src: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        将 Emby MediaSource 归一化为 helper 需要的 payload 结构。

        :param src: Emby MediaSource
        :return: 归一化后的媒体信息
        """
        streams_in = src.get("MediaStreams") or []
        if not streams_in:
            return None
        # Emby 时长单位 100 纳秒(ticks)，转毫秒
        ticks = src.get("RunTimeTicks")
        duration_ms = int(ticks / 10000) if ticks else None
        info: Dict[str, Any] = {
            "container": (src.get("Container") or "").split(",")[0] or None,
            "size": src.get("Size"),
            "bitrate": int(src["Bitrate"] / 1000) if src.get("Bitrate") else None,
            "duration": duration_ms,
            "streams": [],
            "source": "emby",
        }
        # Emby MediaStream.Type: Video/Audio/Subtitle -> Plex stream_type 1/2/3
        type_map = {"Video": 1, "Audio": 2, "Subtitle": 3}
        video_seen = False
        audio_seen = False
        for s in streams_in:
            stype = type_map.get(s.get("Type"))
            if not stype:
                continue
            stream = {
                "stream_type": stype,
                "codec": (s.get("Codec") or "").lower() or None,
                "index": s.get("Index"),
                "language": s.get("Language"),
            }
            if stype == 1:
                stream.update(
                    {
                        "width": s.get("Width"),
                        "height": s.get("Height"),
                        "bitrate": int(s["BitRate"] / 1000) if s.get("BitRate") else None,
                        "frame_rate": s.get("RealFrameRate") or s.get("AverageFrameRate"),
                        "bit_depth": s.get("BitDepth"),
                    }
                )
                if not video_seen:
                    info["width"] = s.get("Width")
                    info["height"] = s.get("Height")
                    info["video_codec"] = (s.get("Codec") or "").lower() or None
                    info["frame_rate"] = s.get("RealFrameRate") or s.get("AverageFrameRate")
                    video_seen = True
            elif stype == 2:
                stream.update(
                    {
                        "bitrate": int(s["BitRate"] / 1000) if s.get("BitRate") else None,
                        "channels": s.get("Channels"),
                        "sampling_rate": s.get("SampleRate"),
                    }
                )
                if not audio_seen:
                    info["audio_codec"] = (s.get("Codec") or "").lower() or None
                    info["audio_channels"] = s.get("Channels")
                    audio_seen = True
            info["streams"].append(stream)
        return info if info["streams"] else None
