from pathlib import Path
from subprocess import CalledProcessError, TimeoutExpired
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread, current_thread
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from test_v3_share_queue_lifecycle import _method
from test_v3_worker_queue import _compile


class TestV3FuseLifecycle(TestCase):
    """
    隔离挂载命令并验证真实 FUSE 服务线程的关停合同
    """

    def setUp(self) -> None:
        """
        加载真实管理器和 worker 并禁止外部挂载调用
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.mountpoint = temporary.name
        self.root = Path(__file__).resolve().parents[1]
        path = self.root / "service/fuse/__init__.py"
        self.entered = Event()
        self.release = Event()
        self.operations = SimpleNamespace(run_forever=self._run_forever)
        self.factory = MagicMock(return_value=self.operations)
        namespace = {
            "Lock": Lock,
            "Thread": Thread,
            "current_thread": current_thread,
            "Path": Path,
            "logger": MagicMock(),
            "system": lambda: "Darwin",
            "run": MagicMock(side_effect=AssertionError("禁止真实挂载命令")),
            "getuid": lambda: 0,
            "getgid": lambda: 0,
            "CalledProcessError": CalledProcessError,
            "TimeoutExpired": TimeoutExpired,
            "P115FuseOperations": self.factory,
            "configer": SimpleNamespace(
                fuse_enabled=True,
                fuse_mountpoint=self.mountpoint,
                fuse_uid=0,
                fuse_gid=0,
                fuse_readdir_ttl=60,
            ),
        }
        _method(path, "_get_fuse_error_message", namespace)
        _method(path, "fuse_thread_worker", namespace)
        cls = _compile(path, namespace, "FuseManager")
        self.manager = cls(client=object())
        self.manager._unmount_fuse = MagicMock()
        self.manager._unmount_fuse_lazy = MagicMock()
        self.addCleanup(self._cleanup)

    def _run_forever(self, **kwargs) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("测试未释放 FUSE 线程")

    def _cleanup(self) -> None:
        self.release.set()
        self.manager.stop_fuse()

    def _start(self) -> Thread:
        self.assertTrue(self.manager.start_fuse())
        self.assertTrue(self.entered.wait(timeout=5))
        return self.manager.fuse_thread

    def test_timeout_preserves_mount_and_rejects_replacement(self) -> None:
        """
        卸载未结束时保留线程和挂载对象，重挂不能覆盖旧实例
        """
        worker = self._start()
        join = worker.join
        with patch.object(worker, "join", side_effect=lambda timeout: join(0)):
            self.assertFalse(self.manager.stop_fuse())
            self.assertFalse(self.manager.start_fuse())
        self.assertIs(self.manager.fuse_thread, worker)
        self.assertIs(self.manager.fuse_operations, self.operations)
        self.assertEqual(self.manager.fuse_mountpoint, self.mountpoint)
        self.factory.assert_called_once()
        self.release.set()
        self.assertTrue(self.manager.stop_fuse())
        self.assertIsNone(self.manager.fuse_thread)
        self.assertIsNone(self.manager.fuse_operations)
        self.assertIsNone(self.manager.fuse_mountpoint)

    def test_failed_unmount_keeps_retryable_handle(self) -> None:
        """
        普通和懒卸载均失败时不丢弃仍存活的线程
        """
        worker = self._start()
        self.manager._unmount_fuse.side_effect = OSError("busy")
        self.manager._unmount_fuse_lazy.side_effect = OSError("busy")
        join = worker.join
        with patch.object(worker, "join", side_effect=lambda timeout: join(0)):
            self.assertFalse(self.manager.stop_fuse())
        self.assertIs(self.manager.fuse_thread, worker)
        self.manager._unmount_fuse_lazy.assert_called_once_with(self.mountpoint)
        self.release.set()
        self.assertTrue(self.manager.stop_fuse())

    def test_normal_stop_and_repeated_stop_are_successful(self) -> None:
        """
        正常退出后重复停止成功且不再发出卸载命令
        """
        self._start()
        self.manager._unmount_fuse.side_effect = lambda mountpoint: self.release.set()
        self.assertTrue(self.manager.stop_fuse())
        self.assertTrue(self.manager.stop_fuse())
        self.manager._unmount_fuse.assert_called_once_with(self.mountpoint)

    def test_api_propagates_unfinished_stop_and_later_success(self) -> None:
        """
        真实服务和卸载 API 不把超时报告为成功，后续退出可重试
        """
        worker = self._start()
        service = SimpleNamespace(fuse_manager=self.manager)
        stop_fuse = _method(self.root / "service/__init__.py", "stop_fuse", {})
        service.stop_fuse = MethodType(stop_fuse, service)
        unmount = _method(
            self.root / "api.py",
            "fuse_unmount_api",
            {
                "servicer": service,
                "ApiResponse": SimpleNamespace,
                "logger": MagicMock(),
            },
        )
        join = worker.join
        with patch.object(worker, "join", side_effect=lambda timeout: join(0)):
            response = unmount()
        self.assertEqual(response.code, -1)
        self.assertIn("尚未退出", response.msg)
        self.release.set()
        self.assertEqual(unmount().code, 0)
        service.fuse_manager = None
        self.assertEqual(unmount().code, 0)

    def test_service_stop_keeps_resources_when_fuse_is_running(self) -> None:
        """
        FUSE 未退出时服务 stop 返回失败且保留整理补丁
        """
        worker = self._start()
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
        stop = _method(self.root / "service/__init__.py", "stop", namespace)
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
            fuse_manager=self.manager,
            redirect=None,
            transfer_task_manager=None,
            transfer_handler=None,
        )
        join = worker.join
        with patch.object(worker, "join", side_effect=lambda timeout: join(0)):
            self.assertFalse(stop(service))
        namespace["TransferChainPatcher"].disable.assert_not_called()
        self.release.set()
        self.assertTrue(stop(service))
        namespace["TransferChainPatcher"].disable.assert_called_once()
