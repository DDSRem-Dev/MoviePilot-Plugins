__all__ = ["RenameDictUtils"]

from re import IGNORECASE, search as re_search
from typing import Any, Callable, Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import unquote
from subprocess import run, TimeoutExpired

from orjson import loads, JSONDecodeError


class RenameDictUtils:
    """
    重命名字典工具类
    """

    FFPROBE_TIMEOUT_SEC = 30

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

    _WIDTH_FORMAT_BUCKETS: Tuple[Tuple[int, str], ...] = (
        (7680, "4320p"),
        (3840, "2160p"),
        (2560, "1440p"),
        (1920, "1080p"),
        (1280, "720p"),
        (854, "480p"),
        (640, "360p"),
    )

    _HEIGHT_FORMAT_BUCKETS: Tuple[Tuple[int, str], ...] = tuple(
        (height, f"{height}p") for height, _ in _HEIGHT_SNAP_TIERS
    )

    _DV_CODEC_TAGS = frozenset({"dvh1", "dvhe", "dva1", "dvav"})

    @staticmethod
    def _parse_frame_rate(rate: Optional[str]) -> Optional[str]:
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

    @staticmethod
    def _snap_height_to_standard(height: int) -> int:
        """
        将因 mod16 裁剪、轻微缩放导致的高度吸附到常见标准值

        :param height: ffprobe 报告的帧高度
        :return: 吸附后的高度（未命中任一容差则原样返回）
        """
        for target, tolerance in RenameDictUtils._HEIGHT_SNAP_TIERS:
            if abs(height - target) <= tolerance:
                return target
        return height

    @staticmethod
    def _height_to_video_format(
        height: Optional[int], width: Optional[int] = None
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
            for min_w, label in RenameDictUtils._WIDTH_FORMAT_BUCKETS:
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
        h = RenameDictUtils._snap_height_to_standard(h)
        for min_h, label in RenameDictUtils._HEIGHT_FORMAT_BUCKETS:
            if h >= min_h:
                return label
        return f"{h}p"

    @staticmethod
    def _map_video_codec(codec_name: Optional[str]) -> Optional[str]:
        if not codec_name:
            return None
        key = codec_name.lower().strip()
        return RenameDictUtils._VIDEO_CODEC_MAP.get(key, codec_name.upper())

    @staticmethod
    def _map_audio_codec(codec_name: Optional[str]) -> Optional[str]:
        if not codec_name:
            return None
        key = codec_name.lower().strip()
        return RenameDictUtils._AUDIO_CODEC_MAP.get(key, codec_name.upper())

    @staticmethod
    def _normalize_audio_channel_tag(
        channel_layout: Optional[str],
        channels: Optional[Any],
    ) -> Optional[str]:
        """
        从 ffprobe / Emby 的声道布局或声道数生成短标签（如 7.1、5.1、2.0）

        与编码名以空格连接，如 Dolby TrueHD 7.1、EAC3 5.1（避免 EAC3 与 5.1 连成 EAC35.1）

        :param channel_layout: channel_layout 或 ChannelLayout 字符串
        :param channels: 声道数量
        :return: 无可靠信息时 None
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

    @staticmethod
    def _audio_stream_has_dolby_atmos_ffprobe(audio_s: Dict[str, Any]) -> bool:
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
        # 杜比全景声 = Dolby Atmos 中文常用写法，与 ASCII「atmos」无关
        return "全景声" in joined

    @staticmethod
    def _audio_stream_has_dolby_atmos_emby(audio_s: Dict[str, Any]) -> bool:
        """
        根据 Emby MediaStream 判断是否含 Dolby Atmos（与基带编码分列展示）

        Emby 常在 Title 写「杜比全景声」，DisplayTitle 可能仅为「TRUEHD 7.1」，故必须包含 Title
        """
        parts: List[str] = []
        for key in ("Profile", "Title", "DisplayTitle", "Codec", "CodecTag"):
            v = audio_s.get(key)
            if v:
                parts.append(str(v))
        joined = " ".join(parts)
        if "atmos" in joined.lower():
            return True
        return "全景声" in joined

    @staticmethod
    def _format_audio_codec_label(
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
        ac = RenameDictUtils._map_audio_codec(codec_name)
        if not ac:
            return None
        tag = RenameDictUtils._normalize_audio_channel_tag(channel_layout, channels)
        parts: List[str] = [ac]
        if dolby_atmos:
            parts.append("Dolby Atmos")
        if tag:
            parts.append(tag)
        return " ".join(parts)

    @staticmethod
    def _video_stream_hdr_flags(video_s: Dict[str, Any]) -> Tuple[bool, bool]:
        """
        从视频流 side_data 与 codec_tag 判断是否含 Dolby Vision / HDR10+ 元数据

        :param video_s: ffprobe 单路视频流 dict
        :return: (has_dovi, has_hdr10plus)
        """
        has_dovi = False
        has_hdr10plus = False
        tag = (video_s.get("codec_tag_string") or "").strip().lower()
        if tag in RenameDictUtils._DV_CODEC_TAGS:
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

    @staticmethod
    def _infer_effect_from_video_stream(video_s: Dict[str, Any]) -> Optional[str]:
        """
        根据 ffprobe 色彩与 side_data 推断与 MoviePilot 模板变量 effect 对应的标签

        输出与常见资源命名接近的短标签，多个以空格连接（如 DoVi、HDR10+）

        :param video_s: ffprobe 单路视频流 dict
        :return: 供 rename_dict["effect"] 使用的字符串，无法判断则 None
        """
        has_dovi, has_hdr10plus = RenameDictUtils._video_stream_hdr_flags(video_s)
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

    @staticmethod
    def _pick_video_audio_streams(
        streams: List[Dict[str, Any]],
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

    @staticmethod
    def _extract_video_bit_depth(video_s: Dict[str, Any]) -> Optional[str]:
        """从 ffprobe 视频流提取位深，如 8bit、10bit"""
        bps = (video_s.get("bits_per_raw_sample") or "").strip()
        if bps and bps.isdigit():
            return f"{bps}bit"
        pix = (video_s.get("pix_fmt") or "").strip().lower()
        if pix:
            m = re_search(r"(\d+)(le|be)", pix)
            if m:
                n = int(m.group(1))
                if n > 0:
                    return f"{n}bit"
        prof = (video_s.get("profile") or "").strip()
        if prof:
            m = re_search(r"main\s*(\d+)", prof, IGNORECASE)
            if m:
                return f"{m.group(1)}bit"
        return None

    @staticmethod
    def _probe_to_rename_fields(probe_json: Dict[str, Any]) -> Dict[str, str]:
        """
        从 ffprobe JSON 提取写入 rename_dict 的命名模板字段
        """
        out: Dict[str, str] = {}
        streams = probe_json.get("streams")
        if not isinstance(streams, list):
            return out
        video_s, audio_s = RenameDictUtils._pick_video_audio_streams(streams)
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
            vf = RenameDictUtils._height_to_video_format(h_int, w_int)
            if vf:
                out["videoFormat"] = vf
            vc = RenameDictUtils._map_video_codec(video_s.get("codec_name"))
            if vc:
                out["videoCodec"] = vc
            vb = RenameDictUtils._extract_video_bit_depth(video_s)
            if vb:
                out["videoBit"] = vb
            fps = RenameDictUtils._parse_frame_rate(
                video_s.get("avg_frame_rate")
            ) or RenameDictUtils._parse_frame_rate(video_s.get("r_frame_rate"))
            if fps:
                out["fps"] = fps
            eff = RenameDictUtils._infer_effect_from_video_stream(video_s)
            if eff:
                out["effect"] = eff
        if audio_s:
            atmos = RenameDictUtils._audio_stream_has_dolby_atmos_ffprobe(audio_s)
            ac = RenameDictUtils._format_audio_codec_label(
                audio_s.get("codec_name"),
                audio_s.get("channel_layout"),
                audio_s.get("channels"),
                dolby_atmos=atmos,
            )
            if ac:
                out["audioCodec"] = ac
        return out

    @staticmethod
    def _normalize_strm_target(raw: str) -> str:
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

    @staticmethod
    def _resolve_probe_target(source_path: str) -> Tuple[Optional[str], str]:
        """
        普通文件直接返回路径；STRM 读取首条有效行并规范化后作为真实地址
        """
        p = Path(source_path)
        if p.suffix.lower() != ".strm":
            return source_path.strip(), ""
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            return None, f"读取 STRM 失败 {source_path}: {e}"
        for line in text.splitlines():
            line = line.strip()
            if not line or line.lstrip().startswith("#"):
                continue
            normalized = RenameDictUtils._normalize_strm_target(line)
            if normalized:
                return normalized, ""
        return None, f"STRM 内容为空 {source_path}"

    @staticmethod
    def _run_ffprobe(probe_target: str) -> Tuple[Optional[Dict[str, Any]], str]:
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
                timeout=RenameDictUtils.FFPROBE_TIMEOUT_SEC,
            )
        except TimeoutExpired:
            return (
                None,
                f"ffprobe 超时({RenameDictUtils.FFPROBE_TIMEOUT_SEC}s) target={probe_target}",
            )
        except OSError as e:
            return None, f"无法执行 ffprobe: {e}"
        if proc.returncode != 0:
            err = (proc.stderr or "").strip() or proc.stdout
            return (
                None,
                f"ffprobe 失败 rc={proc.returncode} target={probe_target} err={err[:500] if err else ''}",
            )
        try:
            return loads(proc.stdout), ""
        except JSONDecodeError as e:
            return None, f"ffprobe JSON 解析失败: {e}"

    @staticmethod
    def ffprobe_get_media_info(
        source_path: Optional[str] = None,
        url: Optional[str] = None,
        strm_resolve_media_info: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        获取媒体信息

        :param source_path: 本地文件或 STRM 路径
        :param url: 无本地路径时直接探测的地址
        :param strm_resolve_media_info: 当 ``source_path`` 为 ``.strm`` 时在 ffprobe 之前调用；
            入参为该 STRM 内解析得到的探测目标字符串（首条有效 URL/路径经规范化后，与即将作为
            ``ffprobe -i`` 输入的字符串相同），不是磁盘上的 ``.strm`` 文件路径；
            若返回非空字典则作为结果直接返回，返回 ``None`` 或空字典 ``{}`` 则继续 ffprobe
        :return: (重命名字段字典, 错误信息)；成功时错误信息为空字符串
        """
        if source_path:
            probe_target, error_message = RenameDictUtils._resolve_probe_target(
                source_path
            )
            if not probe_target:
                return None, error_message
            if (
                strm_resolve_media_info is not None
                and Path(source_path).suffix.lower() == ".strm"
            ):
                resolved = strm_resolve_media_info(probe_target)
                if resolved:
                    return resolved, ""
        else:
            probe_target = url

        probe_json, error_message = RenameDictUtils._run_ffprobe(probe_target)
        if not probe_json:
            return None, error_message

        return RenameDictUtils._probe_to_rename_fields(probe_json), ""

    @staticmethod
    def _emby_numeric_fps_to_str(value: Any) -> Optional[str]:
        """
        将 Emby 的帧率数值格式化为与 _parse_frame_rate 一致的无小数点整数字符串（四舍五入）
        """
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        return str(int(round(v)))

    @staticmethod
    def _infer_effect_from_emby_video_stream(
        video_s: Dict[str, Any],
    ) -> Optional[str]:
        """
        根据 Emby MediaStream 推断与 rename_dict effect 一致的标签

        :param video_s: Type 为 Video 的单路 MediaStream
        :return: 与 RenameDictUtils._infer_effect_from_video_stream 风格一致，无法判断则 None
        """
        vr_raw = (video_s.get("VideoRange") or "").strip()
        vr = vr_raw.lower()

        tokens: List[str] = []
        if "dolby" in vr or "dovi" in vr or "vision" in vr:
            tokens.append("DoVi")
        if "hdr10+" in vr or "hdr10plus" in vr or "hdr 10+" in vr:
            tokens.append("HDR10+")
        elif "hdr10" in vr:
            if "hdr10+" not in vr:
                tokens.append("HDR10")
        elif vr == "hdr":
            tokens.append("HDR10")

        if "hlg" in vr and "HLG" not in tokens:
            tokens.append("HLG")

        if not tokens:
            ct = (video_s.get("ColorTransfer") or "").lower().strip()
            cp = (video_s.get("ColorPrimaries") or "").lower().strip()
            if ct == "smpte2084":
                tokens.append("HDR10")
            elif "arib-std-b67" in ct:
                tokens.append("HLG")

        if not tokens and vr_raw.upper() == "SDR":
            tokens.append("SDR")

        if not tokens:
            ct = (video_s.get("ColorTransfer") or "").lower().strip()
            cp = (video_s.get("ColorPrimaries") or "").lower().strip()
            if ct == "bt709" and (not cp or cp == "bt709"):
                tokens.append("SDR")

        if not tokens:
            return None
        return " ".join(tokens)

    @staticmethod
    def _pick_emby_video_audio_streams(
        streams: List[Dict[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        从 MediaStreams 选取默认视频、音频流（优先 IsDefault，否则同类型首条）
        """
        videos: List[Dict[str, Any]] = []
        audios: List[Dict[str, Any]] = []
        for s in streams:
            if not isinstance(s, dict):
                continue
            st = s.get("Type")
            if st == "Video":
                videos.append(s)
            elif st == "Audio":
                audios.append(s)

        def _pick_default(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not cands:
                return None
            for c in cands:
                if c.get("IsDefault"):
                    return c
            return cands[0]

        return _pick_default(videos), _pick_default(audios)

    @staticmethod
    def _extract_media_streams(payload: Any) -> Optional[List[Dict[str, Any]]]:
        """
        兼容多种 Emby 媒体信息外层结构，取出 MediaStreams 列表
        """
        if payload is None:
            return None
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                msi = item.get("MediaSourceInfo")
                if isinstance(msi, dict):
                    ms = msi.get("MediaStreams")
                    if isinstance(ms, list) and ms:
                        return ms
            return None
        if isinstance(payload, dict):
            ms = payload.get("MediaStreams")
            if isinstance(ms, list) and ms:
                return ms
            msi = payload.get("MediaSourceInfo")
            if isinstance(msi, dict):
                ms = msi.get("MediaStreams")
                if isinstance(ms, list) and ms:
                    return ms
        return None

    @staticmethod
    def emby_mediainfo_to_rename_fields(payload: Any) -> Dict[str, str]:
        """
        从 Emby 媒体信息 JSON 提取写入 rename_dict 的命名模板字段

        输出键与 RenameDictUtils._probe_to_rename_fields 一致：
        videoFormat、videoCodec、videoBit、fps、effect、audioCodec（有则写入）

        :param payload: download_emby_mediainfo_data 单条值，或含 MediaSourceInfo 的 list/dict
        :return: 字符串字典，无法解析时为空 dict
        """
        out: Dict[str, str] = {}
        streams = RenameDictUtils._extract_media_streams(payload)
        if not streams:
            return out
        video_s, audio_s = RenameDictUtils._pick_emby_video_audio_streams(streams)
        if video_s:
            height = video_s.get("Height")
            try:
                h_int = int(height) if height is not None else None
            except (TypeError, ValueError):
                h_int = None
            width = video_s.get("Width")
            try:
                w_int = int(width) if width is not None else None
            except (TypeError, ValueError):
                w_int = None
            vf = RenameDictUtils._height_to_video_format(h_int, w_int)
            if vf:
                out["videoFormat"] = vf
            vc = RenameDictUtils._map_video_codec(video_s.get("Codec"))
            if vc:
                out["videoCodec"] = vc
            vb = video_s.get("BitDepth")
            if vb:
                try:
                    out["videoBit"] = f"{int(vb)}bit"
                except (TypeError, ValueError):
                    pass
            fps = RenameDictUtils._emby_numeric_fps_to_str(
                video_s.get("AverageFrameRate")
            ) or RenameDictUtils._emby_numeric_fps_to_str(video_s.get("RealFrameRate"))
            if fps:
                out["fps"] = fps
            eff = RenameDictUtils._infer_effect_from_emby_video_stream(video_s)
            if eff:
                out["effect"] = eff
        if audio_s:
            atmos = RenameDictUtils._audio_stream_has_dolby_atmos_emby(audio_s)
            ac = RenameDictUtils._format_audio_codec_label(
                audio_s.get("Codec"),
                audio_s.get("ChannelLayout"),
                audio_s.get("Channels"),
                dolby_atmos=atmos,
            )
            if ac:
                out["audioCodec"] = ac
        return out
