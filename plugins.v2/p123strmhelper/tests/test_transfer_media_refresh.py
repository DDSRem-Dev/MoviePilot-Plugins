import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlencode


def _load_listener() -> Any:
    """
    提取当前版本的实际事件方法，隔离宿主启动及网络依赖
    """
    source_path = Path(__file__).resolve().parents[1] / "__init__.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "P123StrmHelper"
    )
    plugin.bases = []
    plugin.body = [
        node
        for node in plugin.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("has_prefix", "__get_media_path", "generate_strm")
    ]
    for method in plugin.body:
        if method.name == "generate_strm":
            method.decorator_list = []
    namespace = {
        "Path": Path,
        "Event": object,
        "ast": ast,
        "urlencode": urlencode,
        "settings": SimpleNamespace(API_TOKEN="test-token"),
        "logger": Mock(),
        "StorageChain": Mock(),
        "MediaInfoDownloader": Mock(),
        "SystemUtils": SimpleNamespace(is_bluray_dir=lambda path: False),
        "RefreshMediaItem": SimpleNamespace,
    }
    module = ast.fix_missing_locations(ast.Module(body=[plugin], type_ignores=[]))
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["P123StrmHelper"]()


class TestTransferMediaRefresh(TestCase):
    """
    验证整理回调的文件写入、路径映射和媒体服务器刷新
    """

    def setUp(self) -> None:
        """
        建立临时 STRM 目录和不访问外部服务的整理事件
        """
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.local_root = Path(directory.name) / "strm"
        self.server_root = Path("/server/media")
        self.service = Mock(spec=["refresh_library_by_items"])
        self.plugin = _load_listener()
        self.plugin.__dict__.update(
            _enabled=True,
            _transfer_monitor_enabled=True,
            _transfer_monitor_paths=f"{self.local_root}#/cloud",
            moviepilot_address="http://moviepilot.invalid",
            _client=None,
            _transfer_monitor_scrape_metadata_enabled=True,
            media_scrape_metadata=Mock(),
            _transfer_monitor_media_server_refresh_enabled=True,
            _transfer_mp_mediaserver_paths=f"{self.server_root}#{self.local_root}",
            service_infos={"test": SimpleNamespace(instance=self.service)},
        )
        file_info = {
            "FileName": "影片.mkv",
            "Size": 1234,
            "Etag": "test-md5",
            "S3KeyFlag": "test-key",
            "FileId": 123,
        }
        self.target = SimpleNamespace(
            storage="123云盘",
            path="/cloud/电影/影片.mkv",
            name="影片.mkv",
            basename="影片",
            pickcode=repr(file_info),
        )
        self.event = SimpleNamespace(
            event_data={
                "transferinfo": SimpleNamespace(
                    target_item=self.target,
                    target_diritem=SimpleNamespace(path="/cloud/电影"),
                ),
                "mediainfo": SimpleNamespace(
                    title="影片", year="2026", type="电影", category="电影"
                ),
                "meta": None,
            }
        )

    def _assert_generated_file(self, relative_path: Path) -> None:
        local_path = self.local_root / relative_path
        self.assertTrue(local_path.is_file())
        content = local_path.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith(
                "http://moviepilot.invalid/api/v1/plugin/P123StrmHelper/redirect_url?"
            )
        )
        self.assertIn("file_id=123", content)
        self.assertEqual(
            self.plugin.media_scrape_metadata.call_args.kwargs["path"], local_path
        )

    def _assert_refresh_path(self, expected_path: Path) -> None:
        self.service.refresh_library_by_items.assert_called_once()
        items = self.service.refresh_library_by_items.call_args.args[0]
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0].target_path, Path)
        self.assertEqual(items[0].target_path, expected_path)

    def test_maps_path_after_writing_local_strm(self) -> None:
        """
        本地写入与刮削成功后使用媒体服务器路径刷新
        """
        self.plugin.generate_strm(self.event)

        self._assert_generated_file(Path("电影/影片.strm"))
        self._assert_refresh_path(self.server_root / "电影/影片.strm")

    def test_unmapped_paths_keep_local_path(self) -> None:
        """
        未配置映射或未命中映射时保留原路径
        """
        for mapping in ("", "/server#/other", f"/server#{self.local_root}2"):
            with self.subTest(mapping=mapping):
                self.service.reset_mock()
                self.plugin._transfer_mp_mediaserver_paths = mapping

                self.plugin.generate_strm(self.event)

                self._assert_generated_file(Path("电影/影片.strm"))
                self._assert_refresh_path(self.local_root / "电影/影片.strm")

    def test_normalized_mapping_prefix(self) -> None:
        """
        配置包含重复斜杠和尾部斜杠时仍正确映射
        """
        self.plugin._transfer_mp_mediaserver_paths = (
            f"{self.server_root}/#{self.local_root.parent}//strm/"
        )

        self.plugin.generate_strm(self.event)

        self._assert_refresh_path(self.server_root / "电影/影片.strm")

    def test_preserves_repeated_prefix_in_subdirectories(self) -> None:
        """
        子目录包含相同路径文本时只转换根目录
        """
        relative_dir = Path("backup") / self.local_root.relative_to(
            self.local_root.anchor
        )
        self.target.path = str(Path("/cloud") / relative_dir / "影片.mkv")

        self.plugin.generate_strm(self.event)

        self._assert_generated_file(relative_dir / "影片.strm")
        self._assert_refresh_path(self.server_root / relative_dir / "影片.strm")

    def test_disabled_refresh_still_generates_strm(self) -> None:
        """
        关闭刷新后仍完成本地 STRM 生成
        """
        self.plugin._transfer_monitor_media_server_refresh_enabled = False

        self.plugin.generate_strm(self.event)

        self._assert_generated_file(Path("电影/影片.strm"))
        self.service.refresh_library_by_items.assert_not_called()

    def test_missing_service_still_generates_strm(self) -> None:
        """
        没有可用媒体服务器时跳过刷新
        """
        self.plugin.service_infos = {}

        self.plugin.generate_strm(self.event)

        self._assert_generated_file(Path("电影/影片.strm"))
        self.service.refresh_library_by_items.assert_not_called()

    def test_repeated_event_keeps_same_file_and_refresh_path(self) -> None:
        """
        重复派发事件时更新同一文件并保持刷新路径稳定
        """
        for _ in range(2):
            self.service.reset_mock()

            self.plugin.generate_strm(self.event)

            self._assert_generated_file(Path("电影/影片.strm"))
            self._assert_refresh_path(self.server_root / "电影/影片.strm")
        self.assertEqual(
            list(self.local_root.rglob("*.strm")),
            [self.local_root / "电影/影片.strm"],
        )
