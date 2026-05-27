from json import JSONDecodeError, loads
from pathlib import Path
from re import IGNORECASE, search as re_search
from subprocess import TimeoutExpired, run
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import FileItem, TransferRenameBuildEventData
from app.schemas.types import ChainEventType


class FFprobeNamingSupplement(_PluginBase):
    """
    ffprobe 命名补充
    """

    plugin_name = "ffprobe命名补充"
    plugin_desc = "整理重命名时调用 ffprobe，补全命名模板中的 videoFormat、videoCodec、videoBit、audioCodec、fps、effect，支持 STRM "
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/refs/heads/main/icons/ffmpeg.png"
    plugin_version = "0.1.8"
    plugin_author = "DDSRem"
    author_url = "https://github.com/DDSRem"
    plugin_config_prefix = "ffprobenamingsupplement_"
    plugin_order = 50
    auth_level = 1

    FFPROBE_TIMEOUT_SEC = 30

    _OVERWRITE_FILL_MISSING = "fill_missing"
    _OVERWRITE_ALWAYS = "always"

    _VIDEO_CODEC_MAP = {
        "h264": "H264",
        "avc": "H264",
        "hevc": "H265",
        "h265": "H265",
        "av1": "AV1",
        "vp9": "VP9",
        "vp8": "VP8",
        "mpeg2video": "MPEG2",
        "vc1": "VC1",
        "mpeg4": "MPEG4",
    }

    _AUDIO_CODEC_MAP = {
        "aac": "AAC",
        "eac3": "EAC3",
        "ac3": "AC3",
        "dts": "DTS",
        "truehd": "Dolby TrueHD",
        "flac": "FLAC",
        "opus": "OPUS",
        "mp3": "MP3",
        "vorbis": "Vorbis",
    }

    _HEIGHT_SNAP_TIERS: Tuple[Tuple[int, int], ...] = (
        (4320, 48),
        (2880, 48),
        (2160, 48),
        (1920, 40),
        (1800, 40),
        (1600, 40),
        (1536, 40),
        (1440, 40),
        (1366, 32),
        (1280, 32),
        (1200, 32),
        (1152, 32),
        (1080, 40),
        (1050, 32),
        (1024, 32),
        (960, 32),
        (900, 28),
        (864, 28),
        (854, 24),
        (800, 24),
        (768, 24),
        (720, 32),
        (704, 24),
        (640, 24),
        (600, 20),
        (576, 20),
        (540, 20),
        (528, 20),
        (512, 20),
        (506, 20),
        (480, 24),
        (468, 20),
        (456, 20),
        (432, 20),
        (408, 16),
        (400, 16),
        (360, 16),
        (320, 16),
        (288, 16),
        (272, 16),
        (240, 16),
        (228, 12),
        (180, 12),
        (168, 12),
        (144, 12),
        (120, 12),
    )

    _HEIGHT_FORMAT_BUCKETS: Tuple[Tuple[int, str], ...] = tuple(
        (height, f"{height}p") for height, _ in _HEIGHT_SNAP_TIERS
    )

    _WIDTH_FORMAT_BUCKETS: Tuple[Tuple[int, str], ...] = (
        (7680, "4320p"),
        (3840, "2160p"),
        (2560, "1440p"),
        (1920, "1080p"),
        (1280, "720p"),
        (854, "480p"),
        (640, "360p"),
    )

    _DV_CODEC_TAGS = frozenset({"dvh1", "dvhe", "dva1", "dvav"})

    _probe_cache = TTLCache(region="ffprobe_naming", maxsize=2048, ttl=3600)

    def __init__(self) -> None:
        """
        初始化
        """
        super().__init__()
        self._enabled = False
        self._overwrite_mode = type(self)._OVERWRITE_FILL_MISSING

    def init_plugin(self, config: dict = None) -> None:
        """
        初始化插件
        """
        if not config:
            return
        cls = type(self)
        prev_enabled = self._enabled
        self._enabled = bool(config.get("enabled"))
        if prev_enabled and not self._enabled:
            cls._clear_probe_cache()
        mode = config.get("overwrite_mode") or cls._OVERWRITE_FILL_MISSING
        self._overwrite_mode = (
            mode
            if mode in (cls._OVERWRITE_FILL_MISSING, cls._OVERWRITE_ALWAYS)
            else cls._OVERWRITE_FILL_MISSING
        )

    def get_state(self) -> bool:
        """
        获取插件状态
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        获取插件命令
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        cls = type(self)
        overwrite_items = [
            {"title": "仅补全缺失或空值", "value": cls._OVERWRITE_FILL_MISSING},
            {"title": "始终用 ffprobe 覆盖上述键", "value": cls._OVERWRITE_ALWAYS},
        ]
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "overwrite_mode",
                                            "label": "写入策略",
                                            "items": overwrite_items,
                                            "hint": (
                                                "针对 videoFormat、videoCodec、videoBit、audioCodec、fps、effect："
                                                "仅补全＝缺或空才写入；始终覆盖＝以 ffprobe 为准覆盖"
                                            ),
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "density": "compact",
                                        },
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2",
                                                },
                                                "text": (
                                                    "说明：仅在整理源文件位于本地存储时，才会调用 ffprobe 读取媒体信息；"
                                                    "若来源为网盘等非本地路径，无法访问媒体流，将跳过补全"
                                                ),
                                            },
                                        ],
                                    },
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "density": "compact",
                                            "class": "mt-2",
                                        },
                                        "content": [
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-subtitle-2 mb-2",
                                                },
                                                "text": (
                                                    "可写入重命名模板的占位符"
                                                    "（需在系统「重命名格式」中自行加入对应变量）"
                                                ),
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2",
                                                },
                                                "text": (
                                                    "{{videoFormat}} — 分辨率档（如 2160p、1080p，由视频高度推断）"
                                                ),
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2 mt-1",
                                                },
                                                "text": "{{videoCodec}} — 视频编码（如 H264、H265）",
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2 mt-1",
                                                },
                                                "text": "{{videoBit}} — 视频位深（如 8bit、10bit）",
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2 mt-1",
                                                },
                                                "text": "{{audioCodec}} — 音频编码与声道（如 EAC3 5.1、Dolby TrueHD Dolby Atmos 7.1、AAC 2.0）",
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2 mt-1",
                                                },
                                                "text": "{{fps}} — 帧率（无小数，四舍五入整数，如 24、30）",
                                            },
                                            {
                                                "component": "div",
                                                "props": {
                                                    "class": "text-body-2 mt-1",
                                                },
                                                "text": (
                                                    "{{effect}} — 动态范围/特效标签（如 DoVi、HDR10、HDR10+、HLG、SDR，"
                                                    "与系统模板变量同名）"
                                                ),
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "overwrite_mode": cls._OVERWRITE_FILL_MISSING,
        }

    def get_page(self) -> Optional[List[dict]]:
        """
        获取插件页面
        """
        pass

    def stop_service(self) -> None:
        """
        停止插件服务
        """
        type(self)._clear_probe_cache()

    @classmethod
    def _clear_probe_cache(cls) -> None:
        """
        清空 ffprobe 结果缓存（类级共享，停止或关闭插件时释放）
        """
        try:
            cls._probe_cache.clear()
        except Exception as e:
            logger.debug("【ffprobe命名补充】清理探测缓存失败 %s", e)

    @classmethod
    def _parse_frame_rate(cls, rate: Optional[str]) -> Optional[str]:
        """
        将 ffprobe 的帧率字符串转为无小数点的整型展示字符串（四舍五入）

        :param rate: 如 24000/1001 或 30
        :return: 如 24（由 23.976… 舍入）或 30
        """
        if not rate or rate in ("0/0", "N/A"):
            return None
        if "/" in rate:
            parts = rate.split("/", 1)
            try:
                num = int(parts[0].strip())
                den = int(parts[1].strip())
            except (ValueError, IndexError):
                return None
            if den == 0:
                return None
            value = num / den
        else:
            try:
                value = float(rate)
            except ValueError:
                return None
        if value <= 0:
            return None
        return str(int(round(value)))

    @classmethod
    def _snap_height_to_standard(cls, height: int) -> int:
        """
        将因 mod16 裁剪、轻微缩放导致的高度吸附到常见标准值

        :param height: ffprobe 报告的帧高度
        :return: 吸附后的高度（未命中任一容差则原样返回）
        """
        for target, tolerance in cls._HEIGHT_SNAP_TIERS:
            if abs(height - target) <= tolerance:
                return target
        return height

    @classmethod
    def _height_to_video_format(
        cls, height: Optional[int], width: Optional[int] = None
    ) -> Optional[str]:
        """
        根据视频宽/高生成分辨率标签：

        先按 width 优先匹配标准档（兼容 21:9、2.39:1 等信箱比宽屏片源），
        否则回退到按 height 吸附后降序分档，未命中则用「{height}p」
        """
        w_int: Optional[int] = None
        if width is not None:
            try:
                w_int = int(width)
            except (TypeError, ValueError):
                w_int = None
            if w_int is not None and w_int <= 0:
                w_int = None
        if w_int is not None:
            for min_w, label in cls._WIDTH_FORMAT_BUCKETS:
                if w_int >= min_w:
                    return label
        if height is None:
            return None
        try:
            h = int(height)
        except (TypeError, ValueError):
            return None
        if h <= 0:
            return None
        h = cls._snap_height_to_standard(h)
        for min_h, label in cls._HEIGHT_FORMAT_BUCKETS:
            if h >= min_h:
                return label
        return f"{h}p"

    @classmethod
    def _map_video_codec(cls, codec_name: Optional[str]) -> Optional[str]:
        if not codec_name:
            return None
        key = codec_name.lower().strip()
        return cls._VIDEO_CODEC_MAP.get(key, codec_name.upper())

    @classmethod
    def _map_audio_codec(cls, codec_name: Optional[str]) -> Optional[str]:
        if not codec_name:
            return None
        key = codec_name.lower().strip()
        return cls._AUDIO_CODEC_MAP.get(key, codec_name.upper())

    @classmethod
    def _normalize_audio_channel_tag(
        cls,
        channel_layout: Optional[str],
        channels: Optional[Any],
    ) -> Optional[str]:
        """
        从 ffprobe 的声道布局或声道数生成短标签（如 7.1、5.1、2.0）

        与编码名以空格连接，如 Dolby TrueHD 7.1、EAC3 5.1（避免 EAC3 与 5.1 连成 EAC35.1）
        """
        layout_raw = (channel_layout or "").strip()
        if layout_raw:
            layout = layout_raw.split("(", 1)[0].strip()
            low = layout.lower()
            aliases = {
                "mono": "1.0",
                "stereo": "2.0",
                "quad": "4.0",
            }
            if low in aliases:
                return aliases[low]
            cleaned = layout.replace(" ", "")
            if cleaned and all(c.isdigit() or c == "." for c in cleaned):
                return cleaned
        try:
            n = int(channels) if channels is not None else 0
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return None
        count_map = {
            1: "1.0",
            2: "2.0",
            3: "2.1",
            4: "4.0",
            5: "5.0",
            6: "5.1",
            7: "6.1",
            8: "7.1",
            10: "7.1.2",
            12: "7.1.4",
        }
        return count_map.get(n)

    @classmethod
    def _audio_stream_has_dolby_atmos_ffprobe(cls, audio_s: Dict[str, Any]) -> bool:
        """
        根据 ffprobe 音频流的 profile、codec_tag_string、tags 等判断是否含 Dolby Atmos

        Dolby TrueHD / EAC3 等与 Atmos 为不同概念；仅在元数据标明 Atmos 时为 True

        除英文「Atmos」外，识别常见中文轨标题「杜比全景声」等（无 profile 的旧版 ffprobe）
        """
        parts: List[str] = []
        prof = audio_s.get("profile")
        if prof:
            parts.append(str(prof))
        cln = audio_s.get("codec_long_name")
        if cln:
            parts.append(str(cln))
        cts = audio_s.get("codec_tag_string")
        if cts:
            parts.append(str(cts))
        tags = audio_s.get("tags")
        if isinstance(tags, dict):
            for v in tags.values():
                if v:
                    parts.append(str(v))
        joined = " ".join(parts)
        if "atmos" in joined.lower():
            return True
        return "全景声" in joined

    @classmethod
    def _format_audio_codec_label(
        cls,
        codec_name: Optional[str],
        channel_layout: Optional[str],
        channels: Optional[Any],
        *,
        dolby_atmos: bool = False,
    ) -> Optional[str]:
        """
        编码名、可选 Dolby Atmos、声道标签（均空格分隔），用于 rename_dict audioCodec

        含 Atmos 时顺序为「基带编码 Dolby Atmos 声道」，如 Dolby TrueHD Dolby Atmos 7.1
        """
        ac = cls._map_audio_codec(codec_name)
        if not ac:
            return None
        tag = cls._normalize_audio_channel_tag(channel_layout, channels)
        parts: List[str] = [ac]
        if dolby_atmos:
            parts.append("Dolby Atmos")
        if tag:
            parts.append(tag)
        return " ".join(parts)

    @classmethod
    def _video_stream_hdr_flags(cls, video_s: Dict[str, Any]) -> Tuple[bool, bool]:
        """
        从视频流 side_data 与 codec_tag 判断是否含 Dolby Vision / HDR10+ 元数据

        :param video_s: ffprobe 单路视频流 dict
        :return: (has_dovi, has_hdr10plus)
        """
        has_dovi = False
        has_hdr10plus = False
        tag = (video_s.get("codec_tag_string") or "").strip().lower()
        if tag in cls._DV_CODEC_TAGS:
            has_dovi = True
        side_list = video_s.get("side_data_list")
        if not isinstance(side_list, list):
            return has_dovi, has_hdr10plus
        for item in side_list:
            if not isinstance(item, dict):
                continue
            sdt = (item.get("side_data_type") or "").lower()
            if "dovi" in sdt or "dolby vision" in sdt:
                has_dovi = True
            if "smpte2094-40" in sdt or "2094-40" in sdt:
                has_hdr10plus = True
            if "hdr10+" in sdt and "dynamic" in sdt:
                has_hdr10plus = True
        return has_dovi, has_hdr10plus

    @classmethod
    def _infer_effect_from_video_stream(cls, video_s: Dict[str, Any]) -> Optional[str]:
        """
        根据 ffprobe 色彩与 side_data 推断与 MoviePilot 模板变量 effect 对应的标签

        输出与常见资源命名接近的短标签，多个以空格连接（如 DoVi、HDR10+）

        :param video_s: ffprobe 单路视频流 dict
        :return: 供 rename_dict["effect"] 使用的字符串，无法判断则 None
        """
        has_dovi, has_hdr10plus = cls._video_stream_hdr_flags(video_s)
        ct = (video_s.get("color_transfer") or "").lower().strip()
        cp = (video_s.get("color_primaries") or "").lower().strip()
        cs = (video_s.get("color_space") or "").lower().strip()

        tokens: List[str] = []
        if has_dovi:
            tokens.append("DoVi")
        if has_hdr10plus:
            tokens.append("HDR10+")
        if not has_dovi and not has_hdr10plus:
            if ct == "smpte2084":
                tokens.append("HDR10")
            elif "arib-std-b67" in ct:
                tokens.append("HLG")

        if not tokens:
            primaries_ok = not cp or cp == "bt709"
            transfer_sdr = ct == "bt709" or (not ct and cs == "bt709")
            if transfer_sdr and primaries_ok:
                tokens.append("SDR")

        if not tokens:
            return None
        return " ".join(tokens)

    @classmethod
    def _pick_video_audio_streams(
        cls, streams: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        选取首路视频；音轨优先 disposition.default，与播放器默认轨一致，避免误用非主音轨
        """
        video_s: Optional[Dict[str, Any]] = None
        audio_s: Optional[Dict[str, Any]] = None
        audios: List[Dict[str, Any]] = []
        for s in streams:
            if not isinstance(s, dict):
                continue
            ct = s.get("codec_type")
            if ct == "video" and video_s is None:
                video_s = s
            elif ct == "audio":
                audios.append(s)
        if audios:
            for s in audios:
                disp = s.get("disposition")
                if isinstance(disp, dict) and disp.get("default") == 1:
                    audio_s = s
                    break
            if audio_s is None:
                audio_s = audios[0]
        return video_s, audio_s

    @classmethod
    def _extract_video_bit_depth(cls, video_s: Dict[str, Any]) -> Optional[str]:
        """
        从 ffprobe 视频流提取位深，如 8bit、10bit

        :param video_s: ffprobe 视频流字典
        :return: 位深字符串或 None
        """
        bps = str(video_s.get("bits_per_raw_sample") or "").strip()
        if bps and bps.isdigit():
            return f"{bps}bit"
        pix = str(video_s.get("pix_fmt") or "").strip().lower()
        if pix:
            m = re_search(r"(\d+)(le|be)", pix)
            if m:
                n = int(m.group(1))
                if n > 0:
                    return f"{n}bit"
        prof = str(video_s.get("profile") or "").strip()
        if prof:
            m = re_search(r"(?:main|high)\s*(\d+)", prof, IGNORECASE)
            if m:
                return f"{m.group(1)}bit"
        if pix:
            return "8bit"
        return None

    @classmethod
    def _probe_to_rename_fields(cls, probe_json: Dict[str, Any]) -> Dict[str, str]:
        """
        从 ffprobe JSON 提取写入 rename_dict 的命名模板字段
        """
        out: Dict[str, str] = {}
        streams = probe_json.get("streams")
        if not isinstance(streams, list):
            return out
        video_s, audio_s = cls._pick_video_audio_streams(streams)
        if video_s:
            height = video_s.get("height")
            try:
                h_int = int(height) if height is not None else None
            except (TypeError, ValueError):
                h_int = None
            width = video_s.get("width")
            try:
                w_int = int(width) if width is not None else None
            except (TypeError, ValueError):
                w_int = None
            vf = cls._height_to_video_format(h_int, w_int)
            if vf:
                out["videoFormat"] = vf
            vc = cls._map_video_codec(video_s.get("codec_name"))
            if vc:
                out["videoCodec"] = vc
            vb = cls._extract_video_bit_depth(video_s)
            if vb:
                out["videoBit"] = vb
            fps = cls._parse_frame_rate(
                video_s.get("avg_frame_rate")
            ) or cls._parse_frame_rate(video_s.get("r_frame_rate"))
            if fps:
                out["fps"] = fps
            eff = cls._infer_effect_from_video_stream(video_s)
            if eff:
                out["effect"] = eff
        if audio_s:
            atmos = cls._audio_stream_has_dolby_atmos_ffprobe(audio_s)
            ac = cls._format_audio_codec_label(
                audio_s.get("codec_name"),
                audio_s.get("channel_layout"),
                audio_s.get("channels"),
                dolby_atmos=atmos,
            )
            if ac:
                out["audioCodec"] = ac
        return out

    @classmethod
    def _normalize_strm_target(cls, raw: str) -> str:
        """
        规范化 STRM 首行内容，便于 ffprobe 作为 -i 参数使用

        :param raw: 行内原始文本（已去掉首尾空白）
        :return: 规范化后的地址或路径，无效则空字符串
        """
        line = raw.strip()
        if not line:
            return ""
        if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
            line = line[1:-1].strip()
        if "%" in line:
            try:
                line = unquote(line)
            except Exception:
                pass
        return line.strip()

    @classmethod
    def _resolve_probe_target(cls, source_path: str) -> Optional[str]:
        """
        普通文件直接返回路径；STRM 读取首条有效行并规范化后作为真实地址
        """
        p = Path(source_path)
        if p.suffix.lower() != ".strm":
            return source_path.strip()
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            logger.warning("【ffprobe命名补充】读取 STRM 失败 %s: %s", source_path, e)
            return None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.lstrip().startswith("#"):
                continue
            normalized = cls._normalize_strm_target(line)
            if normalized:
                return normalized
        logger.warning("【ffprobe命名补充】STRM 内容为空 %s", source_path)
        return None

    @classmethod
    def _should_apply_key(
        cls, overwrite_mode: str, key: str, rename_dict: Dict[str, Any], new_val: str
    ) -> bool:
        if not new_val:
            return False
        if overwrite_mode == cls._OVERWRITE_ALWAYS:
            return True
        cur = rename_dict.get(key)
        if cur is None:
            return True
        if isinstance(cur, str):
            cur_stripped = cur.strip()
            if not cur_stripped:
                return True
            if key == "audioCodec" and not re_search(r"\d+\.\d+", cur_stripped):
                return True
        return False

    @classmethod
    def _run_ffprobe(cls, probe_target: str) -> Optional[Dict[str, Any]]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            "-i",
            probe_target,
        ]
        try:
            proc = run(
                cmd,
                capture_output=True,
                text=True,
                timeout=cls.FFPROBE_TIMEOUT_SEC,
            )
        except TimeoutExpired:
            logger.warning(
                "【ffprobe命名补充】ffprobe 超时(%ss) target=%s",
                cls.FFPROBE_TIMEOUT_SEC,
                probe_target,
            )
            return None
        except OSError as e:
            logger.warning("【ffprobe命名补充】无法执行 ffprobe: %s", e)
            return None
        if proc.returncode != 0:
            err = (proc.stderr or "").strip() or proc.stdout
            logger.debug(
                "【ffprobe命名补充】ffprobe 失败 rc=%s target=%s err=%s",
                proc.returncode,
                probe_target,
                err[:500] if err else "",
            )
            return None
        try:
            return loads(proc.stdout)
        except JSONDecodeError as e:
            logger.warning("【ffprobe命名补充】ffprobe JSON 解析失败: %s", e)
            return None

    @eventmanager.register(ChainEventType.TransferRenameBuild)
    def on_transfer_rename_build(self, event: Event) -> None:
        """
        处理 TransferRenameBuild 链式事件，在主程序首次渲染前把 ffprobe
        解析到的字段写入 rename_dict。

        与渲染后的 TransferRename 字符串改写类插件天然分层、互不冲突。
        """
        if not self._enabled:
            return
        data = event.event_data
        if not isinstance(data, TransferRenameBuildEventData):
            return
        source_path: Optional[str] = data.source_path
        source_item: Optional[FileItem] = data.source_item
        if not source_path or not str(source_path).strip():
            logger.debug("【ffprobe命名补充】source_path 为空，跳过本次重命名补全")
            return
        if not source_item:
            logger.debug("【ffprobe命名补充】source_item 为空，跳过本次重命名补全")
            return
        if source_item.storage != "local":
            logger.debug(
                "【ffprobe命名补充】source_item 不是本地文件，跳过本次重命名补全"
            )
            return
        source_path = str(source_path).strip()
        rename_dict = data.rename_dict
        if not isinstance(rename_dict, dict):
            return

        if source_item.type != "file":
            logger.debug("【ffprobe命名补充】圆盘整理跳过本次重命名补全")
            return

        if Path(source_path).suffix.lower() not in settings.RMT_MEDIAEXT:
            logger.debug("【ffprobe命名补充】文件后缀不是媒体文件，跳过本次重命名补全")
            return

        cls = type(self)
        probe_target = cls._resolve_probe_target(source_path)
        if not probe_target:
            return

        probe_json = self._probe_cache.get(probe_target)
        if probe_json is None:
            probe_json = cls._run_ffprobe(probe_target)
            if probe_json is None:
                return
            self._probe_cache.set(probe_target, probe_json)

        fields = cls._probe_to_rename_fields(probe_json)
        if not fields:
            logger.debug(
                "【ffprobe命名补充】未解析到可用媒体信息 target=%s", probe_target
            )
            return

        for key, val in fields.items():
            if cls._should_apply_key(self._overwrite_mode, key, rename_dict, val):
                rename_dict[key] = val
