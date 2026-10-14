from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from p115center.schemas import ShareInfo

import test_v3_scrape_identity as host_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3ShareReporting(TestCase):
    """
    使用真实 V3 媒体对象及 SDK 模型验证分享上报字段
    """

    def setUp(self) -> None:
        """
        保留媒体和上报模型，隔离外部分享信息服务
        """
        self.host = host_fixture.TestV3ScrapeIdentity()
        self.addCleanup(self.host.doCleanups)
        self.host.setUp()
        self.config = MagicMock()
        self.config.get_config.side_effect = lambda key: {
            "upload_share_info": True,
            "machine_id": "isolated-test-machine",
        }[key]
        self.center = MagicMock()
        namespace = {
            "configer": self.config,
            "ShareInfo": ShareInfo,
            "P115Center": self.center,
            "datetime": datetime,
            "timezone": timezone,
            "logger": MagicMock(),
        }
        self.report = _method(
            Path(__file__).resolve().parents[1] / "helper/share/__init__.py",
            "post_share_info",
            namespace,
        )

    def test_recognized_sources_preserve_existing_report_fields(self) -> None:
        """
        读取 V3 原生来源并保留各来源辅助编号、标题和季信息
        """
        for source, auxiliary in (
            (self.host.types.MediaSource.TMDB, {"tmdb_id": 42}),
            (self.host.types.MediaSource.Douban, {"douban_id": "42"}),
            (self.host.types.MediaSource.Bangumi, {"bangumi_id": 42}),
            (self.host.types.MediaSource.AniList, {"anilist_id": 42, "anidb_id": 84}),
            (self.host.types.MediaSource.TVDB, {"tvdb_id": 42}),
        ):
            with self.subTest(source=source):
                self.center.reset_mock()
                media = self.host.context.MediaInfo(
                    media_source=source,
                    media_id="42",
                    type=self.host.types.MediaType.TV,
                    title="隔离测试剧集",
                    year="2026",
                    season=2,
                    imdb_id="tt123",
                    **auxiliary,
                )
                self.assertFalse(hasattr(media, "source"))
                self.report("115", "share-code", "receive-code", media)
                upload = self.center.return_value.upload_share_info
                upload.assert_called_once()
                self.assertEqual(upload.call_args.kwargs["mtype"], "115")
                payload = upload.call_args.kwargs["payload"]
                self.assertIsInstance(payload, ShareInfo)
                values = payload.model_dump(mode="json")
                self.assertEqual(values["source"], source.value)
                self.assertEqual(values["media_id"], "42")
                self.assertEqual(values["type"], media.type.value)
                self.assertEqual(values["title"], media.title)
                self.assertEqual(values["year"], "2026")
                self.assertEqual(values["season"], 2)
                self.assertEqual(values["imdb_id"], "tt123")
                self.assertEqual(
                    values["url"],
                    "https://115cdn.com/s/share-code?password=receive-code",
                )
                for name, value in auxiliary.items():
                    self.assertEqual(values[name], value)

    def test_unrecognized_and_aliyun_reports_keep_url_contract(self) -> None:
        """
        无识别信息及阿里分享继续使用原链接和平台类型
        """
        self.report("aliyun", "ali-code", None, None)
        upload = self.center.return_value.upload_share_info
        self.assertEqual(upload.call_args.kwargs["mtype"], "ali")
        payload = upload.call_args.kwargs["payload"]
        self.assertEqual(payload.url, "https://www.alipan.com/s/ali-code")
        self.assertIsNone(payload.source)
        self.assertIsNone(payload.media_id)
        self.assertIsNone(payload.title)
        self.assertIsNone(payload.tmdb_id)

    def test_new_source_does_not_fill_unrelated_provider_id(self) -> None:
        """
        新增来源保持来源名称，不将原生编号错误写入其他站点编号
        """
        media = self.host.context.MediaInfo(
            media_source=self.host.types.MediaSource.AniList,
            media_id="42",
            type=self.host.types.MediaType.TV,
        )
        self.report("115", "share-code", "receive-code", media)
        payload = self.center.return_value.upload_share_info.call_args.kwargs["payload"]
        self.assertEqual(payload.source, "anilist")
        self.assertEqual(payload.media_id, "42")
        for field in ("tmdb_id", "douban_id", "bangumi_id"):
            self.assertIsNone(getattr(payload, field))

    def test_opaque_and_extension_identities_survive_both_share_platforms(self) -> None:
        """
        IMDb 和扩展来源的非数字主身份原样上报，不用其他来源编号替换
        """
        for platform in ("115", "aliyun"):
            for source, native_id in (
                ("imdb", "tt123"),
                ("custom.catalog", "show:0042"),
            ):
                with self.subTest(platform=platform, source=source):
                    media = self.host.context.MediaInfo(
                        media_source=source,
                        media_id=native_id,
                        type=self.host.types.MediaType.TV,
                        tmdb_id=12345,
                    )
                    self.report(platform, "share-code", "receive-code", media)
                    payload = (
                        self.center.return_value.upload_share_info.call_args.kwargs[
                            "payload"
                        ]
                    )
                    self.assertEqual(payload.source, source)
                    self.assertEqual(payload.media_id, native_id)
                    self.assertEqual(payload.tmdb_id, 12345)

    def test_disabled_reporting_does_not_construct_client(self) -> None:
        """
        关闭分享上报时保持不创建客户端的原行为
        """
        self.config.get_config.side_effect = lambda key: False
        self.report("115", "share-code", "receive-code", None)
        self.center.assert_not_called()
