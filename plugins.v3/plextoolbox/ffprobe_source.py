"""ffprobe 数据源：读取 STRM 内容并探测其中的远程媒体直链。"""

from __future__ import annotations

import json
import logging
import math
import os
import posixpath
import re
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from app.sdk.logging import logger
except Exception:  # pragma: no cover - standalone helper/unit-test fallback
    logger = logging.getLogger(__name__)


PathMapping = Tuple[str, str]


def _normalise_path(path: str) -> str:
    """以 POSIX 规则规范化 Plex/容器路径，保留根路径。"""
    value = (path or "").strip()
    if not value:
        return ""
    normalised = posixpath.normpath(value)
    return normalised if normalised == "/" else normalised.rstrip("/")


def parse_path_map(raw: str) -> List[PathMapping]:
    """
    解析 Plex 路径到 MoviePilot 路径的映射。

    支持每行一条 ``Plex路径=/容器路径`` 或 ``Plex路径 => /容器路径``，
    也兼容用分号分隔的多条规则。较长的源前缀会在应用时优先匹配。
    """
    mappings: List[PathMapping] = []
    for line in (raw or "").replace(";", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=>" in line:
            source, target = line.split("=>", 1)
        elif "=" in line:
            source, target = line.split("=", 1)
        else:
            logger.warning("PlexToolbox 路径映射格式错误，已忽略: %s", line)
            continue
        source = _normalise_path(source)
        target = _normalise_path(target)
        if not source or not target or not source.startswith("/") or not target.startswith("/"):
            logger.warning("PlexToolbox 路径映射需使用绝对路径，已忽略: %s", line)
            continue
        item = (source, target)
        if item not in mappings:
            mappings.append(item)
    return sorted(mappings, key=lambda item: len(item[0]), reverse=True)


def map_path(path: str, mappings: Iterable[PathMapping]) -> str:
    """将 Plex 文件路径按最长前缀映射为 MoviePilot 可访问的路径。"""
    value = (path or "").strip()
    if not value:
        return ""
    normalised = _normalise_path(value)
    for source, target in mappings:
        if normalised == source or normalised.startswith(source + "/"):
            suffix = normalised[len(source):]
            return target + suffix
    return normalised


def read_strm_url(strm_path: str) -> str:
    """
    读取 STRM 文件中的第一个有效 HTTP(S) 地址。

    :param strm_path: 对 MoviePilot 进程可读的 STRM 路径
    :return: STRM 内的远程地址，无法读取时返回空串
    """
    if not strm_path:
        return ""
    if strm_path.startswith(("http://", "https://")):
        return strm_path
    try:
        if not os.path.isfile(strm_path):
            return ""
        with open(strm_path, "r", encoding="utf-8", errors="replace") as stream_file:
            for line in stream_file:
                candidate = line.strip().lstrip("\ufeff")
                if not candidate or candidate.startswith("#"):
                    continue
                return candidate if candidate.startswith(("http://", "https://")) else ""
    except OSError as exc:
        logger.debug("读取 STRM 失败 %s: %s", strm_path, exc)
    return ""


def _number(value: Any) -> Optional[float]:
    """将 ffprobe 的数字或 N/A 安全转换为有限浮点数。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> Optional[int]:
    """将 ffprobe 数字安全转换为整数。"""
    number = _number(value)
    return int(number) if number is not None else None


def _kbps(value: Any) -> Optional[int]:
    """将 ffprobe 的 bit/s 转成 Plex 使用的 kbit/s。"""
    number = _integer(value)
    return int(number / 1000) if number is not None else None


def _parse_fps(value: Any) -> Optional[float]:
    """解析 ``24000/1001`` 等帧率表示。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"N/A", "0/0"}:
        return None
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_number = float(denominator)
            if denominator_number == 0:
                return None
            rate = float(numerator) / denominator_number
        else:
            rate = float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return round(rate, 3) if math.isfinite(rate) and rate > 0 else None


def _tag_value(tags: Any, name: str) -> Optional[str]:
    """大小写不敏感地读取 ffprobe stream tag。"""
    if not isinstance(tags, dict):
        return None
    wanted = name.lower()
    for key, value in tags.items():
        if str(key).lower() == wanted and value not in (None, ""):
            return str(value)
    return None


def _normalise_codec(codec_type: str, codec: Any) -> Optional[str]:
    """将少数 ffprobe 专用字幕 codec 名称归一化为 Plex 常用名称。"""
    value = str(codec or "").strip().lower()
    if not value:
        return None
    if codec_type == "subtitle":
        return {
            "subrip": "srt",
            "hdmv_pgs_subtitle": "pgs",
            "dvd_subtitle": "vobsub",
        }.get(value, value)
    return value


def _normalise_container(format_name: Any) -> Optional[str]:
    """取 ffprobe format_name 的首个候选并转成常见容器名。"""
    value = str(format_name or "").split(",", 1)[0].strip().lower()
    if not value:
        return None
    return {
        "matroska": "mkv",
        "mov": "mp4",
        "mpegts": "ts",
        "hls": "m3u8",
    }.get(value, value)


def _bit_depth(stream: Dict[str, Any]) -> Optional[int]:
    """从 bits_per_raw_sample 或 pix_fmt 推断视频位深。"""
    explicit = _integer(stream.get("bits_per_raw_sample"))
    if explicit:
        return explicit
    pixel_format = str(stream.get("pix_fmt") or "").lower()
    match = re.search(r"(?:p|yuv|rgb)?(16|12|10)(?:le|be)?", pixel_format)
    if match:
        return int(match.group(1))
    return 8 if pixel_format else None


def _normalize_ffprobe(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将 ffprobe JSON 归一化为 helper 接受的媒体信息载荷。

    :param data: ``ffprobe -print_format json -show_format -show_streams`` 输出
    :return: 归一化媒体信息；没有视频/音频/字幕流时返回 None
    """
    if not isinstance(data, dict):
        return None
    fmt = data.get("format") or {}
    streams_in = data.get("streams") or []
    if not isinstance(fmt, dict) or not isinstance(streams_in, list):
        return None

    duration_seconds = _number(fmt.get("duration"))
    if duration_seconds is None:
        stream_durations = [_number(item.get("duration")) for item in streams_in if isinstance(item, dict)]
        stream_durations = [item for item in stream_durations if item is not None]
        if stream_durations:
            duration_seconds = max(stream_durations)

    info: Dict[str, Any] = {
        "container": _normalise_container(fmt.get("format_name")),
        "size": _integer(fmt.get("size")),
        "bitrate": _kbps(fmt.get("bit_rate")),
        "duration": int(duration_seconds * 1000) if duration_seconds is not None else None,
        "streams": [],
        "source": "ffprobe",
    }
    type_map = {"video": 1, "audio": 2, "subtitle": 3}
    video_seen = False
    audio_seen = False
    for source_stream in streams_in:
        if not isinstance(source_stream, dict):
            continue
        codec_type = str(source_stream.get("codec_type") or "").lower()
        stream_type = type_map.get(codec_type)
        if not stream_type:
            continue
        codec = _normalise_codec(codec_type, source_stream.get("codec_name"))
        stream: Dict[str, Any] = {
            "stream_type": stream_type,
            "codec": codec,
            "index": _integer(source_stream.get("index")),
            "language": _tag_value(source_stream.get("tags"), "language"),
        }
        if stream_type == 1:
            frame_rate = _parse_fps(
                source_stream.get("avg_frame_rate") or source_stream.get("r_frame_rate")
            )
            stream.update(
                {
                    "width": _integer(source_stream.get("width")),
                    "height": _integer(source_stream.get("height")),
                    "bitrate": _kbps(source_stream.get("bit_rate")),
                    "frame_rate": frame_rate,
                    "bit_depth": _bit_depth(source_stream),
                }
            )
            if not video_seen:
                info.update(
                    {
                        "width": _integer(source_stream.get("width")),
                        "height": _integer(source_stream.get("height")),
                        "video_codec": codec,
                        "frame_rate": frame_rate,
                        "display_aspect_ratio": _number(
                            source_stream.get("display_aspect_ratio")
                        ),
                    }
                )
                video_seen = True
        elif stream_type == 2:
            stream.update(
                {
                    "bitrate": _kbps(source_stream.get("bit_rate")),
                    "channels": _integer(source_stream.get("channels")),
                    "sampling_rate": _integer(source_stream.get("sample_rate")),
                }
            )
            if not audio_seen:
                info.update(
                    {
                        "audio_codec": codec,
                        "audio_channels": _integer(source_stream.get("channels")),
                    }
                )
                audio_seen = True
        info["streams"].append(stream)
    return info if info["streams"] else None


def ffprobe_url(
    url: str, timeout: float = 40.0, executable: str = "ffprobe"
) -> Optional[Dict[str, Any]]:
    """
    对远程媒体 URL 执行 ffprobe。

    ffprobe 自带 HTTP 302 跟随能力，因此直接探测 STRM 中的 P115 地址即可，
    不额外做 HEAD 请求，避免部分 302 服务不支持 HEAD 或导致一次额外延迟。
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        timeout_value = max(1.0, float(timeout))
    except (TypeError, ValueError):
        timeout_value = 40.0
    command = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-analyzeduration",
        "10000000",
        "-probesize",
        "10000000",
        url,
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_value,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.debug("ffprobe 执行超时")
        return None
    except OSError as exc:
        logger.debug("ffprobe 进程错误: %s", exc)
        return None
    if process.returncode != 0:
        # stderr 可能回显包含授权参数的输入 URL，不写入日志。
        logger.debug("ffprobe 返回码 %s", process.returncode)
        return None
    try:
        result = json.loads(process.stdout or "{}")
    except (TypeError, ValueError) as exc:
        logger.debug("ffprobe JSON 解析失败: %s", exc)
        return None
    return _normalize_ffprobe(result)


class FfprobeSource:
    """将 Plex 返回的文件路径转换为 MP 路径并提供 ffprobe 媒体信息。"""

    def __init__(self, path_map: str = "", timeout: float = 40.0) -> None:
        self._mappings = parse_path_map(path_map)
        try:
            self._timeout = max(1.0, float(timeout))
        except (TypeError, ValueError):
            self._timeout = 40.0

    def mapped_path(self, plex_path: str) -> str:
        """返回当前 MoviePilot 容器实际可访问的路径。"""
        return map_path(plex_path, self._mappings)

    def find_streams_by_name(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        读取 Plex STRM 的首行 URL并探测媒体流。

        :param file_path: Plex API 返回的 STRM 路径，或直接的 HTTP(S) URL
        :return: helper 媒体信息载荷，失败返回 None
        """
        if not file_path:
            return None
        if file_path.startswith(("http://", "https://")):
            mapped = file_path
            url = file_path
        else:
            mapped = self.mapped_path(file_path)
            url = read_strm_url(mapped)
        # 映射配置写错时仍尝试原始路径，兼容 Plex 与 MP 共享同一目录的情况。
        if not url and mapped != file_path:
            url = read_strm_url(file_path)
        if not url:
            logger.debug("ffprobe 找不到 STRM URL: %s", mapped)
            return None
        info = ffprobe_url(url, timeout=self._timeout)
        if info:
            return info
        logger.debug("ffprobe 未解析到媒体流: %s", mapped)
        return None
