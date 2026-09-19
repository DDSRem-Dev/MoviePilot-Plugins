from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from sys import modules
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock


class _Cache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def clear(self):
        self.data.clear()


def _package(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []
    modules[name] = module
    return module


def _load_queue_module():
    original_modules = {}

    def install(name: str, module: ModuleType) -> None:
        original_modules[name] = modules.get(name)
        modules[name] = module

    for package_name in (
        "app",
        "app.chain",
        "p115strmhelper",
        "p115strmhelper.core",
        "p115strmhelper.helper",
        "p115strmhelper.helper.strm",
        "p115strmhelper.helper.strm.share",
        "p115strmhelper.utils",
    ):
        if package_name not in modules:
            original_modules[package_name] = None
            _package(package_name)

    transfer_module = ModuleType("app.chain.transfer")
    transfer_module.TransferChain = MagicMock
    install("app.chain.transfer", transfer_module)

    log_module = ModuleType("app.log")
    log_module.logger = MagicMock()
    install("app.log", log_module)

    schemas_module = ModuleType("app.schemas")
    schemas_module.FileItem = SimpleNamespace
    schemas_module.NotificationType = SimpleNamespace(Plugin="plugin")
    install("app.schemas", schemas_module)

    config_module = ModuleType("p115strmhelper.core.config")
    config_module.configer = SimpleNamespace(
        PLUGIN_CONFIG_PATH=Path("."),
        share_audit_queue_enabled=True,
        share_audit_max_wait_seconds=21600,
        share_audit_retry_interval_seconds=1800,
        rename_dict_supplement_enabled=True,
        notify=True,
        get_ios_ua_app=lambda app=False: {},
    )
    install("p115strmhelper.core.config", config_module)

    translations = {
        "share_audit_notify_queued_title": "⏳【115网盘】分享文件等待审核",
        "share_audit_notify_success_title": "✅【115网盘】分享审核下载完成",
        "share_audit_notify_failure_title": "❌【115网盘】分享审核下载失败",
        "share_audit_notify_share_code": "🔗 分享码：{share_code}",
        "share_audit_notify_queued_count": "⏳ 延迟下载 {count} 个",
        "share_audit_notify_success_count": "⬇️ 下载媒体文件 {count} 个",
        "share_audit_notify_failure_count": "🚫 下载媒体失败 {count} 个",
        "share_audit_notify_retry": "🔄 {minutes} 分钟后检查",
        "share_audit_notify_reason": "📝 原因：{reason}",
        "share_audit_notify_reason_timeout": "审核等待超过 {hours} 小时",
        "share_audit_notify_reason_expired": "分享链接已失效或过期",
        "share_audit_notify_reason_download_failed": "审核通过后下载仍然失败",
    }
    i18n_module = ModuleType("p115strmhelper.core.i18n")
    i18n_module.i18n = SimpleNamespace(
        translate=lambda key, **kwargs: translations[key].format(**kwargs)
    )
    install("p115strmhelper.core.i18n", i18n_module)

    message_module = ModuleType("p115strmhelper.core.message")
    message_module.post_message = MagicMock()
    install("p115strmhelper.core.message", message_module)

    cache_module = ModuleType("p115strmhelper.core.cache")
    cache_module.rename_media_fields_cacher = _Cache()
    install("p115strmhelper.core.cache", cache_module)

    rename_module = ModuleType("p115strmhelper.utils.rename_dict")
    rename_module.RenameDictUtils = SimpleNamespace(
        emby_mediainfo_to_rename_fields=lambda payload: payload,
        ffprobe_get_media_info=lambda url=None: (None, "探测失败"),
    )
    install("p115strmhelper.utils.rename_dict", rename_module)

    limiter_module = ModuleType("p115strmhelper.utils.limiter")
    limiter_module.RateLimiter = lambda qps: MagicMock()
    install("p115strmhelper.utils.limiter", limiter_module)

    module_path = (
        Path(__file__).resolve().parents[1]
        / "helper/strm/share/audit_download_queue.py"
    )
    module_name = "p115strmhelper.helper.strm.share.audit_download_queue"
    spec = spec_from_file_location(module_name, module_path)
    module = module_from_spec(spec)
    modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in original_modules.items():
            if original is None:
                modules.pop(name, None)
            else:
                modules[name] = original
    return module


queue_module = _load_queue_module()


class _Client:
    def __init__(self, state: int):
        self.state = state

    def share_snap_app(self, payload, **kwargs):
        return {"data": {"shareinfo": {"share_state": self.state}}}


class _Downloader:
    def __init__(self, state: int):
        self.client = _Client(state)
        self.downloaded = []
        self.p115_center = SimpleNamespace(
            download_emby_mediainfo_data=lambda items: {
                items[0][0].upper(): {"videoCodec": "H265"}
            }
        )

    def batch_auto_share_downloader(self, items):
        for item in items:
            path = Path(item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 2048)
            self.downloaded.append(path)
        return len(items), 0, []


class TestShareAuditDownloadQueue(TestCase):
    """
    分享文件审核等待队列测试
    """

    def setUp(self):
        """
        初始化隔离的队列和持久化路径
        """
        from tempfile import TemporaryDirectory

        self.temp_dir = TemporaryDirectory()
        queue_module.configer.PLUGIN_CONFIG_PATH = Path(self.temp_dir.name)
        queue_module.configer.share_audit_queue_enabled = True
        queue_module.configer.share_audit_max_wait_seconds = 21600
        queue_module.configer.share_audit_retry_interval_seconds = 1800
        queue_module.configer.rename_dict_supplement_enabled = True
        queue_module.configer.notify = True
        queue_module.post_message.reset_mock()
        self.queue = queue_module.ShareAuditDownloadQueue()
        self.queue._share_state_limiter = MagicMock()

    def tearDown(self):
        """
        清理临时目录
        """
        self.queue.stop()
        self.temp_dir.cleanup()

    def _item(self, name: str = "sample.srt"):
        return {
            "share_code": "share-code",
            "receive_code": "receive-code",
            "file_id": 1,
            "sha1": "ABC",
            "path": Path(self.temp_dir.name) / name,
            "mp_transfer_after_download": True,
            "media_relation_key": "source:relation-key",
            "related_media": {
                "sha1": "MEDIA-SHA1",
                "size": 1024,
                "strm_url": "http://127.0.0.1/media",
            },
        }

    def test_auditing_share_enters_persistent_queue(self):
        """
        审核中的分享文件进入持久化队列并使用三十分钟间隔
        """
        self.queue.bind_downloader(_Downloader(state=0))

        immediate, queued_count, failures = self.queue.partition_downloads(
            [self._item()]
        )

        self.assertEqual(immediate, [])
        self.assertEqual(queued_count, 1)
        self.assertEqual(failures, [])
        self.assertEqual(self.queue.pending_item_count(), 1)
        task = next(iter(self.queue._tasks.values()))
        self.assertAlmostEqual(
            task["next_retry_at"] - task["created_at"], 1800, delta=1
        )
        self.assertTrue(self.queue._get_persist_path().is_file())
        queue_module.post_message.assert_called_once()
        notification = queue_module.post_message.call_args.kwargs
        self.assertEqual(notification["title"], "⏳【115网盘】分享文件等待审核")
        self.assertIn("⏳ 延迟下载 1 个", notification["text"])
        self.assertIn("🔄 30 分钟后检查", notification["text"])

    def test_normal_share_remains_in_immediate_downloads(self):
        """
        审核通过的分享文件保留在即时下载列表
        """
        item = self._item()
        self.queue.bind_downloader(_Downloader(state=1))

        immediate, queued_count, failures = self.queue.partition_downloads([item])

        self.assertEqual(immediate, [item])
        self.assertEqual(queued_count, 0)
        self.assertEqual(failures, [])
        self.queue._share_state_limiter.acquire.assert_called_once()

    def test_expired_share_is_terminal_failure(self):
        """
        已失效分享直接返回永久失败路径
        """
        item = self._item()
        self.queue.bind_downloader(_Downloader(state=7))

        immediate, queued_count, failures = self.queue.partition_downloads([item])

        self.assertEqual(immediate, [])
        self.assertEqual(queued_count, 0)
        self.assertEqual(failures, [Path(item["path"]).as_posix()])

    def test_failed_download_is_queued_when_audit_state_changes(self):
        """
        即时失败残缺文件转入队列后持久化标记并强制重新下载
        """
        item = self._item()
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 2048)
        downloader = _Downloader(state=0)
        original_downloader = downloader.batch_auto_share_downloader
        downloader.batch_auto_share_downloader = MagicMock(
            side_effect=original_downloader
        )
        self.queue.bind_downloader(downloader)

        queued_paths = self.queue.enqueue_failed_auditing_downloads([item])

        self.assertEqual(queued_paths, [path.as_posix()])
        self.assertFalse(path.exists())
        self.assertEqual(self.queue.pending_item_count(), 1)
        task = next(iter(self.queue._tasks.values()))
        self.assertTrue(task["items"][0]["download_required"])

        restored = queue_module.ShareAuditDownloadQueue()
        restored._load_tasks_locked()
        restored_item = next(iter(restored._tasks.values()))["items"][0]
        self.assertTrue(restored_item["download_required"])

        path.write_bytes(b"x" * 2048)
        downloader.client.state = 1
        self.queue.transfer_local_file = MagicMock(return_value=True)
        self.queue._process_task(dict(task))

        downloader.batch_auto_share_downloader.assert_called_once()
        self.queue.transfer_local_file.assert_called_once()
        self.assertEqual(self.queue.pending_item_count(), 0)

    def test_failed_download_is_not_deferred_when_persistence_fails(self):
        """
        队列持久化失败时不清理残缺文件也不返回延期路径
        """
        item = self._item()
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 2048)
        self.queue.bind_downloader(_Downloader(state=0))
        self.queue._save_tasks_locked = MagicMock(return_value=False)

        queued_paths = self.queue.enqueue_failed_auditing_downloads([item])

        self.assertEqual(queued_paths, [])
        self.assertTrue(path.exists())
        self.assertEqual(self.queue.pending_item_count(), 0)

    def test_deferred_path_is_returned_when_invalid_file_cleanup_fails(self):
        """
        残缺文件清理失败时仍返回延期路径供调用方排除整理
        """
        item = self._item()
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 2048)
        self.queue.bind_downloader(_Downloader(state=0))
        self.queue._remove_invalid_download = MagicMock()

        queued_paths = self.queue.enqueue_failed_auditing_downloads([item])

        self.assertEqual(queued_paths, [path.as_posix()])
        self.assertTrue(path.exists())
        self.assertEqual(self.queue.pending_item_count(), 1)

    def test_duplicate_pending_item_is_marked_for_forced_download(self):
        """
        即时失败项已在队列中时升级已有任务的强制下载标记
        """
        item = self._item()
        path = Path(item["path"])
        downloader = _Downloader(state=0)
        self.queue.bind_downloader(downloader)
        self.queue.enqueue("share-code", "receive-code", [item])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 2048)

        queued_paths = self.queue.enqueue_failed_auditing_downloads([item])

        self.assertEqual(queued_paths, [path.as_posix()])
        self.assertFalse(path.exists())
        self.assertEqual(self.queue.pending_item_count(), 1)
        task = next(iter(self.queue._tasks.values()))
        self.assertTrue(task["items"][0]["download_required"])

    def test_successful_forced_download_is_not_repeated_for_transfer_retry(self):
        """
        强制下载成功后整理重试不重复下载文件
        """
        item = self._item()
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 2048)
        downloader = _Downloader(state=0)
        original_downloader = downloader.batch_auto_share_downloader
        downloader.batch_auto_share_downloader = MagicMock(
            side_effect=original_downloader
        )
        self.queue.bind_downloader(downloader)
        self.queue.enqueue_failed_auditing_downloads([item])
        task = next(iter(self.queue._tasks.values()))
        downloader.client.state = 1
        self.queue.transfer_local_file = MagicMock(return_value=False)

        self.queue._process_task(dict(task))

        pending_task = next(iter(self.queue._tasks.values()))
        self.assertNotIn("download_required", pending_task["items"][0])
        downloader.batch_auto_share_downloader.reset_mock()
        self.queue.transfer_local_file = MagicMock(return_value=True)

        self.queue._process_task(dict(pending_task))

        downloader.batch_auto_share_downloader.assert_not_called()
        self.queue.transfer_local_file.assert_called_once()
        self.assertEqual(self.queue.pending_item_count(), 0)

    def test_delayed_download_runs_moviepilot_post_action(self):
        """
        延迟下载完成后继续执行 MoviePilot 整理后处理
        """
        downloader = _Downloader(state=0)
        self.queue.bind_downloader(downloader)
        self.queue.enqueue("share-code", "receive-code", [self._item()])
        task = next(iter(self.queue._tasks.values()))
        downloader.client.state = 1
        self.queue.transfer_local_file = MagicMock(return_value=True)

        self.queue._process_task(dict(task))

        self.assertEqual(len(downloader.downloaded), 1)
        self.queue.transfer_local_file.assert_called_once()
        self.assertEqual(self.queue.pending_item_count(), 0)
        notification = queue_module.post_message.call_args_list[-1].kwargs
        self.assertEqual(notification["title"], "✅【115网盘】分享审核下载完成")
        self.assertIn("⬇️ 下载媒体文件 1 个", notification["text"])

    def test_task_checks_passed_state_at_maximum_wait(self):
        """
        到达最长等待时间时先检查状态并下载已通过文件
        """
        downloader = _Downloader(state=1)
        self.queue.bind_downloader(downloader)
        queue_module.configer.share_audit_max_wait_seconds = 3600
        queue_module.configer.share_audit_retry_interval_seconds = 3600
        self.queue.enqueue("share-code", "receive-code", [self._item()])
        task = next(iter(self.queue._tasks.values()))
        self.assertEqual(task["next_retry_at"], task["deadline_at"])
        task["deadline_at"] = 0
        self.queue.transfer_local_file = MagicMock(return_value=True)

        self.queue._process_task(dict(task))

        self.assertEqual(len(downloader.downloaded), 1)
        self.queue._share_state_limiter.acquire.assert_called_once()
        self.assertEqual(self.queue.pending_item_count(), 0)
        notification = queue_module.post_message.call_args_list[-1].kwargs
        self.assertEqual(notification["title"], "✅【115网盘】分享审核下载完成")

    def test_task_stops_after_final_audit_check(self):
        """
        到达最长等待时间且仍在审核时执行最终检查后终止
        """
        downloader = _Downloader(state=0)
        self.queue.bind_downloader(downloader)
        self.queue.enqueue("share-code", "receive-code", [self._item()])
        task = next(iter(self.queue._tasks.values()))
        task["deadline_at"] = 0

        self.queue._process_task(dict(task))

        self.queue._share_state_limiter.acquire.assert_called_once()
        self.assertEqual(downloader.downloaded, [])
        self.assertEqual(self.queue.pending_item_count(), 0)
        notification = queue_module.post_message.call_args_list[-1].kwargs
        self.assertEqual(notification["title"], "❌【115网盘】分享审核下载失败")
        self.assertIn("审核等待超过 6 小时", notification["text"])

    def test_failed_delayed_download_sends_notification(self):
        """
        审核通过后不超过一百字节的残缺文件按失败处理并清理
        """
        downloader = _Downloader(state=0)
        item = self._item()
        path = Path(item["path"])

        def write_partial_file(items):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 100)
            return 0, 1, [path.as_posix()]

        downloader.batch_auto_share_downloader = MagicMock(
            side_effect=write_partial_file
        )
        self.queue.bind_downloader(downloader)
        self.queue.enqueue("share-code", "receive-code", [item])
        task = next(iter(self.queue._tasks.values()))
        downloader.client.state = 1
        self.queue.transfer_local_file = MagicMock(return_value=True)

        self.queue._process_task(dict(task))

        self.assertFalse(path.exists())
        self.queue.transfer_local_file.assert_not_called()
        self.assertEqual(self.queue.pending_item_count(), 0)
        notification = queue_module.post_message.call_args_list[-1].kwargs
        self.assertEqual(notification["title"], "❌【115网盘】分享审核下载失败")
        self.assertIn("🚫 下载媒体失败 1 个", notification["text"])
        self.assertIn("审核通过后下载仍然失败", notification["text"])

    def test_reported_failure_path_overrides_large_file(self):
        """
        下载器报告失败时即使文件超过一百字节也不判定成功
        """
        downloader = _Downloader(state=0)
        item = self._item()
        path = Path(item["path"])

        def write_reported_failure(items):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 2048)
            return 0, 1, [path.as_posix()]

        downloader.batch_auto_share_downloader = MagicMock(
            side_effect=write_reported_failure
        )
        self.queue.bind_downloader(downloader)
        self.queue.enqueue("share-code", "receive-code", [item])
        task = next(iter(self.queue._tasks.values()))
        downloader.client.state = 1
        self.queue.transfer_local_file = MagicMock(return_value=True)

        self.queue._process_task(dict(task))

        self.assertFalse(path.exists())
        self.queue.transfer_local_file.assert_not_called()
        self.assertEqual(self.queue.pending_item_count(), 0)

    def test_notifications_follow_global_switch(self):
        """
        关闭全局通知时不发送延迟下载通知
        """
        queue_module.configer.notify = False
        self.queue.bind_downloader(_Downloader(state=0))

        self.queue.partition_downloads([self._item()])

        queue_module.post_message.assert_not_called()

    def test_media_fields_restore_from_persistent_context(self):
        """
        原一小时缓存失效后使用持久化主视频上下文恢复媒体字段
        """
        item = self._item()
        path = Path(item["path"])
        path.write_bytes(b"x" * 128)
        self.queue.bind_downloader(_Downloader(state=1))
        queue_module.rename_media_fields_cacher.clear()

        result = self.queue.transfer_local_file(path, item)

        self.assertTrue(result)
        self.assertEqual(
            queue_module.rename_media_fields_cacher.get("source:relation-key"),
            {"videoCodec": "H265"},
        )

    def test_media_context_is_ignored_when_supplement_disabled(self):
        """
        关闭媒体元数据补充时不恢复主视频字段
        """
        item = self._item()
        downloader = _Downloader(state=1)
        self.queue.bind_downloader(downloader)
        queue_module.configer.rename_dict_supplement_enabled = False
        queue_module.rename_media_fields_cacher.clear()

        result = self.queue.prepare_media_fields(item)

        self.assertFalse(result)
        self.assertIsNone(
            queue_module.rename_media_fields_cacher.get("source:relation-key")
        )

    def test_pending_tasks_restore_after_restart(self):
        """
        队列实例重建后恢复未完成任务
        """
        self.queue.bind_downloader(_Downloader(state=0))
        self.queue.enqueue("share-code", "receive-code", [self._item()])

        restored = queue_module.ShareAuditDownloadQueue()
        restored._load_tasks_locked()

        self.assertEqual(restored.pending_item_count(), 1)
        restored_item = next(iter(restored._tasks.values()))["items"][0]
        self.assertEqual(restored_item["related_media"]["sha1"], "MEDIA-SHA1")


if __name__ == "__main__":
    from unittest import main

    main(verbosity=2)
