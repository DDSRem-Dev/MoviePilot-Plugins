from pathlib import Path
from re import search
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import test_v3_sync_lifecycle as sync_fixture
from test_v3_share_queue_lifecycle import _method


class TestV3TransferHookLifecycle(TestCase):
    """
    验证整理扩展回调运行期间保留 V3 实例资源
    """

    def setUp(self) -> None:
        """
        加载真实事件方法与服务类，隔离探测、存储和通知边界
        """
        self.runtime = sync_fixture.TestV3SyncLifecycle()
        self.runtime.setUp()
        self.addCleanup(self.runtime.doCleanups)
        self.service = self.runtime.service
        self.namespace = self.runtime.namespace
        self.namespace.update(
            servicer=self.service,
            TransferRenameBuildEventData=SimpleNamespace,
            TransferInterceptEventData=SimpleNamespace,
            TransferOverwriteCheckEventData=SimpleNamespace,
            RenameDictUtils=MagicMock(),
            StorageChain=MagicMock(),
            DirectoryHelper=MagicMock(),
            MediaType=SimpleNamespace(TV="TV"),
            UrlUtils=MagicMock(),
            sharestrmcacher=SimpleNamespace(file_item_dict={}),
            settings=SimpleNamespace(RMT_MEDIAEXT=[".mkv"], RMT_SUBEXT=[".srt"], RMT_AUDIOEXT=[".mka"]),
            re_search=search,
        )
        self.namespace["UrlUtils"].parse_query_params.return_value = {
            "share_code": "share", "receive_code": "abcd", "id": "42",
        }
        self.config = self.namespace["configer"]
        self.config.enabled = True
        self.config.rename_dict_supplement_enabled = True
        self.config.rename_dict_supplement_overwrite_mode = "fill_missing"
        self.config.transfer_intercept_exists_enabled = True
        self.config.share_strm_overwrite_check_enabled = True
        self.config.auto_delete_inferior_source_enabled = True
        self.config.notify = True
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "target.strm"
        self.target.write_text("https://isolated.invalid/P115StrmHelper?share_code=share&receive_code=abcd&id=42")
        plugin_cls = type("IsolatedPlugin", (), {"_rename_media_fields_cache": MagicMock()})
        plugin_cls._rename_media_fields_cache.get.return_value = None
        self.plugin = plugin_cls()
        self.plugin.chain = MagicMock()
        self.source = SimpleNamespace(type="file", path="/isolated/video.mkv", storage="local", extension="mkv")
        self.rename = SimpleNamespace(source_path=self.source.path, source_item=self.source, rename_dict={})
        self.intercept = SimpleNamespace(
            fileitem=self.source, cancel=False, mediainfo=SimpleNamespace(type="movie", title="synthetic"),
            target_path=Path("/isolated"), target_storage="local",
        )
        self.overwrite = SimpleNamespace(target_path=self.target, target_size=None)
        self.failed = {"fileitem": self.source, "transferinfo": SimpleNamespace(message="同名文件")}
        self.entries = (
            (
                "rename_dict_supplement", self.rename,
                self.namespace["RenameDictUtils"].ffprobe_get_media_info,
                ({"videoCodec": "H265"}, ""),
            ),
            (
                "intercept_if_exists_in_library", self.intercept, self.plugin.chain.media_exists,
                SimpleNamespace(server="synthetic"),
            ),
            (
                "share_strm_overwrite_check", self.overwrite,
                self.namespace["RenameDictUtils"].ffprobe_get_media_info,
                ({"file_size": 1024}, ""),
            ),
            (
                "auto_delete_inferior_source", self.failed,
                self.namespace["StorageChain"].return_value.delete_media_file, True,
            ),
        )
        self.namespace["StorageChain"].return_value.get_file_item.return_value = None
        root = Path(__file__).resolve().parents[1]
        for name, _, _, _ in self.entries:
            setattr(self.plugin, name, MethodType(_method(root / "__init__.py", name, self.namespace), self.plugin))

    def test_running_callbacks_block_stop_and_reload(self) -> None:
        """
        四类回调在途时拒绝释放资源，停止后不再进入探测、查询及删除
        """
        for name, data, boundary, result in self.entries:
            with self.subTest(entry=name):
                self.service._sync_stopping = False
                self.runtime.entered.clear()
                self.runtime.release.clear()
                boundary.reset_mock()

                def hold(*args, **kwargs):
                    self.runtime._block()
                    return result

                boundary.side_effect = hold
                event = SimpleNamespace(event_data=data)
                callback = getattr(self.plugin, name)
                worker = self.runtime._start(lambda: callback(event))
                try:
                    self.assertTrue(self.runtime.entered.wait(timeout=2))
                    client = self.service.client
                    stop = self.service._stop_sync_operations
                    with patch.object(self.service, "_stop_sync_operations", side_effect=lambda: stop(0)):
                        self.assertFalse(self.service.stop())
                    self.assertFalse(self.service.init_service())
                    self.assertIs(self.service.client, client)
                    self.namespace["directory_upload_queue"].stop.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError, "同步服务已停止"):
                        callback(event)
                    self.assertEqual(boundary.call_count, 1)
                finally:
                    self.runtime.release.set()
                    worker.join(timeout=2)
                    boundary.side_effect = None
                self.assertFalse(worker.is_alive())
                self.assertEqual(self.runtime.errors, [])
                self.assertEqual(self.service._sync_operations, {})
        self.assertEqual(self.rename.rename_dict, {"videoCodec": "H265"})
        self.assertTrue(self.intercept.cancel)
        self.assertEqual(self.overwrite.target_size, 1024)
        self.namespace["post_message"].assert_called_once()

    def test_original_filters_skip_closed_service(self) -> None:
        """
        原停用、无效模型、伴随文件及非质量失败过滤不触发业务
        """
        self.service._sync_stopping = True
        self.config.enabled = False
        for name, data, _, _ in self.entries:
            self.assertIsNone(getattr(self.plugin, name)(SimpleNamespace(event_data=data)))
        self.config.enabled = True
        for name, _, _, _ in self.entries[:3]:
            self.assertIsNone(getattr(self.plugin, name)(SimpleNamespace(event_data={})))
        self.rename.source_item = SimpleNamespace(type="dir")
        self.plugin.rename_dict_supplement(SimpleNamespace(event_data=self.rename))
        self.intercept.fileitem = SimpleNamespace(type="file", extension="srt")
        self.plugin.intercept_if_exists_in_library(SimpleNamespace(event_data=self.intercept))
        self.overwrite.target_path = Path("/isolated/target.mkv")
        self.plugin.share_strm_overwrite_check(SimpleNamespace(event_data=self.overwrite))
        self.failed["transferinfo"].message = "网络失败"
        self.plugin.auto_delete_inferior_source(SimpleNamespace(event_data=self.failed))
        for _, _, boundary, _ in self.entries:
            boundary.assert_not_called()
        self.assertEqual(self.service._sync_operations, {})

    def test_original_exceptions_release_registration(self) -> None:
        """
        原查询和删除异常继续捕获，原探测异常继续传播，均释放登记
        """
        for name, data, boundary, _ in self.entries:
            with self.subTest(entry=name):
                boundary.side_effect = ValueError("synthetic")
                event = SimpleNamespace(event_data=data)
                if name in ("rename_dict_supplement", "share_strm_overwrite_check"):
                    with self.assertRaisesRegex(ValueError, "synthetic"):
                        getattr(self.plugin, name)(event)
                else:
                    self.assertIsNone(getattr(self.plugin, name)(event))
                self.assertEqual(self.service._sync_operations, {})
                boundary.side_effect = None
