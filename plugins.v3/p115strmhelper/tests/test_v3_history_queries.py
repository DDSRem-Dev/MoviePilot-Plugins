import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class TestV3HistoryQueries(TestCase):
    """
    通过真实宿主 SQL 查询、应用服务和 SDK 验证插件历史读取
    """

    def setUp(self) -> None:
        """
        隔离启动与云端依赖，保留实际数据库模型和只读查询链路
        """
        self.root = Path(__file__).resolve().parents[1]
        host = Path(
            os.environ.get("MOVIEPILOT_SOURCE", self.root.parents[2] / "MoviePilot")
        )
        if not (host / "app/sdk/queries.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        self.prefix = "_p115_history_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith("app.")
        }
        others = {}
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if (
                    name == "app"
                    or name.startswith("app.")
                    or name.startswith(self.prefix)
                ):
                    sys.modules.pop(name)
            sys.modules.update(originals)
            for name, original in others.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

        self.addCleanup(restore)

        def module(name: str, **values: Any) -> ModuleType:
            if not name.startswith(("app", self.prefix)):
                others[name] = sys.modules.get(name)
            result = ModuleType(name)
            result.__dict__.update(values)
            sys.modules[name] = result
            return result

        for name in (
            "app",
            "app.sdk",
            "app.schemas",
            "app.db",
            "app.db.models",
            "app.db.oper",
            "app.db.adapters",
            "app.runtime",
            "app.application",
            "app.foundation",
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        module("app.runtime.settings", get_runtime_setting=lambda name: "sqlite")
        module("app.db.oper.subscribe", SubscribeOper=object)
        module("app.db.oper.subscribehistory", SubscribeHistoryOper=object)
        base = importlib.import_module("app.db.base")
        self.transfer_model = importlib.import_module(
            "app.db.models.transferhistory"
        ).TransferHistory
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(bind=self.engine)

        def run_query(operation):
            with self.sessions.begin() as session:
                return operation(session)

        runner = patch.object(base, "run_sync_transaction", side_effect=run_query)
        runner.start()
        self.addCleanup(runner.stop)
        cut = importlib.import_module("app.foundation.text").cut
        module("app.sdk.utilities", SystemUtils=object, cut=cut)
        adapter_type = importlib.import_module(
            "app.db.adapters.query"
        ).SqlAlchemyDataQueryAdapter
        base.Base.metadata.create_all(self.engine)
        adapter = adapter_type(self.sessions)
        service_module = importlib.import_module("app.application.query")
        service_module._configured_data_query_service = service_module.DataQueryService(
            subscriptions=adapter,
            histories=adapter,
            async_executor=MagicMock(),
        )
        self.sdk = importlib.import_module("app.sdk.queries")
        self.types = importlib.import_module("app.schemas.types")
        sys.modules["app.schemas"].MessageType = self.types.MessageType
        for suffix in (
            "",
            ".db_manager",
            ".core",
            ".helper",
            ".helper.strm",
            ".helper.strm.share",
            ".utils",
        ):
            module(
                self.prefix + suffix,
                __path__=[
                    str(self.root.joinpath(*suffix.strip(".").split(".")))
                    if suffix
                    else str(self.root)
                ],
            )
        self.query_module = importlib.import_module(
            f"{self.prefix}.db_manager.moviepilot_transfer"
        )
        self.queries = self.query_module.TransferHBOper()
        self.config = SimpleNamespace(sync_del_remove_versions=False)
        self.logger = MagicMock()
        module("app.sdk.events", Event=SimpleNamespace)
        module("app.sdk.logging", logger=self.logger)
        module("app.sdk.config", settings=SimpleNamespace())
        module("app.sdk.services", DownloaderHelper=object)
        module("app.chain", __path__=[])
        module("app.chain.storage", StorageChain=object)
        module("app.application.history", get_transfer_history_repository=MagicMock())
        module("app.schemas.mediaserver", WebhookEventInfo=object)
        module(f"{self.prefix}.core.config", configer=self.config)
        module(f"{self.prefix}.core.i18n", i18n=MagicMock())
        module(f"{self.prefix}.core.message", post_message=MagicMock())
        module(f"{self.prefix}.core.plunins", PluginChian=object)
        module(
            f"{self.prefix}.db_manager.oper",
            TransferHBOper=self.query_module.TransferHBOper,
        )
        module(f"{self.prefix}.helper.mediaserver", EmbyOperate=object)
        module(
            f"{self.prefix}.utils.sentry",
            sentry_manager=SimpleNamespace(
                capture_all_class_exceptions=lambda cls: cls
            ),
        )
        module(f"{self.prefix}.utils.webhook", WebhookUtils=object)
        sync_module = importlib.import_module(f"{self.prefix}.helper.mediasyncdel")
        self.sync = object.__new__(sync_module.MediaSyncDelHelper)
        self.sync.transferhisb = self.queries
        self.sync.transferhis = MagicMock()
        module("share_strm_scan", Pair=object, ShareStrmScanCache=MagicMock())
        module(f"{self.prefix}.helper.strm.share.oof", ShareOOPServerHelper=object)
        self.cleaner = importlib.import_module(
            f"{self.prefix}.helper.strm.share.cleaner"
        )

    def add_history(self, **values: Any) -> int:
        """
        写入实际宿主历史表并返回主键
        """
        defaults: Dict[str, Any] = {
            "src": f"/source/{uuid4().hex}.mkv",
            "dest": "/library/file.mkv",
            "type": self.types.MediaType.MOVIE.value,
            "media_source": self.types.MediaSource.TMDB.value,
            "media_id": "42",
            "title": "电影",
            "status": True,
        }
        defaults.update(values)
        with self.sessions.begin() as session:
            item = self.transfer_model(**defaults)
            session.add(item)
            session.flush()
            return item.id

    def test_original_fuzzy_search_returns_all_matching_snapshots(self) -> None:
        """
        原分词检索返回全部命中项，并在宿主短会话关闭前物化快照
        """
        with self.sessions.begin() as session:
            session.add_all(
                [
                    self.transfer_model(
                        src=f"/src/{i}", dest=f"/library/{i}.mkv", status=True
                    )
                    for i in range(451)
                ]
            )
        rows = self.queries.get_transfer_his_by_path_title("/library")
        self.assertEqual(len(rows), 451)
        self.assertEqual({item.id for item in rows}, set(range(1, 452)))
        self.assertIsInstance(rows[0], self.sdk.TransferHistorySnapshot)
        with self.sessions.begin() as session:
            session.query(self.transfer_model).delete()
        self.assertEqual(len({item.dest for item in rows}), 451)

    def test_original_fuzzy_search_preserves_title_source_case_and_wildcards(
        self,
    ) -> None:
        """
        原分词搜索仍匹配标题、源路径、相邻目录、大小写及通配字符
        """
        expected = [self.add_history(dest="/A_%/file.mkv")]
        for values in (
            {"dest": "/ABx/file.mkv"},
            {"dest": "/A_%2/file.mkv"},
            {"dest": "/a_%/file.mkv"},
            {"src": "/A_%/source.mkv"},
            {"title": "/A_%"},
        ):
            expected.append(self.add_history(**values))
        self.assertEqual(
            {item.id for item in self.queries.get_transfer_his_by_path_title("/A_%")},
            set(expected),
        )

    def test_exact_path_selects_latest_without_wildcards(self) -> None:
        """
        精确路径查询返回最新一条且不把百分号当通配符
        """
        self.add_history(dest="/A_%.mkv")
        latest = self.add_history(dest="/A_%.mkv")
        self.add_history(dest="/ABx.mkv")
        self.assertEqual(self.queries.get_by_dest("/A_%.mkv").id, latest)
        self.assertIsNone(self.queries.get_by_dest("/missing"))

    def test_media_identity_and_episode_filters_are_all_required(self) -> None:
        """
        来源相异但数字相同的 ID、其他季集及其他版本不会交叉匹配
        """
        expected = self.add_history(type="电视剧", seasons="S01", episodes="E02")
        for values in (
            {"media_source": self.types.MediaSource.Douban.value},
            {"media_id": "43"},
            {"seasons": "S02"},
            {"episodes": "E03"},
            {"dest": "/other/version.mkv"},
            {"type": "电影"},
        ):
            row = {"type": "电视剧", "seasons": "S01", "episodes": "E02"}
            row.update(values)
            self.add_history(**row)
        rows = self.queries.list_by_media_identity(
            self.types.MediaSource.TMDB,
            "42",
            self.types.MediaType.TV,
            season="S01",
            episode="E02",
            dest="/library/file.mkv",
        )
        self.assertEqual([item.id for item in rows], [expected])

    def test_missing_identity_never_becomes_unfiltered_query(self) -> None:
        """
        身份缺失、零 ID 或空目标不会退化成全库查询
        """
        with patch.object(self.query_module, "list_transfer_history") as query:
            for identity in (None, "", " ", "0"):
                with self.subTest(identity=identity), self.assertRaises(ValueError):
                    self.queries.list_by_media_identity(
                        self.types.MediaSource.TMDB,
                        identity,
                        self.types.MediaType.MOVIE,
                    )
            with self.assertRaises(ValueError):
                self.queries.list_by_media_identity(
                    self.types.MediaSource.TMDB,
                    "42",
                    self.types.MediaType.MOVIE,
                    dest="",
                )
            self.assertIsNone(self.queries.get_by_dest(""))
            query.assert_not_called()

    def test_sync_delete_uses_sdk_identity_for_each_media_scope(self) -> None:
        """
        电影、剧、季、集使用 SDK 成对身份，多版本保留原按路径查询
        """
        movie = self.add_history()
        episode = self.add_history(
            type="电视剧", seasons="S01", episodes="E02", dest="/tv/ep.mkv"
        )
        latest = self.add_history(media_source=self.types.MediaSource.Douban.value)
        query = self.sync._MediaSyncDelHelper__get_transfer_his
        for kind, season, ep, path, expected in (
            ("Movie", None, None, "/library/file.mkv", movie),
            ("Episode", None, None, "/tv", episode),
            ("Episode", "1", None, "/tv", episode),
            ("Episode", "1", "2", "/tv/ep.mkv", episode),
        ):
            with self.subTest(kind=kind, season=season, ep=ep):
                _, rows = query(kind, "电影", path, 42, season, ep)
                self.assertEqual([item.id for item in rows], [expected])
        self.config.sync_del_remove_versions = True
        _, rows = query("Movie", "电影", "/library/file.mkv", 42, None, None)
        self.assertEqual([item.id for item in rows], [latest])
        self.assertEqual(
            query("Movie", "电影", "/library/file.mkv", 0, None, None), ("", [])
        )

    def test_retained_history_prevents_following_file_deletion(self) -> None:
        """
        宿主保留的持久任务历史不会被报告为已删
        """
        identity = self.add_history()
        self.assertFalse(self.sync._delete_transfer_history(identity))
        self.sync.transferhis.delete.assert_called_once_with(identity)
        with patch.object(Path, "unlink") as unlink:
            result = self.sync.remove_by_path("/library", del_source=True)
            self.assertEqual(result[2], 1)
            unlink.assert_not_called()
        with self.sessions.begin() as session:
            session.query(self.transfer_model).delete()
        self.assertTrue(self.sync._delete_transfer_history(identity))

    def test_missing_media_record_preserves_native_source_identity(self) -> None:
        """
        非 TMDB 来源的整理快照保持来源和原生 ID，不丢失或改写为 TMDB
        """
        identity = self.add_history(
            media_source=self.types.MediaSource.Bangumi.value, media_id="123"
        )
        snapshot = self.sdk.get_transfer_history(identity)
        row = self.cleaner.ShareStrmMissingMediaStore.row_from_transfer_history(
            snapshot, "/x.strm", "share", "code"
        )
        self.assertEqual(row["media_source"], self.types.MediaSource.Bangumi.value)
        self.assertEqual(row["media_id"], "123")
        self.assertNotIn("tmdbid", row)
