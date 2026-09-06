"""PlexToolbox ffprobe 数据源与无 Emby 回退逻辑的纯 Python 自测。"""

from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from ffprobe_source import (  # noqa: E402
    FfprobeSource,
    _normalize_ffprobe,
    map_path,
    parse_path_map,
    read_strm_url,
)


class FfprobeSourceTest(unittest.TestCase):
    """覆盖 STRM 读取、路径映射和 ffprobe JSON 归一化。"""

    def test_path_mapping_prefers_longest_prefix(self) -> None:
        mappings = parse_path_map(
            "/Volumes/data=/media\n/Volumes/data/mp=/special; /invalid=relative"
        )
        self.assertEqual(
            map_path("/Volumes/data/mp/movie.strm", mappings),
            "/special/movie.strm",
        )
        self.assertEqual(map_path("/Volumes/other/movie.strm", mappings), "/Volumes/other/movie.strm")

    def test_read_strm_url_skips_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            strm = Path(temp_dir) / "movie.strm"
            strm.write_text("# generated\n\nhttps://example.invalid/movie.mkv?pickcode=redacted\n", encoding="utf-8")
            self.assertEqual(
                read_strm_url(str(strm)),
                "https://example.invalid/movie.mkv?pickcode=redacted",
            )

    def test_normalize_ffprobe_output(self) -> None:
        result = _normalize_ffprobe(
            {
                "format": {
                    "format_name": "matroska,webm",
                    "duration": "1420.125",
                    "size": "2147483648",
                    "bit_rate": "12000000",
                },
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_name": "hevc",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "24000/1001",
                        "pix_fmt": "yuv420p10le",
                        "bit_rate": "10000000",
                        "tags": {"LANGUAGE": "und"},
                    },
                    {
                        "index": 1,
                        "codec_type": "audio",
                        "codec_name": "eac3",
                        "channels": 6,
                        "sample_rate": "48000",
                        "bit_rate": "640000",
                        "tags": {"language": "jpn"},
                    },
                    {
                        "index": 2,
                        "codec_type": "subtitle",
                        "codec_name": "subrip",
                        "tags": {"language": "chi"},
                    },
                    {"index": 3, "codec_type": "data", "codec_name": "bin_data"},
                ],
            }
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["container"], "mkv")
        self.assertEqual(result["duration"], 1420125)
        self.assertEqual(result["bitrate"], 12000)
        self.assertEqual(result["video_codec"], "hevc")
        self.assertEqual(result["audio_codec"], "eac3")
        self.assertEqual(result["audio_channels"], 6)
        self.assertEqual(len(result["streams"]), 3)
        self.assertEqual(result["streams"][0]["bit_depth"], 10)
        self.assertEqual(result["streams"][0]["frame_rate"], 23.976)
        self.assertEqual(result["streams"][2]["codec"], "srt")

    def test_source_reads_mapped_strm_and_probes_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plex_root = Path(temp_dir) / "plex"
            mp_root = Path(temp_dir) / "mp"
            mp_root.mkdir()
            strm = mp_root / "movie.strm"
            strm.write_text("https://example.invalid/movie.mkv\n", encoding="utf-8")
            source = FfprobeSource(f"{plex_root}={mp_root}", timeout=7)
            expected = {"source": "ffprobe", "streams": [{"stream_type": 1, "codec": "hevc"}]}
            with patch("ffprobe_source.ffprobe_url", return_value=expected) as probe:
                self.assertEqual(source.find_streams_by_name(f"{plex_root}/movie.strm"), expected)
                probe.assert_called_once_with("https://example.invalid/movie.mkv", timeout=7.0)


class FfprobeFallbackTest(unittest.TestCase):
    """验证关闭 Emby 后 MediaInfoCompleter 仍能走 ffprobe。"""

    @classmethod
    def setUpClass(cls) -> None:
        # mediainfo.py 使用 MoviePilot 的 logger；测试时提供最小模块桩，
        # 不需要启动 MoviePilot 或连接 Plex/helper。
        app = types.ModuleType("app")
        app.__path__ = []
        sdk = types.ModuleType("app.sdk")
        sdk.__path__ = []
        logging_module = types.ModuleType("app.sdk.logging")
        import logging

        logging_module.logger = logging.getLogger("plextoolbox-test")
        sys.modules.setdefault("app", app)
        sys.modules.setdefault("app.sdk", sdk)
        sys.modules.setdefault("app.sdk.logging", logging_module)

        # 仅为导入 Plex/Emby/helper 客户端提供最小 httpx 桩；本测试不发网络请求。
        if "httpx" not in sys.modules:
            httpx = types.ModuleType("httpx")

            class ClientStub:
                pass

            httpx.Client = ClientStub
            sys.modules["httpx"] = httpx

        package = types.ModuleType("plextoolbox")
        package.__path__ = [str(PLUGIN_DIR)]
        sys.modules.setdefault("plextoolbox", package)
        cls.completer_module = importlib.import_module("plextoolbox.mediainfo")

    def test_no_emby_uses_ffprobe(self) -> None:
        module = self.completer_module

        class PlexStub:
            def item_label(self, rating_key: str) -> str:
                return "测试电影"

            def collect_window_parts_by_rating_key(self, rating_key: str, **kwargs):
                return [{"part_id": 12, "file": "/media/test.strm", "label": "测试电影"}]

        class HelperStub:
            def write_batch(self, items, force=False):
                return {
                    "ok": len(items),
                    "results": [{"part_id": 12, "success": True}],
                }

        class ProbeStub:
            def find_streams_by_name(self, file_path: str):
                return {"source": "ffprobe", "streams": [{"stream_type": 1, "codec": "hevc"}]}

        completer = module.MediaInfoCompleter(
            plex=PlexStub(),
            helper=HelperStub(),
            emby=None,
            use_emby=False,
            ffprobe=ProbeStub(),
            use_ffprobe=True,
        )
        summary = completer.run_rating_key("138375")
        self.assertEqual(summary["resolved"], 1)
        self.assertEqual(summary["ffprobe_hits"], 1)
        self.assertEqual(summary["emby_hits"], 0)
        self.assertEqual(summary["written_ok"], 1)


if __name__ == "__main__":
    unittest.main()
