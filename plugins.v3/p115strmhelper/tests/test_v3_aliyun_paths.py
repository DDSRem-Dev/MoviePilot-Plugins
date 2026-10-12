import __future__
import ast
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from json import dumps, loads
from logging import ERROR
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from typing import Any, Optional
from unittest import TestCase
from unittest.mock import MagicMock, patch


class TestV3AliyunPaths(TestCase):
    """
    使用真实 Aligo 验证分身登录文件加载及刷新写入的目录归属
    """

    def setUp(self) -> None:
        """
        隔离第三方默认目录、日志配置与全部网络，仅保留真实文件加载和保存
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = Path(__file__).resolve().parents[1]
        with patch.object(Path, "home", return_value=self.directory):
            self.aligo = importlib.import_module("aligo")
        self.auth_module = importlib.import_module("aligo.core.Auth")
        api_module = importlib.import_module("aligo.apis.Aligo")
        self.global_directory = self.directory / "global"
        self.global_directory.mkdir()
        for module in (self.auth_module, api_module):
            self.enterContext(
                patch.object(module, "aligo_config_folder", self.global_directory)
            )
        self.enterContext(patch("coloredlogs.install"))
        self.network = self.enterContext(
            patch(
                "requests.Session.request",
                side_effect=AssertionError("测试禁止网络请求"),
            )
        )
        spec = importlib.util.spec_from_file_location(
            "_p115_aliyun_paths", self.root / "core/aliyunpan.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.client_type = module.BAligo
        self.enterContext(
            patch.object(
                self.client_type,
                "v2_user_get",
                return_value=SimpleNamespace(resource_drive_id="resource"),
            )
        )
        self.clients = []

        def close() -> None:
            for client in self.clients:
                client._session.close()

        self.addCleanup(close)

    def _token(self, directory: Path, identity: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "aligo.json"
        path.write_text(
            dumps(
                {
                    "refresh_token": identity,
                    "access_token": "test-access",
                    "user_id": identity,
                    "x_device_id": "test-device",
                }
            )
        )
        return path

    def _service(
        self,
        directory: Path,
        token: Optional[str],
        barrier: Optional[Barrier] = None,
    ) -> Any:
        tree = ast.parse((self.root / "service/__init__.py").read_text())
        cls = next(
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "ServiceHelper"
        )
        cls.bases, cls.decorator_list = [], []
        cls.body = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "init_service"
        ]
        values = {
            "plugin_aligo_path": directory,
            "aliyundrive_token": token,
            "cookies": "unused-cookie",
        }
        config = SimpleNamespace(
            cookies="unused-cookie",
            get_config=lambda key: values.get(key),
            get_default_timeout=lambda: None,
            get_slow_timeout=lambda: None,
            fuse_enabled=False,
            share_audit_queue_enabled=False,
        )

        def client(**kwargs: Any) -> Any:
            if barrier is not None:
                barrier.wait(timeout=3)
            value = self.client_type(**kwargs)
            self.clients.append(value)
            return value

        namespace = {
            name: MagicMock()
            for name in (
                "create_client",
                "logger",
                "MediaInfoDownloader",
                "BackupService",
                "share_audit_download_queue",
                "MonitorLife",
                "ShareTransferHelper",
                "OfflineDownloadHelper",
                "Redirect",
                "FuseManager",
                "WebdavCore",
                "emby_mediainfo_queue",
                "sync_del_webhook_queue",
            )
        }
        namespace.update(
            {"configer": config, "Path": Path, "ERROR": ERROR, "BAligo": client}
        )
        exec(
            compile(
                ast.Module(body=[cls], type_ignores=[]),
                "service.py",
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        service = namespace[cls.name]()
        service._stop_sync_operations = MagicMock(return_value=True)
        service._sync_condition = MagicMock()
        service.aligo = None
        service.share_interactive_gen_strm_queue = MagicMock()
        service.backup_service = MagicMock()
        service._init_transfer_enhancement = MagicMock()
        return service

    def test_existing_login_files_are_loaded_from_each_instance(self) -> None:
        """
        真实库读取各实例原文件，默认目录的其他账号文件不参与登录
        """
        self._token(self.global_directory, "global")
        for identity in ("main", "clone"):
            directory = self.directory / identity / "aligo"
            path = self._token(directory, identity)
            before = path.read_bytes()
            service = self._service(directory, identity)
            self.assertTrue(service.init_service())
            self.assertEqual(service.aligo._auth._name, path)
            self.assertEqual(service.aligo._auth.token.user_id, identity)
            self.assertEqual(service.aligo.default_drive_id, "resource")
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.auth_module.aligo_config_folder, self.global_directory)
        self.network.assert_not_called()

    def test_refresh_login_creates_only_the_current_instance_file(self) -> None:
        """
        新 token 登录复用真实保存逻辑，仅创建本实例登录文件
        """

        def refresh(auth: Any, token: str) -> None:
            auth.token = self.aligo.Token(refresh_token=token, user_id=token)
            auth._save()

        directory = self.directory / "clone/aligo"
        service = self._service(directory, "new-token")
        with patch.object(self.auth_module.Auth, "_refresh_token", refresh):
            self.assertTrue(service.init_service())
        self.assertEqual(
            loads((directory / "aligo.json").read_text())["refresh_token"], "new-token"
        )
        self.assertFalse((self.global_directory / "aligo.json").exists())
        self.network.assert_not_called()

    def test_concurrent_initialization_and_later_save_preserve_file_ownership(
        self,
    ) -> None:
        """
        两实例同时构造并在第三方全局目录变化后保存，仍各写原登录文件
        """
        barrier = Barrier(2)
        services = []
        paths = []
        for identity in ("a", "b"):
            directory = self.directory / identity
            paths.append(self._token(directory, identity))
            services.append(self._service(directory, identity, barrier))
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(
                list(executor.map(lambda service: service.init_service(), services)),
                [True, True],
            )
        alternate = self.directory / "unrelated"
        alternate.mkdir()
        with patch.object(self.auth_module, "aligo_config_folder", alternate):
            for index, service in enumerate(services):
                service.aligo._auth.token.refresh_token = f"refreshed-{index}"
                service.aligo._auth._save()
        for index, path in enumerate(paths):
            self.assertEqual(
                loads(path.read_text())["refresh_token"], f"refreshed-{index}"
            )
        self.assertFalse((alternate / "aligo.json").exists())
        self.network.assert_not_called()

    def test_no_configured_token_does_not_create_login_directory_or_client(
        self,
    ) -> None:
        """
        未配置阿里登录时继续初始化其他服务，不创建登录文件
        """
        directory = self.directory / "disabled/aligo"
        service = self._service(directory, None)
        self.assertTrue(service.init_service())
        self.assertIsNone(service.aligo)
        self.assertFalse(directory.exists())
        self.assertFalse(self.clients)

    def test_invalid_login_file_does_not_overwrite_another_instance(self) -> None:
        """
        单实例登录文件损坏时沿用原失败降级，其他实例文件不变
        """
        healthy = self._token(self.directory / "healthy", "healthy")
        before = healthy.read_bytes()
        bad = self.directory / "bad"
        bad.mkdir()
        (bad / "aligo.json").write_text("{bad")
        service = self._service(bad, "configured")
        self.assertTrue(service.init_service())
        self.assertIsNone(service.aligo)
        self.assertEqual(healthy.read_bytes(), before)
        self.network.assert_not_called()
