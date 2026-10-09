"""
MediaWarp 配置恢复、原子安装和启动异常回归测试
"""

import importlib.util
import io
import stat
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import Mock, patch

from ruamel.yaml import YAML


def _load_plugin(root: Path) -> ModuleType:
    source = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("mediawarp_under_test", source)
    module = importlib.util.module_from_spec(spec)
    host_modules = {
        name: ModuleType(name)
        for name in (
            "app",
            "app.core",
            "app.core.config",
            "app.helper",
            "app.helper.mediaserver",
            "app.log",
            "app.plugins",
        )
    }
    host_modules["app.core.config"].settings = SimpleNamespace(
        PLUGIN_DATA_PATH=root, PROXY=None, TZ="UTC"
    )
    host_modules["app.helper.mediaserver"].MediaServerHelper = Mock()
    host_modules["app.log"].logger = Mock()
    host_modules["app.plugins"]._PluginBase = object
    with patch.dict(sys.modules, host_modules):
        spec.loader.exec_module(module)
    return module


class TestMediaWarpPersistence(TestCase):
    """
    使用真实文件和 YAML 验证故障时原文件保持完整
    """

    def setUp(self) -> None:
        """
        创建独立的插件目录并隔离 MoviePilot 宿主依赖
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.module = _load_plugin(self.root)
        self.plugin = self.module.MediaWarp()
        self.config = self.root / "mediawarp/config/config.yaml"
        self.config.parent.mkdir(parents=True)
        self.binary = self.root / "mediawarp/MediaWarp"
        self.binary.write_bytes(b"old binary")
        self.binary.chmod(0o755)
        self.version = self.root / "mediawarp/version.txt"
        self.plugin._port = 9000
        self.plugin._emby_host = "http://emby:8096"
        self.plugin._emby_apikey = "test-key"
        self.plugin._media_strm_path = "/media\n/movies"

    def _modify(self) -> None:
        self.plugin._MediaWarp__modify_config(
            self.config,
            {"Port": 9000, "Logger.AccessLogger.File": True},
        )

    def _assert_no_temporary_files(self) -> None:
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def _archive_response(self, include_binary: bool = True) -> Mock:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            entries = {"config.yaml.example": b"Port: 8000\n"}
            if include_binary:
                entries["MediaWarp"] = b"new binary"
            for name, content in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        response = Mock()
        response.iter_content.return_value = [buffer.getvalue()]
        return response

    def test_empty_and_missing_config_can_start(self) -> None:
        """
        空文件和缺失文件均可恢复启动所需的插件配置
        """
        for content in (None, "", "# empty\n", "null\n"):
            with self.subTest(content=content):
                self.config.unlink(missing_ok=True)
                if content is not None:
                    self.config.write_text(content, encoding="utf-8")
                self.module.logger.reset_mock()
                with patch.object(self.module.psutil, "Popen") as popen:
                    popen.return_value.is_running.return_value = True
                    self.plugin._MediaWarp__run_service()
                    popen.assert_called_once_with([self.binary])
                config = YAML().load(self.config)
                self.assertEqual(config["Port"], 9000)
                self.assertEqual(config["MediaServer"]["ADDR"], "http://emby:8096")
                self.assertEqual(config["MediaServer"]["AUTH"], "test-key")
                self.assertEqual(
                    config["HTTPStrm"]["PrefixList"], ["/media", "/movies"]
                )
                self.assertTrue(config["Logger"]["AccessLogger"]["File"])
                self.module.logger.warning.assert_called_once()
                self.module.logger.info.assert_called_with("MediaWarp 服务成功启动！")
                self._assert_no_temporary_files()

    def test_valid_config_retains_custom_settings_and_mode(self) -> None:
        """
        更新插件选项时保留自定义配置、注释、引号和文件权限
        """
        self.config.write_text(
            '# custom\nCustom: "keep"\nPort: 8000\n'
            "Logger:\n  AccessLogger:\n    Console: True\n",
            encoding="utf-8",
        )
        self.config.chmod(0o640)
        self._modify()
        content = self.config.read_text(encoding="utf-8")
        self.assertIn('# custom\nCustom: "keep"', content)
        config = YAML().load(content)
        self.assertEqual(config["Port"], 9000)
        self.assertTrue(config["Logger"]["AccessLogger"]["Console"])
        self.assertTrue(config["Logger"]["AccessLogger"]["File"])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self._assert_no_temporary_files()

    def test_null_sections_are_rebuilt(self) -> None:
        """
        空的嵌套节点可恢复为配置映射
        """
        for content in ("Logger: null\n", "Logger:\n  AccessLogger: null\n"):
            with self.subTest(content=content):
                self.config.write_text(content, encoding="utf-8")
                self._modify()
                self.assertTrue(
                    YAML().load(self.config)["Logger"]["AccessLogger"]["File"]
                )

    def test_corrupt_config_is_preserved_and_startup_error_is_logged(self) -> None:
        """
        YAML 语法或结构错误保留原配置并记录启动异常
        """
        for content in (
            "Port: [broken\n",
            "- item\n",
            "false\n",
            "42\n",
            "Logger: invalid\n",
            "Logger:\n  AccessLogger: []\n",
        ):
            with self.subTest(content=content):
                self.config.write_text(content, encoding="utf-8")
                self.module.logger.reset_mock()
                with patch.object(self.module.psutil, "Popen") as popen:
                    self.plugin._MediaWarp__run_service()
                    popen.assert_not_called()
                self.assertEqual(self.config.read_text(encoding="utf-8"), content)
                self.module.logger.error.assert_called_once()
                self.assertTrue(self.module.logger.error.call_args.kwargs["exc_info"])
                self.module.logger.info.assert_not_called()
                self._assert_no_temporary_files()

    def test_serialization_failure_preserves_original(self) -> None:
        """
        YAML 序列化中途失败不会截断原配置
        """
        original = b"Port: 8000\n"
        self.config.write_bytes(original)

        def fail_dump(data: Any, stream: Any) -> None:
            stream.write("Port:")
            raise OSError("disk full")

        with patch.object(self.module.YAML, "dump", side_effect=fail_dump):
            with self.assertRaises(OSError):
                self._modify()
        self.assertEqual(self.config.read_bytes(), original)
        self._assert_no_temporary_files()

    def test_sync_and_replace_failure_preserve_original(self) -> None:
        """
        落盘或原子替换失败时保留原文件并清理临时文件
        """
        original = b"Port: 8000\n"
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                self.config.write_bytes(original)
                with patch.object(
                    self.module.os, operation, side_effect=OSError(operation)
                ):
                    with self.assertRaises(OSError):
                        self._modify()
                self.assertEqual(self.config.read_bytes(), original)
                self._assert_no_temporary_files()

    def test_interrupted_write_preserves_original(self) -> None:
        """
        写入被中断时原文件保持完整
        """
        original = b"Port: 8000\n"
        self.config.write_bytes(original)
        with self.assertRaises(KeyboardInterrupt):
            with self.plugin._MediaWarp__atomic_write(self.config) as file:
                file.write("incomplete")
                file.flush()
                self.assertEqual(self.config.read_bytes(), original)
                raise KeyboardInterrupt
        self.assertEqual(self.config.read_bytes(), original)
        self._assert_no_temporary_files()

    def test_binary_copy_failure_preserves_old_executable(self) -> None:
        """
        二进制复制中断后旧程序仍完整且可执行
        """
        source = self.root / "new-binary"
        source.write_bytes(b"new binary")

        def fail_copy(source_file: Any, target_file: Any) -> None:
            target_file.write(source_file.read(3))
            raise OSError("disk full")

        with patch.object(self.module.shutil, "copyfileobj", side_effect=fail_copy):
            with self.assertRaises(OSError):
                self.plugin._MediaWarp__atomic_copy(source, self.binary)
        self.assertEqual(self.binary.read_bytes(), b"old binary")
        self.assertEqual(stat.S_IMODE(self.binary.stat().st_mode), 0o755)
        self._assert_no_temporary_files()

    def test_install_preserves_config_and_updates_executable_and_version(self) -> None:
        """
        安装更新保留用户配置并保存可执行权限及版本
        """
        self.config.write_bytes(b"Port: 9000\nCustom: keep\n")
        with patch.object(
            self.module.requests, "get", return_value=self._archive_response()
        ):
            self.plugin._MediaWarp__download_and_extract()
        self.assertEqual(self.binary.read_bytes(), b"new binary")
        self.assertEqual(stat.S_IMODE(self.binary.stat().st_mode), 0o755)
        self.assertEqual(self.config.read_bytes(), b"Port: 9000\nCustom: keep\n")
        self.assertEqual(self.version.read_text(), "0.1.12")
        self._assert_no_temporary_files()

    def test_first_install_saves_example_config(self) -> None:
        """
        首次安装原子保存示例配置
        """
        self.binary.unlink()
        with patch.object(
            self.module.requests, "get", return_value=self._archive_response()
        ):
            self.plugin._MediaWarp__download_and_extract()
        self.assertEqual(self.config.read_bytes(), b"Port: 8000\n")
        self.assertEqual(self.version.read_text(), "0.1.12")
        self._assert_no_temporary_files()

    def test_failed_install_preserves_binary_and_version(self) -> None:
        """
        安装替换失败不破坏旧二进制且不错误更新版本号
        """
        self.version.write_text("0.1.11", encoding="utf-8")
        with (
            patch.object(
                self.module.requests, "get", return_value=self._archive_response()
            ),
            patch.object(
                self.module.os, "replace", side_effect=OSError("replace failed")
            ),
        ):
            self.plugin._MediaWarp__download_and_extract()
        self.assertEqual(self.binary.read_bytes(), b"old binary")
        self.assertEqual(self.version.read_text(), "0.1.11")
        self.module.logger.error.assert_called_once()
        self.assertTrue(self.module.logger.error.call_args.kwargs["exc_info"])
        self._assert_no_temporary_files()

    def test_archive_without_binary_does_not_advance_version(self) -> None:
        """
        压缩包缺失程序时不标记安装成功
        """
        self.version.write_text("0.1.11", encoding="utf-8")
        with patch.object(
            self.module.requests, "get", return_value=self._archive_response(False)
        ):
            self.plugin._MediaWarp__download_and_extract()
        self.assertEqual(self.binary.read_bytes(), b"old binary")
        self.assertEqual(self.version.read_text(), "0.1.11")
        self.module.logger.error.assert_called_once()
        self._assert_no_temporary_files()

    def test_spawn_failure_is_logged(self) -> None:
        """
        二进制启动失败通过插件日志输出异常堆栈
        """
        self.config.write_text("Port: 8000\n", encoding="utf-8")
        with patch.object(
            self.module.psutil, "Popen", side_effect=OSError("exec failed")
        ):
            self.plugin._MediaWarp__run_service()
        self.module.logger.error.assert_called_once()
        self.assertTrue(self.module.logger.error.call_args.kwargs["exc_info"])
        self.module.logger.info.assert_not_called()

    def test_immediate_process_exit_is_logged(self) -> None:
        """
        进程立即退出时明确报错且不输出启动成功
        """
        self.config.write_text("Port: 8000\n", encoding="utf-8")
        with patch.object(self.module.psutil, "Popen") as popen:
            popen.return_value.is_running.return_value = False
            self.plugin._MediaWarp__run_service()
        self.module.logger.error.assert_called_once()
        self.module.logger.info.assert_not_called()
