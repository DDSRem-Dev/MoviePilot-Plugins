import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock


class TestV3ScrapeIdentity(TestCase):
    """
    使用宿主身份规则、事件契约和文件模型验证刮削目录选择
    """

    def setUp(self) -> None:
        """
        隔离识别网络和事件线程，保留真实 V3 身份与载荷校验
        """
        root = Path(__file__).resolve().parents[1]
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        if not (host / "app/sdk/media.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        prefix = "_p115_scrape_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith("app.")
        }
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if name == "app" or name.startswith(("app.", prefix)):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)

        def module(name: str, **attributes: Any) -> ModuleType:
            result = ModuleType(name)
            result.__dict__.update(attributes)
            sys.modules[name] = result
            return result

        for name in (
            "app", "app.schemas", "app.sdk", "app.chain", "app.domain", "app.foundation"
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        module(prefix, __path__=[str(root)])
        module(f"{prefix}.core", __path__=[str(root / "core")])
        self.types = importlib.import_module("app.schemas.types")
        self.context = importlib.import_module("app.domain.context")
        self.snapshots = importlib.import_module("app.schemas.context")
        self.meta_path = importlib.import_module("app.domain.metainfo").MetaInfoPath
        meta_base = importlib.import_module("app.domain.meta.metabase").MetaBase
        identity = importlib.import_module("app.schemas.media")
        file_model = importlib.import_module("app.schemas.file").FileItem
        sys.modules["app.schemas"].FileItem = file_model
        self.contract = importlib.import_module(
            "app.schemas.event"
        ).MetadataScrapeContractData
        self.events = MagicMock()
        self.chain = MagicMock()
        self.logger = MagicMock()
        self.settings = SimpleNamespace(TV_RENAME_FORMAT="{{title}}/Season {{season}}/{{title}}")
        module("app.sdk.events", eventmanager=self.events)
        module(
            "app.sdk.media",
            MetaInfoPath=self.meta_path,
            MetaBase=meta_base,
            MediaInfo=self.context.MediaInfo,
            resolve_media_identity=identity.resolve_media_identity,
        )
        module("app.sdk.config", settings=self.settings)
        module("app.sdk.logging", logger=self.logger)
        module("app.chain.media", MediaChain=MagicMock(return_value=self.chain))
        self.scrape = importlib.import_module(f"{prefix}.core.scrape")
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.library = Path(temporary.name)
        self.series = self.library / "Example"
        self.season = self.series / "Season 01"
        self.season.mkdir(parents=True)
        self.file = self.season / "Example.S01E01.strm"
        self.file.write_text("https://example.invalid/video", encoding="utf-8")

    def _media(self, **values: Any) -> Any:
        fields = {
            "media_source": self.types.MediaSource.Bangumi,
            "media_id": "42",
            "type": self.types.MediaType.TV.value,
            "title": "Example",
        }
        fields.update(values)
        fields["type"] = self.types.MediaType(fields["type"])
        return self.context.MediaInfo(**fields)

    def _payload(self) -> Any:
        self.events.send_event.assert_called_once()
        event_type, payload = self.events.send_event.call_args.args
        self.assertEqual(event_type, self.types.EventType.MetadataScrape)
        return self.contract.model_validate(payload)

    def test_native_identity_without_imdb_selects_series_root(self) -> None:
        """
        Bangumi 文件、季目录和剧目录的成对身份一致时刮削剧目录
        """
        media = self._media()
        self.chain.recognize_by_meta.side_effect = [media, media, media]
        self.scrape.media_scrape_metadata(self.file)
        payload = self._payload()
        self.assertEqual(payload.fileitem.path, str(self.series))
        self.assertEqual(payload.fileitem.type, "dir")
        self.assertEqual(payload.mediainfo.media_source, self.types.MediaSource.Bangumi)
        self.assertEqual(payload.mediainfo.media_id, "42")

    def test_parent_mismatch_never_expands_to_directory(self) -> None:
        """
        同编号跨来源、同 IMDb 跨原生身份和同编号跨类型均不扩大刮削范围
        """
        media = self._media(imdb_id="tt123")
        for parent in (
            self._media(media_source=self.types.MediaSource.TMDB, imdb_id="tt123"),
            self._media(media_id="43", imdb_id="tt123"),
            self._media(type=self.types.MediaType.MOVIE.value, imdb_id="tt123"),
            self._media(media_source=None, media_id=None, imdb_id="tt123"),
        ):
            with self.subTest(parent=parent):
                self.events.reset_mock()
                self.chain.recognize_by_meta.side_effect = [media, parent]
                self.scrape.media_scrape_metadata(self.file)
                payload = self._payload()
                self.assertEqual(payload.fileitem.path, str(self.file))
                self.assertEqual(payload.fileitem.type, "file")

    def test_missing_imdb_does_not_make_different_titles_equal(self) -> None:
        """
        两边 IMDb 均缺失时仍按原生 ID 拒绝错误父目录
        """
        self.chain.recognize_by_meta.side_effect = [self._media(), self._media(media_id="99")]
        self.scrape.media_scrape_metadata(self.file)
        self.assertEqual(self._payload().fileitem.path, str(self.file))

    def test_grandparent_mismatch_keeps_matching_season_directory(self) -> None:
        """
        季目录身份相同但上级身份不同则保持季目录范围
        """
        media = self._media()
        self.chain.recognize_by_meta.side_effect = [media, media, self._media(media_id="99")]
        self.scrape.media_scrape_metadata(self.file)
        self.assertEqual(self._payload().fileitem.path, str(self.season))

    def test_recognized_movie_uses_matching_parent_only(self) -> None:
        """
        电影身份匹配后使用直接父目录，不再识别更高目录
        """
        media = self._media(type=self.types.MediaType.MOVIE.value)
        self.chain.recognize_by_meta.side_effect = [media, media]
        self.scrape.media_scrape_metadata(self.file)
        self.assertEqual(self._payload().fileitem.path, str(self.season))
        self.assertEqual(self.chain.recognize_by_meta.call_count, 2)

    def test_missing_recognition_does_not_emit_scrape(self) -> None:
        """
        无识别结果时不提交刮削事件
        """
        self.chain.recognize_by_meta.return_value = None
        self.scrape.media_scrape_metadata(self.file)
        self.events.send_event.assert_not_called()

    def test_supplied_movie_context_preserves_parent_and_metadata(self) -> None:
        """
        整理事件已提供电影身份和元数据时直接传递给宿主
        """
        media = self._media(type=self.types.MediaType.MOVIE.value)
        meta = self.meta_path(self.file)
        self.scrape.media_scrape_metadata(self.file, mediainfo=media, meta=meta)
        payload = self._payload()
        self.assertEqual(payload.fileitem.path, self.season.as_posix())
        self.assertEqual(payload.meta.begin_episode, 1)
        self.chain.recognize_by_meta.assert_not_called()

    def test_supplied_tv_context_retains_existing_template_depth(self) -> None:
        """
        已识别电视剧继续按现有命名模板层数选择目录或文件
        """
        for template, expected, kind in (
            ("{{title}}/Season {{season}}/{{title}}", self.series, "dir"),
            ("Season {{season}}/{{title}}", self.season, "dir"),
            ("{{title}}", self.file, "file"),
        ):
            with self.subTest(template=template):
                self.events.reset_mock()
                self.settings.TV_RENAME_FORMAT = template
                self.scrape.media_scrape_metadata(self.file, mediainfo=self._media())
                payload = self._payload()
                self.assertEqual(payload.fileitem.path, expected.as_posix())
                self.assertEqual(payload.fileitem.type, kind)
        self.chain.recognize_by_meta.assert_not_called()

    def test_invalid_or_missing_identity_never_matches(self) -> None:
        """
        原生身份不完整、零 ID 和缺失媒体类型均不能触发父目录匹配
        """
        for source, identity, kind in (
            (None, "42", self.types.MediaType.TV),
            (self.types.MediaSource.Bangumi, "0", self.types.MediaType.TV),
            (self.types.MediaSource.Bangumi, " ", self.types.MediaType.TV),
            (self.types.MediaSource.Bangumi, "42", None),
        ):
            media = SimpleNamespace(media_source=source, media_id=identity, type=kind)
            with self.subTest(source=source, identity=identity, kind=kind):
                self.assertFalse(self.scrape._same_media_identity(media, media))
        self.assertFalse(self.scrape._same_media_identity(None, None))

    def test_enum_and_snapshot_media_types_share_identity(self) -> None:
        """
        运行时枚举与事件快照字符串按宿主规则解析为同一媒体类型
        """
        runtime = SimpleNamespace(
            media_source="bangumi", media_id=" 42 ", type=self.types.MediaType.TV
        )
        snapshot = self.snapshots.MediaInfo(
            media_source="bangumi", media_id="42", type=self.types.MediaType.TV.value
        )
        self.assertTrue(self.scrape._same_media_identity(runtime, snapshot))
