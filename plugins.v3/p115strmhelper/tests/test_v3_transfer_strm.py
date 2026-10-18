import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base

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
        for suffix in (
            "",
            ".core",
            ".helper",
            ".helper.strm",
            ".utils",
            ".db_manager",
            ".db_manager.models",
        ):
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
        self.root = Path(temporary.name).resolve()
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
        self.engine = create_engine(f"sqlite:///{self.root / 'postprocess.db'}")
        self.addCleanup(self.engine.dispose)
        base = declarative_base()
        db_module = sys.modules[prefix + ".db_manager"]
        db_module.P115StrmHelperBase = base
        db_module.ct_db_manager = SimpleNamespace(
            get_database=lambda: SimpleNamespace(session=lambda: Session(self.engine))
        )
        self.remote_files = {}
        self.storage.get_file_item_strict.side_effect = lambda storage, path: (
            self.remote_files.get((storage, path.as_posix()))
        )
        self.module = importlib.import_module(f"{prefix}.helper.strm.transfer")
        base.metadata.create_all(self.engine)
        self.helper = self.module.TransferStrmHelper()
        self.processor = importlib.import_module(
            f"{prefix}.helper.strm.transfer.postprocess"
        )
        self.files = importlib.import_module(f"{prefix}.helper.strm.transfer.files")
        self.downloader = MagicMock()
        self.downloader.get_download_url.return_value = (
            "https://example.invalid/subtitle"
        )

        def save(file_path, file_name, download_url):
            file_path.write_bytes(b"complete subtitle")
            return True

        self.downloader.save_mediainfo_file.side_effect = save
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
        self.remote_files[(target.storage, target.path)] = target
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
            "idempotency_key": f"transfer.result:{name}:1:succeeded:v1",
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
        真实 outbox 恢复领域对象，失败重投续做，成功重投不再次执行
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
                with patch.object(
                    self.helper, "_prepare_file", side_effect=OSError("磁盘错误")
                ):
                    with self.assertRaises(OSError):
                        handler(message)
                handler(message)
                with patch.object(
                    self.helper,
                    "_prepare_file",
                    side_effect=AssertionError("不能重新生成"),
                ):
                    handler(message)

    def test_host_runtime_payloads_keep_native_identity_and_directory(self) -> None:
        """
        冻结后的原生媒体身份和路径用于首次执行，重放不再提交刮削
        """
        original = self._item()
        replayed = self.durable.restore_transfer_result(
            self.durable.snapshot_transfer_result(original)
        )
        self._run(original)
        target = self.library / "Example.S01E01.strm"
        self.assertEqual(target.read_text(), "https://example.invalid/video")
        self.scrape.assert_called_once()
        args = self.scrape.call_args.kwargs
        self.assertEqual(args["mediainfo"].media_source, self.types.MediaSource.Bangumi)
        self.assertEqual(args["mediainfo"].media_id, "42")
        self.assertEqual(args["mediainfo"].library_category, "动画")
        self.assertEqual(args["meta"].begin_episode, 1)
        self.assertEqual(args["meta"].begin_season, 1)
        self._run(replayed)
        self.scrape.assert_called_once()
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
        with patch.object(Path, "write_text", side_effect=OSError("磁盘错误")):
            with self.assertRaisesRegex(OSError, "磁盘错误"):
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
                self.downloader.save_mediainfo_file.assert_called_once()
                self.assertEqual(
                    self.downloader.save_mediainfo_file.call_args.kwargs["file_name"],
                    name,
                )
                self.assertEqual(
                    (self.library / name).read_bytes(), b"complete subtitle"
                )
        self.scrape.assert_not_called()
        self.url.get_strm_url.assert_not_called()

    def test_linked_audio_restores_video_metadata_for_indexing(self) -> None:
        """
        关联音轨保留影视元数据，不向 V3 音乐解析对象的只读属性写入快照
        """
        parser = importlib.import_module("app.domain.metainfo")
        with patch.object(parser, "get_audio_extensions", return_value={".flac"}):
            audio = parser.MetaInfoPath(Path("Example.S01E01.flac"))
            self.assertEqual(type(audio).__name__, "MetaMusic")
            self._run(
                self._item("Example.S01E01.flac"),
                self.types.EventType.AudioTransferComplete,
            )
        self.database.upsert_batch.assert_called_once()
        self.scrape.assert_not_called()
        self.assertEqual(
            (self.library / "Example.S01E01.flac").read_bytes(), b"complete subtitle"
        )

    def test_download_failures_propagate_for_durable_retry(self) -> None:
        """
        下载链接缺失或保存失败均反馈给宿主重试，不静默确认事件
        """
        for url, saved in ((None, True), ("https://example.invalid/subtitle", False)):
            self.downloader.get_download_url.return_value = url
            self.downloader.save_mediainfo_file.side_effect = None
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

    def _latest(self) -> None:
        self.directory.get_dirs.return_value = [
            SimpleNamespace(
                library_storage="u115", library_path="/cloud", overwrite_mode="latest"
            )
        ]

    def _remove_cloud(self, item: Dict[str, Any]) -> None:
        target = item["transferinfo"].target_item
        self.remote_files.pop((target.storage, target.path), None)

    def test_a_b_a_replay_preserves_new_version_after_restart(self) -> None:
        """
        A 成功、B 替换后重启监听器重放 A，不复活旧文件或删除 B
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self._run(old)
        old_path = self.library / "Example.S01E01.1080p.strm"
        subtitle = old_path.with_suffix(".zh.srt")
        subtitle.write_text("old subtitle")
        self._remove_cloud(old)
        new = self._item("Example.S01E01.2160p.mkv")
        self.url.get_strm_url.return_value = "https://example.invalid/new"
        self._run(new)
        new_path = self.library / "Example.S01E01.2160p.strm"
        self.assertFalse(old_path.exists())
        self.assertFalse(subtitle.exists())
        self.helper = self.module.TransferStrmHelper()
        self._run(old)
        self.assertFalse(old_path.exists())
        self.assertEqual(new_path.read_text(), "https://example.invalid/new")
        self.assertEqual(self.scrape.call_count, 2)

    def test_first_delivery_out_of_order_requires_current_cloud_identity(self) -> None:
        """
        从未见过的旧事件晚于新事件到达时，以云端身份拒绝旧写入
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        new = self._item("Example.S01E01.2160p.mkv")
        self._remove_cloud(old)
        self._run(new)
        self._run(old)
        self.assertFalse((self.library / "Example.S01E01.1080p.strm").exists())
        self.assertTrue((self.library / "Example.S01E01.2160p.strm").exists())
        self.scrape.assert_called_once()

    def test_same_path_replacement_rejects_old_file_id(self) -> None:
        """
        同名文件已被新文件 ID 替换时，旧事件不能覆盖其 STRM
        """
        old = self._item()
        new = self._item()
        new["transferinfo"].target_item.fileid = "202"
        new["idempotency_key"] = "new-event"
        self._run(new)
        path = self.library / "Example.S01E01.strm"
        stamp = self.files.fingerprint(path)
        self.url.get_strm_url.return_value = "https://example.invalid/old"
        self._run(old)
        self.assertEqual(self.files.fingerprint(path), stamp)

    def test_cloud_errors_propagate_without_touching_files(self) -> None:
        """
        回源异常不会被当成文件不存在或允许执行删除
        """
        item = self._item()
        self.storage.get_file_item_strict.side_effect = RuntimeError(
            "cloud unavailable"
        )
        with self.assertRaisesRegex(RuntimeError, "cloud unavailable"):
            self._run(item)
        self.assertFalse(self.library.exists())
        self.storage.get_file_item_strict.side_effect = lambda storage, path: (
            self.remote_files.get((storage, path.as_posix()))
        )
        self._run(item)
        self.assertTrue((self.library / "Example.S01E01.strm").exists())

    def test_transfer_timestamp_change_preserves_file_identity(self) -> None:
        """
        移动或复制后的云端时间不同于完成事件快照时仍生成文件，重放不重复执行
        """
        for mode, name in (("move", "moved.mkv"), ("copy", "copied.mkv")):
            with self.subTest(mode=mode):
                item = self._item(name)
                transfer = item["transferinfo"]
                transfer.transfer_type = mode
                target = transfer.target_item
                target.size = 73053519159
                target.modify_time = 1791622064
                source = target.model_copy(
                    update={
                        "path": f"/incoming/{name}",
                        "fileid": "100" if mode == "copy" else target.fileid,
                        "pickcode": "b" * 17 if mode == "copy" else target.pickcode,
                    }
                )
                transfer.fileitem = source
                item["fileitem"] = source
                if mode == "copy":
                    self.remote_files[(source.storage, source.path)] = source
                self.remote_files[(target.storage, target.path)] = target.model_copy(
                    update={"modify_time": 1791877143}
                )
                message = SimpleNamespace(
                    payload=self.durable.snapshot_transfer_result(item)
                )
                handler = self.outbox[self.types.EventType.TransferComplete.value]
                handler(message)
                path = self.library / Path(name).with_suffix(".strm")
                self.assertEqual(path.read_text(), "https://example.invalid/video")
                stamp = self.files.fingerprint(path)
                key = self.processor.event_key(
                    item, self.types.EventType.TransferComplete
                )
                record = self.processor.TransferPostprocessStore().load(key)
                self.assertEqual(record["state"], "done")
                self.assertEqual(record["plan"]["identity"]["fileid"], target.fileid)
                self.assertEqual(record["plan"]["pickcode"], target.pickcode)
                self.url.get_strm_url.assert_called_with(
                    target.pickcode, target.name, target.path
                )
                if mode == "copy":
                    self.assertNotEqual(source.fileid, target.fileid)
                    self.assertNotEqual(source.pickcode, target.pickcode)
                    self.assertIs(
                        self.remote_files[(source.storage, source.path)], source
                    )
                self.assertTrue(all(record["plan"]["effects"].values()))
                self.scrape.assert_called_once()
                self.helper = self.module.TransferStrmHelper()
                handler(message)
                self.assertEqual(self.files.fingerprint(path), stamp)
                self.scrape.assert_called_once()
                self.scrape.reset_mock()

    def test_copy_uses_target_pickcode_when_file_id_is_unavailable(self) -> None:
        """
        复制目标缺少文件 ID 时使用目标 pickcode，源文件身份不参与目标校验
        """
        item = self._item()
        target = item["transferinfo"].target_item
        source = target.model_copy(
            update={"path": "/incoming/source.mkv", "pickcode": "b" * 17}
        )
        item["fileitem"] = source
        item["transferinfo"].fileitem = source
        target.fileid = None
        target.modify_time = 1
        self.client.to_id.return_value = 101
        self.database.process_fileitem.side_effect = _method(
            Path(__file__).resolve().parents[1] / "db_manager/file_oper.py",
            "process_fileitem",
            {"Path": Path},
        )
        self.remote_files[(target.storage, target.path)] = target.model_copy(
            update={"modify_time": 2}
        )
        self._run(item)
        self.assertTrue((self.library / "Example.S01E01.strm").exists())
        self.url.get_strm_url.assert_called_once_with(
            target.pickcode, target.name, target.path
        )
        self.client.to_id.assert_called_once_with(target.pickcode)
        indexed = self.database.upsert_batch.call_args.args[0][0]["data"]
        self.assertEqual(indexed["id"], 101)
        self.assertEqual(indexed["pickcode"], target.pickcode)
        self.assertIsNone(target.fileid)

    def test_same_identity_with_changed_size_is_superseded(self) -> None:
        """
        精确快照已固定后，文件大小变化仍阻止旧事件写入
        """
        item = self._item()
        target = item["transferinfo"].target_item
        target.size = 100
        target.modify_time = 1
        with patch.object(self.helper, "_prepare_file", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                self._run(item)
        self.remote_files[(target.storage, target.path)] = target.model_copy(
            update={"size": 200, "modify_time": 2}
        )
        self._run(item)
        self.assertFalse((self.library / "Example.S01E01.strm").exists())
        self.scrape.assert_not_called()
        key = self.processor.event_key(item, self.types.EventType.TransferComplete)
        self.assertEqual(
            self.processor.TransferPostprocessStore().load(key)["state"], "superseded"
        )

    def test_live_old_cloud_file_is_not_deleted_by_latest(self) -> None:
        """
        latest 候选在云端仍有效时保留，不以到达顺序判定过期
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self._run(old)
        self._run(self._item("Example.S01E01.2160p.mkv"))
        self.assertEqual(len(list(self.library.glob("*.strm"))), 2)

    def test_write_then_checkpoint_failure_recovers_without_rewriting(self) -> None:
        """
        原子替换成功而归属检查点失败时，重启后识别暂存文件指纹并续做
        """
        item = self._item()
        store = self.processor.TransferPostprocessStore
        with patch.object(
            store, "complete_file", side_effect=RuntimeError("checkpoint failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "checkpoint failed"):
                self._run(item)
        path = self.library / "Example.S01E01.strm"
        stamp = self.files.fingerprint(path)
        self.helper = self.module.TransferStrmHelper()
        with patch.object(
            self.helper, "_prepare_file", side_effect=AssertionError("不能重写")
        ):
            self._run(item)
        self.assertEqual(self.files.fingerprint(path), stamp)
        self.scrape.assert_called_once()

    def test_partial_download_never_replaces_existing_subtitle(self) -> None:
        """
        下载失败只留下暂存内容，原字幕不被半文件覆盖，重试后原子发布
        """
        item = self._item("Example.S01E01.srt")
        self.library.mkdir()
        target = self.library / "Example.S01E01.srt"
        target.write_bytes(b"existing")

        def partial(file_path, **kwargs):
            file_path.write_bytes(b"partial")
            return False

        self.downloader.save_mediainfo_file.side_effect = partial
        with self.assertRaisesRegex(RuntimeError, "保存失败"):
            self._run(item, self.types.EventType.SubtitleTransferComplete)
        self.assertEqual(target.read_bytes(), b"existing")

        def complete(file_path, **kwargs):
            file_path.write_bytes(b"complete")
            return True

        self.downloader.save_mediainfo_file.side_effect = complete
        self._run(item, self.types.EventType.SubtitleTransferComplete)
        self.assertEqual(target.read_bytes(), b"complete")
        self.assertFalse(list(self.library.glob("*.part")))

    def test_external_change_after_interrupted_write_is_preserved(self) -> None:
        """
        写入后记录失败期间目标被其他工作修改，恢复时保留当前文件
        """
        item = self._item()
        with patch.object(
            self.processor.TransferPostprocessStore,
            "complete_file",
            side_effect=RuntimeError("crash"),
        ):
            with self.assertRaises(RuntimeError):
                self._run(item)
        target = self.library / "Example.S01E01.strm"
        target.write_text("new external owner")
        self._run(item)
        self.assertEqual(target.read_text(), "new external owner")
        self.scrape.assert_not_called()

    def test_failed_refresh_remains_pending_and_retries_only_refresh(self) -> None:
        """
        刷新返回失败时保留待重试状态，恢复后不重写 STRM 或重复刮削
        """
        self.config.transfer_monitor_media_server_refresh_enabled = True
        refresh = self.module.MediaServerRefresh.return_value.refresh_mediaserver
        refresh.return_value = False
        item = self._item()
        key = self.processor.event_key(item, self.types.EventType.TransferComplete)
        store = self.processor.TransferPostprocessStore()
        with self.assertRaisesRegex(RuntimeError, "媒体服务器刷新失败"):
            self._run(item)
        record = store.load(key)
        self.assertEqual(record["state"], "pending")
        self.assertFalse(record["plan"]["effects"]["refresh"])
        self.assertTrue(record["plan"]["effects"]["scrape"])
        target = self.library / "Example.S01E01.strm"
        stamp = self.files.fingerprint(target)
        refresh.return_value = True
        self._run(item)
        self.assertEqual(store.load(key)["state"], "done")
        self.assertEqual(self.files.fingerprint(target), stamp)
        self.scrape.assert_called_once()
        self.assertEqual(refresh.call_count, 2)
        self._run(item)
        self.assertEqual(refresh.call_count, 2)

    def test_completed_write_is_not_repeated_when_scrape_retries(self) -> None:
        """
        刮削提交失败后只重试未完成效果，路径和内容使用首次固定值
        """
        item = self._item()
        self.scrape.side_effect = RuntimeError("scrape unavailable")
        with self.assertRaises(RuntimeError):
            self._run(item)
        target = self.library / "Example.S01E01.strm"
        stamp = self.files.fingerprint(target)
        self.url.get_strm_url.return_value = "changed URL template"
        self.config.transfer_monitor_paths = f"{self.root / 'changed'}#/unmatched"
        self.config.transfer_monitor_scrape_metadata_enabled = False
        self.scrape.side_effect = None
        self._run(item)
        self.assertEqual(self.files.fingerprint(target), stamp)
        self.assertEqual(self.scrape.call_count, 2)
        self.assertFalse((self.root / "changed").exists())

    def test_delete_checkpoint_failure_does_not_delete_replacement(self) -> None:
        """
        删除成功而检查点失败后出现新的同名文件，恢复时不得再次删除
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self._run(old)
        self._remove_cloud(old)
        new = self._item("Example.S01E01.2160p.mkv")
        store = self.processor.TransferPostprocessStore
        complete = store.complete_file

        def fail_delete(instance, key, plan, operation):
            if operation["kind"] == "delete":
                raise RuntimeError("delete checkpoint failed")
            return complete(instance, key, plan, operation)

        with patch.object(store, "complete_file", fail_delete):
            with self.assertRaisesRegex(RuntimeError, "delete checkpoint failed"):
                self._run(new)
        old_path = self.library / "Example.S01E01.1080p.strm"
        self.assertFalse(old_path.exists())
        old_path.write_text("replacement")
        self._run(new)
        self.assertEqual(old_path.read_text(), "replacement")

    def test_concurrent_duplicate_event_runs_effects_once(self) -> None:
        """
        并发投递由媒体库锁串行处理，第二个监听器读取已完成检查点
        """
        from concurrent.futures import ThreadPoolExecutor

        item = self._item()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self._run, item) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.scrape.assert_called_once()

    def _move_item(self) -> Dict[str, Any]:
        self.config.transfer_monitor_paths = f"{self.library}#/cloud"
        self.config.transfer_monitor_remove_stale_strm = True
        self.config.transfer_monitor_remove_stale_strm_file = True
        self.config.transfer_monitor_remove_stale_strm_dir = True
        item = self._item()
        item["transferinfo"].transfer_type = "move"
        item["transferinfo"].fileitem = self.file_type(
            storage="u115", path="/cloud/old/Example.S01E01.mkv", fileid="101"
        )
        old = self.library / "old"
        old.mkdir(parents=True)
        for name in (
            "Example.S01E01.strm",
            "Example.S01E01.srt",
            "poster.jpg",
            "movie.nfo",
        ):
            (old / name).write_text("old")
        return item

    def test_move_cleanup_preserves_original_related_and_directory_options(
        self,
    ) -> None:
        """
        重新整理保留旧 STRM、关联刮削文件和空目录的清理能力
        """
        self._run(self._move_item())
        self.assertFalse((self.library / "old").exists())
        self.assertTrue(
            (self.library / "Example/Season 01/Example.S01E01.strm").exists()
        )

    def test_move_cleanup_disabled_preserves_original_files(self) -> None:
        """
        关闭移动源清理总开关后不删除任何源文件
        """
        item = self._move_item()
        self.config.transfer_monitor_remove_stale_strm = False
        self._run(item)
        self.assertEqual(len(list((self.library / "old").iterdir())), 4)

    def test_move_cleanup_without_related_preserves_sidecars(self) -> None:
        """
        关闭关联清理只删除旧 STRM，保留字幕和共享刮削文件
        """
        item = self._move_item()
        self.config.transfer_monitor_remove_stale_strm_file = False
        self._run(item)
        self.assertEqual(len(list((self.library / "old").iterdir())), 3)

    def test_move_cleanup_without_directory_removal_keeps_empty_directory(self) -> None:
        """
        关闭目录清理时保留清空后的旧目录
        """
        item = self._move_item()
        self.config.transfer_monitor_remove_stale_strm_dir = False
        self._run(item)
        self.assertEqual(list((self.library / "old").iterdir()), [])

    def test_same_path_move_keeps_new_file_and_shared_artwork(self) -> None:
        """
        源目标相同的原地整理不触发旧路径清理
        """
        item = self._move_item()
        item["transferinfo"].fileitem = item["transferinfo"].target_item.model_copy()
        self._run(item)
        self.assertTrue(
            (self.library / "Example/Season 01/Example.S01E01.strm").exists()
        )
        self.assertEqual(len(list((self.library / "old").iterdir())), 4)

    def test_pending_old_event_is_superseded_by_new_cloud_result(self) -> None:
        """
        A 后续效果失败后 B 已完成，A 恢复时不得继续清理或刮削
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self.scrape.side_effect = RuntimeError("scrape failed")
        with self.assertRaises(RuntimeError):
            self._run(old)
        self.scrape.side_effect = None
        self._remove_cloud(old)
        self._run(self._item("Example.S01E01.2160p.mkv"))
        self._run(old)
        self.assertEqual(
            [p.name for p in self.library.glob("*.strm")], ["Example.S01E01.2160p.strm"]
        )
        self.assertEqual(self.scrape.call_count, 2)

    def test_legacy_event_without_id_has_stable_replay_identity(self) -> None:
        """
        无持久事件键的旧同步结果使用完整文件身份去重
        """
        item = self._item()
        item.pop("idempotency_key")
        self._run(item)
        self._run(item)
        self.scrape.assert_called_once()

    def test_unowned_latest_candidate_requires_recoverable_cloud_name(self) -> None:
        """
        未跟踪的旧 STRM 仅在可还原云端名称并确认不存在时清理
        """
        self._latest()
        self.library.mkdir()
        known = self.library / "Example.S01E01.720p.strm"
        unknown = self.library / "Example.S01E01.1080p.strm"
        known.write_text(
            "https://isolated.invalid/?pickcode=old&file_name=Example.S01E01.720p.mkv"
        )
        unknown.write_text("https://isolated.invalid/opaque")
        self._run(self._item("Example.S01E01.2160p.mkv"))
        self.assertFalse(known.exists())
        self.assertTrue(unknown.exists())

    def test_new_files_after_failed_write_are_not_added_to_cleanup_plan(self) -> None:
        """
        首次固定清单后写入失败，重试不重新扫描并删除后来出现的版本
        """
        self._latest()
        item = self._item("Example.S01E01.1080p.mkv")
        with patch.object(self.helper, "_prepare_file", side_effect=OSError("failed")):
            with self.assertRaises(OSError):
                self._run(item)
        later = self.library / "Example.S01E01.2160p.strm"
        later.write_text("newer file")
        self._run(item)
        self.assertEqual(later.read_text(), "newer file")

    def test_file_changed_during_cloud_query_is_not_deleted(self) -> None:
        """
        清理回源期间文件被替换，删除前二次核对保留新内容
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self._run(old)
        self._remove_cloud(old)
        old_path = self.library / "Example.S01E01.1080p.strm"
        new = self._item("Example.S01E01.2160p.mkv")

        def query(storage, path):
            if path.as_posix() == old["transferinfo"].target_item.path:
                old_path.write_text("changed while querying")
                return None
            return self.remote_files.get((storage, path.as_posix()))

        self.storage.get_file_item_strict.side_effect = query
        self._run(new)
        self.assertEqual(old_path.read_text(), "changed while querying")

    def test_same_directory_move_keeps_shared_artwork(self) -> None:
        """
        同目录改名清理旧文件和其字幕，同时保留新 STRM 的共享图片
        """
        item = self._move_item()
        target = item["transferinfo"].target_item
        self._remove_cloud(item)
        target.path = "/cloud/old/Example.S01E01.renamed.mkv"
        target.name = "Example.S01E01.renamed.mkv"
        item["transferinfo"].target_diritem.path = "/cloud/old"
        self.remote_files[(target.storage, target.path)] = target
        self._run(item)
        self.assertFalse((self.library / "old/Example.S01E01.strm").exists())
        self.assertTrue((self.library / "old/Example.S01E01.renamed.strm").exists())
        self.assertTrue((self.library / "old/poster.jpg").exists())
        self.assertTrue((self.library / "old/movie.nfo").exists())

    def test_missing_pickcode_does_not_start_download(self) -> None:
        """
        字幕缺少 pickcode 时保留原跳过行为，不提交下载
        """
        item = self._item("Example.S01E01.srt")
        item["transferinfo"].target_item.pickcode = None
        self._run(item, self.types.EventType.SubtitleTransferComplete)
        self.downloader.get_download_url.assert_not_called()
        self.assertFalse(self.library.exists())

    def test_replaced_output_stops_pending_cleanup(self) -> None:
        """
        新文件写入后清理中断，目标被替换时旧计划不再删除其他文件
        """
        self._latest()
        old = self._item("Example.S01E01.1080p.mkv")
        self._run(old)
        self._remove_cloud(old)
        new = self._item("Example.S01E01.2160p.mkv")
        with patch.object(
            self.processor.TransferPostprocessor,
            "_delete",
            side_effect=OSError("cleanup failed"),
        ):
            with self.assertRaises(OSError):
                self._run(new)
        output = self.library / "Example.S01E01.2160p.strm"
        output.write_text("external replacement")
        self._run(new)
        self.assertTrue((self.library / "Example.S01E01.1080p.strm").exists())
        self.assertEqual(output.read_text(), "external replacement")
