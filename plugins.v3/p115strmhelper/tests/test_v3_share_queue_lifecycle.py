import ast
import asyncio
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from test_share_audit_download_queue import _Downloader, _load_queue_module


def _method(path: Path, name: str, namespace: Dict[str, Any]) -> Any:
    tree = ast.parse(path.read_text())
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    method.decorator_list = []
    code = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            method,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(code), str(path), "exec"), namespace)
    return namespace[name]


class TestV3ShareQueueLifecycle(TestCase):
    """
    验证审核队列关停状态到宿主及配置更新入口的传播
    """

    def setUp(self) -> None:
        """
        创建独立目录和真实队列并隔离网络发送
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plugin_root = Path(__file__).resolve().parents[1]
        self.module = _load_queue_module()
        self.module.configer.PLUGIN_CONFIG_PATH = self.root / "old"
        self.queue = self.module.ShareAuditDownloadQueue()
        self.addCleanup(self.queue.stop)
        self.downloader = _Downloader(1)
        self.queue._share_state_limiter = MagicMock()
        self.queue.bind_downloader(self.downloader)

    def _enqueue(self) -> Dict[str, Any]:
        self.queue.enqueue(
            "share",
            "receive",
            [
                {
                    "path": self.root / "sample.srt",
                    "share_code": "share",
                    "file_id": 1,
                    "mp_transfer_after_download": True,
                }
            ],
        )
        return next(iter(self.queue._tasks.values()))

    def test_stop_timeout_preserves_worker_and_rejects_restart_or_rebind(self) -> None:
        """
        真实下载未退出时保持停止信号且不更换下载器
        """
        entered, release = Event(), Event()
        original = self.downloader.batch_auto_share_downloader

        def download(items):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("测试未释放下载")
            return original(items)

        self.downloader.batch_auto_share_downloader = download
        task = self._enqueue()
        task["next_retry_at"] = 0
        self.queue._save_tasks_locked()
        self.queue.start()
        worker = self.queue._worker_thread
        self.addCleanup(release.set)
        try:
            self.assertTrue(entered.wait(timeout=5))
            join = worker.join
            with patch.object(
                worker, "join", side_effect=lambda timeout: join(timeout=0.01)
            ):
                self.assertIs(self.queue.stop(), False)
            self.assertIs(self.queue._worker_thread, worker)
            with self.assertRaises(RuntimeError):
                self.queue.start()
            self.assertTrue(self.queue._stop_event.is_set())
            with self.assertRaises(RuntimeError):
                self.queue.bind_downloader(_Downloader(1))
            self.module.configer.PLUGIN_CONFIG_PATH = self.root / "new"
            with self.assertRaises(RuntimeError):
                self.queue.bind_downloader(self.downloader)
            self.assertIs(self.queue._downloader, self.downloader)
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertIs(self.queue.stop(), True)
        replacement = _Downloader(1)
        self.queue.bind_downloader(replacement)
        self.assertIs(self.queue._downloader, replacement)
        self.assertEqual(
            self.queue._get_persist_path(),
            (self.root / "new/share_audit_download_queue.json").resolve(),
        )

    def test_stopped_path_switch_preserves_old_queue_and_loads_new_path(self) -> None:
        """
        正常停止后切换目录不复制旧任务且能重新恢复原目录
        """
        task = deepcopy(self._enqueue())
        old_path = self.queue._get_persist_path()
        original_bytes = old_path.read_bytes()
        self.assertTrue(self.queue.stop())
        self.module.configer.PLUGIN_CONFIG_PATH = self.root / "new"
        self.queue.bind_downloader(_Downloader(1))
        self.assertEqual(self.queue.pending_item_count(), 0)
        self.assertEqual(old_path.read_bytes(), original_bytes)
        self.module.configer.PLUGIN_CONFIG_PATH = self.root / "old"
        self.queue.bind_downloader(_Downloader(1))
        with patch.object(self.module, "Thread") as thread:
            thread.return_value.is_alive.return_value = False
            self.queue.start()
        self.assertEqual(self.queue.pending_item_count(), 1)
        self.assertEqual(self.queue._tasks[task["task_id"]], task)

    def test_worker_self_stop_during_external_join(self) -> None:
        """
        审核下载回调请求停止时不与外部停止线程互相等待
        """
        entered, joining = Event(), Event()
        results = []
        original = self.downloader.batch_auto_share_downloader

        def download(items):
            entered.set()
            if not joining.wait(timeout=5):
                raise AssertionError("外部停止未开始等待")
            results.append(self.queue.stop())
            return original(items)

        self.downloader.batch_auto_share_downloader = download
        self._enqueue()["next_retry_at"] = 0
        self.queue._save_tasks_locked()
        self.queue.start()
        worker = self.queue._worker_thread
        join = worker.join

        def external_join(timeout):
            joining.set()
            join(timeout=2)

        try:
            self.assertTrue(entered.wait(timeout=5))
            with patch.object(worker, "join", side_effect=external_join):
                self.assertTrue(self.queue.stop())
            self.assertEqual(results, [False])
            self.assertFalse(worker.is_alive())
        finally:
            joining.set()
            self.queue.stop()

    def test_service_propagates_audit_stop_failure_before_patch_teardown(self) -> None:
        """
        服务层在审核任务未退出时保留整理补丁和任务管理器
        """
        audit = MagicMock()
        audit.stop.return_value = False
        patcher = MagicMock()
        namespace = {
            "logger": MagicMock(),
            "share_audit_download_queue": audit,
            "directory_upload_stability_tracker": MagicMock(),
            "directory_upload_queue": MagicMock(),
            "emby_mediainfo_queue": MagicMock(),
            "sync_del_webhook_queue": MagicMock(),
            "TransferChainPatcher": patcher,
        }
        stop = _method(self.plugin_root / "service/__init__.py", "stop", namespace)
        manager = MagicMock()
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[],
            monitor_life_lock=Lock(),
            monitor_life_thread=None,
            monitorlife=None,
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=None,
            monitor_stop_event=None,
            fuse_manager=None,
            redirect=None,
            transfer_task_manager=manager,
            transfer_handler=object(),
        )
        self.assertIs(stop(service), False)
        patcher.disable.assert_not_called()
        manager.shutdown.assert_not_called()
        audit.stop.return_value = True
        self.assertIs(stop(service), True)
        patcher.disable.assert_called_once()
        manager.shutdown.assert_called_once()

    def test_service_retains_unfinished_watchers_and_life_monitor(self) -> None:
        """
        超时的目录和生活事件线程保留句柄且阻止资源销毁
        """
        namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
            )
        }
        path = self.plugin_root / "service/__init__.py"
        stop = _method(path, "stop", namespace)
        stop_life = _method(path, "_stop_monitor_life_internal", namespace)
        watcher = SimpleNamespace(
            thread=MagicMock(), stop_event=Event(), mon_path="test"
        )
        watcher.thread.is_alive.return_value = True
        life = MagicMock()
        life.is_alive.return_value = True
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[watcher],
            monitor_life_lock=Lock(),
            monitor_life_thread=life,
            monitorlife=None,
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=None,
            monitor_stop_event=Event(),
            fuse_manager=None,
            redirect=None,
            transfer_task_manager=None,
            transfer_handler=None,
        )
        service._stop_monitor_life_internal = lambda: stop_life(service)
        self.assertIs(stop(service), False)
        self.assertEqual(service.service_observer, [watcher])
        self.assertIs(service.monitor_life_thread, life)
        self.assertTrue(service.monitor_stop_event.is_set())
        namespace["TransferChainPatcher"].disable.assert_not_called()
        watcher.thread.is_alive.return_value = False
        life.is_alive.return_value = False
        self.assertIs(stop(service), True)
        self.assertEqual(service.service_observer, [])
        self.assertIsNone(service.monitor_life_thread)
        self.assertIsNone(service.monitor_stop_event)

    def test_service_preserves_manager_on_shutdown_exception(self) -> None:
        """
        整理任务管理器关闭异常时保留对象供后续关闭重试
        """
        namespace = {
            name: MagicMock()
            for name in (
                "logger",
                "directory_upload_stability_tracker",
                "directory_upload_queue",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
                "share_audit_download_queue",
                "TransferChainPatcher",
            )
        }
        stop = _method(self.plugin_root / "service/__init__.py", "stop", namespace)
        manager = MagicMock()
        manager.shutdown.side_effect = [OSError("failure"), None]
        service = SimpleNamespace(
            _stop_sync_operations=MagicMock(return_value=True),
            backup_service=MagicMock(),
            service_observer=[],
            monitor_life_lock=Lock(),
            monitor_life_thread=None,
            monitorlife=None,
            share_interactive_gen_strm_queue=MagicMock(),
            sharetransferhelper=None,
            monitor_stop_event=None,
            fuse_manager=None,
            redirect=None,
            transfer_task_manager=manager,
            transfer_handler=object(),
        )
        self.assertIs(stop(service), False)
        self.assertIs(service.transfer_task_manager, manager)
        self.assertIs(stop(service), True)
        self.assertIsNone(service.transfer_task_manager)

    def _plugin_stop(self):
        namespace = {
            name: MagicMock()
            for name in (
                "servicer",
                "ct_db_manager",
                "U115Patcher",
                "P115DiskPatcher",
                "AppVerPatcher",
                "upload_notifier",
            )
        }
        method = _method(self.plugin_root / "__init__.py", "stop_service", namespace)
        plugin_type = type(
            "Plugin",
            (),
            {
                "stop_service": method,
                "_rename_media_fields_cache": MagicMock(),
            },
        )
        return plugin_type(), namespace

    def test_plugin_stop_preserves_resources_until_queue_exits(self) -> None:
        """
        插件入口未停止完成时不关闭数据库或清除在途资源
        """
        plugin, namespace = self._plugin_stop()
        namespace["servicer"].stop.return_value = False
        self.assertIs(plugin.stop_service(), False)
        plugin._rename_media_fields_cache.clear.assert_not_called()
        namespace["ct_db_manager"].close_database.assert_not_called()
        namespace["upload_notifier"].shutdown.assert_not_called()
        namespace["U115Patcher"].assert_not_called()
        namespace["servicer"].stop.return_value = True
        self.assertIs(plugin.stop_service(), True)
        namespace["ct_db_manager"].close_database.assert_called_once()
        namespace["upload_notifier"].shutdown.assert_called_once_with(plugin)

    def test_host_quiesce_retries_unfinished_plugin_hook(self) -> None:
        """
        真实 V3 分阶段关闭合同保留失败钩子并在下次重试
        """
        host = Path(
            os.environ.get(
                "MOVIEPILOT_SOURCE", self.plugin_root.parents[2] / "MoviePilot"
            )
        )
        path = host / "app/runtime/extensions/plugin/lifecycle.py"
        if not path.exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        quiesce = _method(path, "_quiesce_hooks", {})
        plugin, namespace = self._plugin_stop()
        namespace["servicer"].stop.side_effect = [False, True]
        lifecycle = SimpleNamespace(_quiesced_hooks={}, _logger=MagicMock())
        self.assertIs(quiesce(lifecycle, {"P115StrmHelper": plugin}), False)
        self.assertNotIn("stop_service", lifecycle._quiesced_hooks["P115StrmHelper"])
        self.assertIs(quiesce(lifecycle, {"P115StrmHelper": plugin}), True)
        self.assertIn("stop_service", lifecycle._quiesced_hooks["P115StrmHelper"])
        namespace["ct_db_manager"].close_database.assert_called_once()

    def test_config_api_validates_then_stops_before_publishing(self) -> None:
        """
        配置接口先校验且审核未停完时不发布或持久化新配置
        """
        for valid, stopped, saved in (
            (False, True, True),
            (True, False, True),
            (True, True, False),
            (True, True, True),
        ):
            with self.subTest(valid=valid, stopped=stopped, saved=saved):
                events = []
                config = MagicMock()
                config.validate_updates.side_effect = lambda data: (
                    events.append("validate") or valid
                )
                config.update_config.side_effect = lambda data: (
                    events.append("publish") or True
                )
                config.update_plugin_config.side_effect = lambda: (
                    events.append("save") or saved
                )
                namespace = {
                    "configer": config,
                    "i18n": MagicMock(),
                    "sentry_manager": MagicMock(),
                    "to_thread": asyncio.to_thread,
                }
                method = _method(
                    self.plugin_root / "__init__.py", "_save_config_api", namespace
                )
                plugin = SimpleNamespace(
                    stop_service=MagicMock(
                        side_effect=lambda: events.append("stop") or stopped
                    ),
                    init_plugin=MagicMock(
                        side_effect=lambda **kwargs: events.append("init")
                    ),
                    get_config=MagicMock(return_value={}),
                )
                result = asyncio.run(
                    method(
                        plugin,
                        SimpleNamespace(
                            json=AsyncMock(return_value={"cookies": "new"})
                        ),
                    )
                )
                if not valid:
                    self.assertEqual(events, ["validate"])
                elif not stopped:
                    self.assertEqual(events, ["validate", "stop"])
                elif not saved:
                    self.assertEqual(events, ["validate", "stop", "publish", "save"])
                else:
                    self.assertEqual(
                        events, ["validate", "stop", "publish", "save", "init"]
                    )
                self.assertEqual(
                    result["code"], 0 if valid and stopped and saved else 1
                )
