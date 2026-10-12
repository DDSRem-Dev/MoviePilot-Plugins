import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method


class TestV3TransferStrm(TestCase):
    """
    使用真实 V3 整理契约、持久事件转换和媒体解析验证 STRM 监听器
    """

    def setUp(self) -> None:
        """
        保留宿主领域对象与事件校验，仅隔离网络、数据库和后台服务
        """
        root = Path(__file__).resolve().parents[1]
        host = Path(os.environ.get("MOVIEPILOT_SOURCE", root.parents[2] / "MoviePilot"))
        if not (host / "app/sdk/events.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        prefix = "_p115_transfer_strm_test"
        roots = ("app", "p115client", prefix)
        originals = {
            name: value
            for name, value in sys.modules.items()
            if any(name == key or name.startswith(key + ".") for key in roots)
        }
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if any(name == key or name.startswith(key + ".") for key in roots):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)

        def module(name: str, **attributes: Any) -> ModuleType:
            value = ModuleType(name)
            value.__dict__.update(attributes)
            sys.modules[name] = value
            return value

        for name in (
            "app",
            "app.schemas",
            "app.sdk",
            "app.chain",
            "app.domain",
            "app.foundation",
            "app.application",
            "app.application.chain",
            "app.application.transfer",
            "app.runtime",
            "app.runtime.event",
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        for suffix in ("", ".core", ".helper", ".helper.strm", ".utils", ".db_manager"):
            location = root.joinpath(*suffix.strip(".").split(".")) if suffix else root
            module(prefix + suffix, __path__=[str(location)])
        module("p115client", __path__=[], P115Client=object)
        module("p115client.tool", __path__=[])
        module("p115client.tool.attr", get_attr=MagicMock())

        self.types = importlib.import_module("app.schemas.types")
        self.file_type = importlib.import_module("app.schemas.file").FileItem
        self.transfer_type = importlib.import_module(
            "app.schemas.transfer"
        ).TransferInfo
        sys.modules["app.schemas"].FileItem = self.file_type
        sys.modules["app.schemas"].TransferInfo = self.transfer_type
        self.context = importlib.import_module("app.domain.context")
        meta_path = importlib.import_module("app.domain.metainfo").MetaInfoPath
        meta_base = importlib.import_module("app.domain.meta.metabase").MetaBase
        module(
            "app.sdk.media",
            MediaInfo=self.context.MediaInfo,
            MetaBase=meta_base,
            MetaInfoPath=meta_path,
        )
        snapshot = importlib.import_module(
            "app.runtime.event.snapshot"
        ).snapshot_event_data
        module(
            "app.runtime.events",
            Event=object,
            EventManager=object,
            eventmanager=MagicMock(),
        )
        self.events = importlib.import_module("app.sdk.events")
        self.assertIs(self.events.snapshot_event_data, snapshot)
        self.durable = importlib.import_module("app.application.chain.events")
        self.outbox = _method(
            host / "app/startup/composition/outbox.py",
            "build_outbox_handlers",
            {
                "EventManager": lambda: SimpleNamespace(
                    send_event_strict=self._dispatch
                ),
                "EventType": self.types.EventType,
                "durable_event_topic": lambda event: event.value,
                "restore_transfer_result": self.durable.restore_transfer_result,
                "DOWNLOAD_NOTIFICATION_TOPIC": "download.notification",
                "DOWNLOAD_MODULE_TOPIC": "download.module",
                "DOWNLOAD_SUBTITLE_TOPIC": "download.subtitle",
                "validate_durable_event_handlers": lambda handlers: None,
            },
        )()
        self.logger = MagicMock()
        module("app.sdk.logging", logger=self.logger)
        module("app.sdk.utilities", SystemUtils=MagicMock())
        module(
            "app.sdk.config",
            settings=SimpleNamespace(
                RMT_MEDIAEXT=[".mkv", ".mp4", ".iso"],
                RMT_SUBEXT=[".srt", ".ass"],
                RMT_AUDIOEXT=[".flac"],
            ),
        )
        self.storage = MagicMock()
        self.storage.is_bluray_folder.return_value = False
        module("app.chain.storage", StorageChain=MagicMock(return_value=self.storage))
        self.directory = MagicMock()
        self.directory.get_dirs.return_value = []
        module(
            "app.application.directory",
            DirectoryHelper=MagicMock(return_value=self.directory),
        )
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.config = SimpleNamespace(
            transfer_monitor_paths=f"{self.library}#/cloud/Example/Season 01",
            transfer_monitor_clouddrive2_enabled=False,
            transfer_monitor_remove_stale_strm=False,
            transfer_monitor_emby_mediainfo_enabled=False,
            native_emby_mediainfo_enabled=False,
            transfer_monitor_scrape_metadata_enabled=True,
        )
        self.config.get_config = lambda key: getattr(self.config, key, False)
        module(f"{prefix}.core.config", configer=self.config)
        self.scrape = MagicMock()
        module(f"{prefix}.core.scrape", media_scrape_metadata=self.scrape)
        self.database = MagicMock()
        module(
            f"{prefix}.db_manager.oper",
            FileDbHelper=MagicMock(return_value=self.database),
        )
        module(f"{prefix}.helper.mediainfo_download", MediaInfoDownloader=object)
        module(
            f"{prefix}.helper.mediaserver",
            MediaServerRefresh=MagicMock(),
            emby_mediainfo_queue=MagicMock(),
        )
        module(f"{prefix}.utils.sentry", sentry_manager=MagicMock())
        self.filename = MagicMock(
            side_effect=lambda path: path.with_suffix(".strm").name
        )
        self.url = MagicMock()
        self.url.get_strm_url.return_value = "https://example.invalid/video"
        module(
            f"{prefix}.utils.strm",
            StrmUrlGetter=MagicMock(return_value=self.url),
            StrmGenerater=SimpleNamespace(get_strm_filename=self.filename),
        )
        self.module = importlib.import_module(f"{prefix}.helper.strm.transfer")
        self.helper = self.module.TransferStrmHelper()
        self.downloader = MagicMock()
        self.downloader.get_download_url.return_value = (
            "https://example.invalid/subtitle"
        )
        self.downloader.save_mediainfo_file.return_value = True
        self.client = MagicMock()
        self.media = self.context.MediaInfo(
            media_source=self.types.MediaSource.Bangumi,
            media_id="42",
            type=self.types.MediaType.TV,
            title="Example",
            library_category="动画",
            bangumi_info={"id": 42, "name": "Example"},
        )
        self.meta = meta_path(Path("Example.S01E01.mkv"))

    def _item(self, name: str = "Example.S01E01.mkv") -> Dict[str, Any]:
        target = self.file_type(
            storage="u115",
            type="file",
            name=name,
            path=f"/cloud/Example/Season 01/{name}",
            pickcode="a" * 17,
            fileid="101",
        )
        return {
            "transferinfo": self.transfer_type(
                target_item=target,
                target_diritem=self.file_type(
                    storage="u115", type="dir", path="/cloud/Example/Season 01"
                ),
                transfer_type="copy",
            ),
            "meta": self.meta,
            "mediainfo": self.media,
            "transfer_history_id": 123,
            "idempotency_key": "transfer.result:task:1:succeeded:v1",
        }

    def _run(self, item: Dict[str, Any], event_type: Any = None) -> None:
        self.helper.do_generate(
            client=self.client,
            item=item,
            event_type=event_type or self.types.EventType.TransferComplete,
            mediainfodownloader=self.downloader,
        )

    def _dispatch(self, event_type: Any, payload: Dict[str, Any]) -> None:
        self.assertIsInstance(payload["transferinfo"], self.transfer_type)
        self.assertIsInstance(payload["mediainfo"], self.context.MediaInfo)
        self._run(payload, event_type)

    def test_host_outbox_restores_completion_payloads_and_propagates_failure(
        self,
    ) -> None:
        """
        真实 outbox 完成事件 handler 先恢复领域对象，再传播插件执行失败
        """
        for event, filename in (
            (self.types.EventType.TransferComplete, "Example.S01E01.mkv"),
            (self.types.EventType.SubtitleTransferComplete, "Example.S01E01.srt"),
            (self.types.EventType.AudioTransferComplete, "Example.S01E01.flac"),
        ):
            message = SimpleNamespace(
                payload=self.durable.snapshot_transfer_result(self._item(filename))
            )
            handler = self.outbox[event.value]
            with self.subTest(event=event):
                handler(message)
                with (
                    patch.object(
                        self.helper, "generate_strm_files", return_value=(False, None)
                    ),
                    patch.object(
                        self.downloader, "save_mediainfo_file", return_value=False
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    handler(message)

    def test_host_runtime_payloads_keep_native_identity_and_directory(
        self,
    ) -> None:
        """
        实时及宿主已恢复载荷保留原目录映射、原生身份和领域对象
        """
        original = self._item()
        frozen = self.durable.snapshot_transfer_result(original)
        replayed = self.durable.restore_transfer_result(frozen)
        self.assertIsNone(frozen["mediainfo"]["bangumi_info"])
        for payload in (original, replayed):
            with self.subTest(payload_type=type(payload["mediainfo"]).__name__):
                self.scrape.reset_mock()
                self._run(payload)
                target = self.library / "Example.S01E01.strm"
                self.assertEqual(target.read_text(), "https://example.invalid/video")
                self.scrape.assert_called_once()
                args = self.scrape.call_args.kwargs
                if payload is original:
                    self.assertIs(args["mediainfo"], original["mediainfo"])
                    self.assertIs(args["meta"], original["meta"])
                self.assertIsInstance(args["mediainfo"], self.context.MediaInfo)
                self.assertEqual(
                    args["mediainfo"].media_source, self.types.MediaSource.Bangumi
                )
                self.assertEqual(args["mediainfo"].media_id, "42")
                self.assertEqual(args["mediainfo"].library_category, "动画")
                if payload is original:
                    self.assertEqual(args["mediainfo"].bangumi_info["id"], 42)
                else:
                    self.assertIsNone(args["mediainfo"].bangumi_info)
                self.assertEqual(args["meta"].begin_episode, 1)
                self.assertEqual(args["meta"].begin_season, 1)
        self.assertEqual(original["mediainfo"].media_id, "42")
        self.assertEqual(list(self.library.glob("*.strm")), [target])

    def test_missing_target_results_keep_original_skip_behavior(
        self,
    ) -> None:
        """
        缺少目标文件或目录时沿用原跳过分支
        """
        cases = [{}]
        for field, value in (
            ("target_item", None),
            ("target_diritem", None),
        ):
            item = self._item()
            setattr(item["transferinfo"], field, value)
            cases.append(item)
        for item in cases:
            for event in (
                self.types.EventType.TransferComplete,
                self.types.EventType.SubtitleTransferComplete,
                self.types.EventType.AudioTransferComplete,
            ):
                with (
                    self.subTest(item=item, event=event),
                    patch.object(self.module, "FileDbHelper") as factory,
                ):
                    self._run(item, event)
                    factory.assert_not_called()
        self.assertFalse(self.library.exists())
        self.downloader.save_mediainfo_file.assert_not_called()
        self.storage.is_bluray_folder.assert_not_called()

    def test_nonmatching_cloud_mapping_does_not_write(self) -> None:
        """
        未命中映射的文件不落盘
        """
        self.config.transfer_monitor_paths = f"{self.library}#/other"
        self._run(self._item())
        self.assertFalse(self.library.exists())
        self.database.upsert_batch.assert_not_called()

    def test_write_failure_propagates_before_scrape(self) -> None:
        """
        文件写入失败向严格事件投递传播异常并阻止刮削
        """
        with patch("builtins.open", side_effect=OSError("磁盘错误")):
            with self.assertRaisesRegex(RuntimeError, "STRM 文件写入失败"):
                self._run(self._item())
        self.scrape.assert_not_called()
        self.assertEqual(list(self.library.iterdir()), [])

    def test_audio_and_subtitle_events_download_without_strm(self) -> None:
        """
        专用音轨字幕事件及普通完成事件中的音轨字幕均走下载分支
        """
        for event, name in (
            (self.types.EventType.SubtitleTransferComplete, "episode.ass"),
            (self.types.EventType.AudioTransferComplete, "episode.flac"),
            (self.types.EventType.TransferComplete, "episode.srt"),
            (self.types.EventType.TransferComplete, "episode.flac"),
        ):
            self.downloader.reset_mock()
            with self.subTest(event=event, name=name):
                self._run(self._item(name), event)
                self.downloader.save_mediainfo_file.assert_called_once_with(
                    file_path=self.library / name,
                    file_name=name,
                    download_url="https://example.invalid/subtitle",
                )
        self.scrape.assert_not_called()
        self.url.get_strm_url.assert_not_called()

    def test_download_failures_propagate_for_durable_retry(self) -> None:
        """
        下载链接缺失或保存失败均反馈给宿主重试，不静默确认事件
        """
        for url, saved in ((None, True), ("https://example.invalid/subtitle", False)):
            self.downloader.get_download_url.return_value = url
            self.downloader.save_mediainfo_file.return_value = saved
            with self.subTest(url=url, saved=saved), self.assertRaises(RuntimeError):
                self._run(
                    self._item("episode.ass"),
                    self.types.EventType.SubtitleTransferComplete,
                )

    def test_nonmedia_extension_keeps_original_skip_behavior(self) -> None:
        """
        非媒体文件沿用原跳过分支，不生成 STRM
        """
        self._run(self._item("episode.nfo"))
        self.url.get_strm_url.assert_not_called()
        self.downloader.save_mediainfo_file.assert_not_called()
        self.assertFalse(self.library.exists())
