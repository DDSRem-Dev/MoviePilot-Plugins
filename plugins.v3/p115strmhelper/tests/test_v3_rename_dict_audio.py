import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from typing import Any, Dict

_FFPROBE_VIDEO: Dict[str, Any] = {
    "codec_type": "video",
    "codec_name": "hevc",
    "width": 3840,
    "height": 2160,
    "pix_fmt": "yuv420p10le",
    "avg_frame_rate": "24000/1001",
    "color_transfer": "smpte2084",
    "color_primaries": "bt2020",
    "disposition": {"default": 1},
}

_EMBY_VIDEO: Dict[str, Any] = {
    "Type": "Video",
    "Codec": "hevc",
    "Width": 3840,
    "Height": 2160,
    "BitDepth": 10,
    "AverageFrameRate": 23.976,
    "VideoRange": "HDR10",
    "IsDefault": True,
}


def _ensure_orjson() -> None:
    """
    宿主依赖 orjson 缺失时注入等价桩，使工具类可在纯标准库环境加载
    """
    try:
        import orjson  # noqa: F401
    except ImportError:
        stub = ModuleType("orjson")
        stub.loads = json.loads
        stub.JSONDecodeError = json.JSONDecodeError
        sys.modules["orjson"] = stub


def _load_rename_dict() -> ModuleType:
    _ensure_orjson()
    path = Path(__file__).resolve().parents[1] / "utils/rename_dict.py"
    spec = spec_from_file_location("rename_dict_under_test", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ffprobe_audio(**kwargs: Any) -> Dict[str, Any]:
    stream: Dict[str, Any] = {
        "codec_type": "audio",
        "index": 1,
        "disposition": {"default": 1},
    }
    stream.update(kwargs)
    return stream


class TestV3RenameDictAudio(TestCase):
    """
    验证音频命名字段保留 DTS 家族的具体档位
    """

    def setUp(self) -> None:
        """
        加载真实重命名字典工具类
        """
        self.utils = _load_rename_dict().RenameDictUtils

    def test_ffprobe_keeps_dts_hd_ma_profile(self) -> None:
        """
        ffprobe 只把档位写在 profile 与 codec_long_name 中时仍需还原 DTS-HD MA
        """
        audio = _ffprobe_audio(
            codec_name="dts",
            codec_long_name="DTS (DTS-HD MA)",
            profile="DTS-HD MA",
            codec_tag_string="[0][0][0][0]",
            channels=6,
            channel_layout="5.1(side)",
            tags={"language": "eng", "title": "DTS-HD MA 5.1"},
        )
        fields = self.utils._probe_to_rename_fields(
            {"streams": [_FFPROBE_VIDEO, audio]}
        )
        self.assertEqual(fields["audioCodec"], "DTS-HD MA 5.1")
        self.assertEqual(fields["videoCodec"], "H265")
        self.assertEqual(fields["videoBit"], "10bit")
        self.assertEqual(fields["fps"], "24")
        self.assertEqual(fields["effect"], "HDR10")

    def test_emby_keeps_dts_hd_ma_profile(self) -> None:
        """
        Emby 仅通过 Profile 与 Title 暴露档位时仍需还原 DTS-HD MA
        """
        audio = {
            "Type": "Audio",
            "Codec": "dts",
            "Profile": "DTS-HD MA",
            "Title": "DTS-HD MA 5.1",
            "DisplayTitle": "DTS-HD MA 5.1 (DTS-HD MA)",
            "ChannelLayout": "5.1",
            "Channels": 6,
            "IsDefault": True,
        }
        fields = self.utils.emby_mediainfo_to_rename_fields(
            {"MediaStreams": [_EMBY_VIDEO, audio]}
        )
        self.assertEqual(fields["audioCodec"], "DTS-HD MA 5.1")
        self.assertEqual(fields["videoCodec"], "H265")

    def test_plain_dts_stays_plain(self) -> None:
        """
        普通 DTS 音轨在 ffprobe 固定 codec_long_name 下不被误标为 DTS-HD MA
        """
        audio = _ffprobe_audio(
            codec_name="dts",
            codec_long_name="DTS (DTS-HD MA)",
            profile="DTS",
            channels=6,
            channel_layout="5.1(side)",
            tags={},
        )
        fields = self.utils._probe_to_rename_fields(
            {"streams": [_FFPROBE_VIDEO, audio]}
        )
        self.assertEqual(fields["audioCodec"], "DTS 5.1")

    def test_title_only_carries_profile(self) -> None:
        """
        profile 缺失时可由音轨标题还原档位
        """
        audio = {
            "Type": "Audio",
            "Codec": "dts",
            "Title": "DTS-HD MA 7.1",
            "ChannelLayout": "7.1",
            "Channels": 8,
            "IsDefault": True,
        }
        fields = self.utils.emby_mediainfo_to_rename_fields(
            {"MediaStreams": [_EMBY_VIDEO, audio]}
        )
        self.assertEqual(fields["audioCodec"], "DTS-HD MA 7.1")

    def test_dts_profile_variants(self) -> None:
        """
        DTS-HD HR、DTS:X、DTS-ES、DTS 96-24、DTS Express 不受固定 codec_long_name 干扰
        """
        cases = [
            (
                {"profile": "DTS-HD HRA", "channels": 8, "channel_layout": "7.1"},
                "DTS-HD HR 7.1",
            ),
            (
                {"profile": "DTS:X", "channels": 8, "channel_layout": "7.1"},
                "DTS-X 7.1",
            ),
            (
                {"profile": "DTS-ES", "channels": 6, "channel_layout": "5.1(side)"},
                "DTS-ES 5.1",
            ),
            (
                {"profile": "DTS 96/24", "channels": 6, "channel_layout": "5.1(side)"},
                "DTS 96-24 5.1",
            ),
            (
                {
                    "profile": "DTS Express",
                    "channels": 2,
                    "channel_layout": "stereo",
                },
                "DTS Express 2.0",
            ),
        ]
        for audio_extra, expected in cases:
            audio = _ffprobe_audio(
                codec_name="dts",
                codec_long_name="DTS (DTS-HD MA)",
                tags={},
                **audio_extra,
            )
            fields = self.utils._probe_to_rename_fields(
                {"streams": [_FFPROBE_VIDEO, audio]}
            )
            self.assertEqual(fields["audioCodec"], expected)

    def test_label_has_no_path_separator(self) -> None:
        """
        96/24 这类档位不能把路径分隔符带进文件名
        """
        profiles = [
            "DTS",
            "DTS-HD HRA",
            "DTS-HD MA",
            "DTS:X",
            "DTS 96/24",
            "DTS Express",
        ]
        for profile in profiles:
            label = self.utils._format_audio_codec_label(
                "dts", "5.1(side)", 6, audio_s={"profile": profile}
            )
            self.assertNotIn("/", label)
            self.assertNotIn("\\", label)

    def test_mapping_without_stream_keeps_compat(self) -> None:
        """
        未传入音轨字典时保持原有映射行为
        """
        self.assertEqual(self.utils._map_audio_codec("dts"), "DTS")
        self.assertEqual(self.utils._map_audio_codec("eac3"), "EAC3")
        self.assertEqual(self.utils._map_audio_codec("truehd"), "Dolby TrueHD")
        self.assertIsNone(self.utils._map_audio_codec(None))
