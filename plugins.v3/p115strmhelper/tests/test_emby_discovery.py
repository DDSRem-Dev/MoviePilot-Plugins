import ast
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath, PureWindowsPath
from queue import Queue
from threading import Event, Lock, Thread, current_thread
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _load_class(path: Path, name: str, namespace: Dict[str, Any]) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    node.decorator_list = []
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def _load_scan() -> Any:
    path = Path(__file__).resolve().parents[1] / "helper/mediaserver/scan.py"
    spec = importlib.util.spec_from_file_location("_emby_discovery_scan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response(status: int, data: Any = None) -> MagicMock:
    response = MagicMock(status_code=status)
    response.__enter__.return_value = response
    response.__bool__.return_value = status < 400
    response.json.return_value = data
    return response


class TestEmbyDiscovery(TestCase):
    """
    使用真实业务方法验证文件发现请求、失败传播和媒体信息补发现
    """

    def setUp(self) -> None:
        """
        隔离宿主、网络和计时，保留实际刷新及提取控制流
        """
        self.root = Path(__file__).resolve().parents[1]
        self.requests = MagicMock()
        self.requests.post_res.return_value = _response(204)
        self.requests.get_res.return_value = _response(200, {"Items": []})
        self.server = MagicMock()
        self.server.is_inactive.return_value = False
        self.server.refresh_root_library.return_value = True
        self.service = SimpleNamespace(
            type="emby",
            instance=self.server,
            config=SimpleNamespace(
                config={"host": "http://emby.invalid/", "apikey": "test-key"}
            ),
        )
        self.services = {"Emby": self.service}
        self.directory = MagicMock()
        self.directory.get_service.side_effect = lambda **kwargs: self.services.get(
            kwargs["name"]
        )
        self.directory.get_services.side_effect = lambda **kwargs: dict(self.services)
        self.scan = _load_scan()
        self.scan.sleep = MagicMock()
        self.clock = 0
        self.namespace = {
            "__name__": "_emby_discovery.refresh",
            "__package__": "_emby_discovery",
            "Path": Path,
            "PurePosixPath": PurePosixPath,
            "PureWindowsPath": PureWindowsPath,
            "Event": Event,
            "monotonic": lambda: self.clock,
            "logger": MagicMock(),
            "MediaServerHelper": lambda: self.directory,
            "MpMediaServerHelper": lambda: self.directory,
            "RequestUtils": lambda: self.requests,
            "library_scan": self.scan.library_scan,
            "P115Center": MagicMock(),
            "configer": MagicMock(),
            "__file__": str(self.root / "helper/mediaserver/emby.py"),
            "PathUtils": MagicMock(),
            "MetaInfoPath": MagicMock(),
            "MediaChain": lambda: SimpleNamespace(
                recognize_media=lambda **kwargs: None
            ),
            "RefreshMediaItem": lambda **kwargs: SimpleNamespace(**kwargs),
        }
        emby_path = self.root / "helper/mediaserver/emby.py"
        self.operate_type = _load_class(emby_path, "EmbyOperate", self.namespace)
        self.operate = self.operate_type("test")
        self.info_type = _load_class(emby_path, "EmbyMediaInfoOperate", self.namespace)
        emby = ModuleType("_emby_discovery.emby")
        emby.EmbyOperate = lambda **kwargs: self.operate
        modules = patch.dict(sys.modules, {emby.__name__: emby})
        modules.start()
        self.addCleanup(modules.stop)
        refresh_type = _load_class(
            self.root / "helper/mediaserver/refresh.py",
            "MediaServerRefresh",
            self.namespace,
        )
        self.refresh = refresh_type("test", enabled=True, mediaservers=["Emby"])

    def _info(self) -> Any:
        info = self.info_type("test", mediaservers=["Emby"])
        info.emby_operate = MagicMock()
        info.emby_operate.get_item_id_by_path.return_value = None
        info.emby_operate.notify_media_updated.return_value = True
        info._stop_event = MagicMock()
        info._stop_event.is_set.return_value = False

        def wait(seconds: float) -> bool:
            self.clock += seconds
            return False

        info._stop_event.wait.side_effect = wait
        return info

    def test_unrecognized_file_never_queries_or_refreshes_parent(self) -> None:
        """
        仅父级库已入库时仍直接通知文件路径，不寻找或完整刷新父目录
        """
        self.requests.get_res.return_value = _response(
            200, {"Items": [{"Path": "/media/Movies", "Id": "library-root"}]}
        )
        path = "/media/Movies/新电影/unknown.strm"
        self.assertTrue(self.refresh.refresh_mediaserver(path))
        self.requests.post_res.assert_called_once_with(
            url="http://emby.invalid/emby/Library/Media/Updated",
            params={"api_key": "test-key"},
            json={"Updates": [{"Path": path, "UpdateType": "Created"}]},
        )
        self.requests.get_res.assert_not_called()
        self.server.refresh_root_library.assert_not_called()

    def test_unsupported_endpoint_uses_plain_library_scan(self) -> None:
        """
        明确不支持通知接口时回退普通扫描，正确处理假值错误响应
        """
        for status in (404, 405, 501):
            with self.subTest(status=status):
                self.requests.post_res.return_value = _response(status)
                self.assertTrue(
                    self.operate.notify_media_updated("Emby", "/movies/new.strm")
                )
        self.assertEqual(self.server.refresh_root_library.call_count, 3)
        self.assertTrue(
            all(
                "/Library/Media/Updated" in c.kwargs["url"]
                for c in self.requests.post_res.call_args_list
            )
        )

    def test_request_errors_never_expand_into_library_scan(self) -> None:
        """
        权限、服务端错误和无响应均失败，不自动扩大扫描范围
        """
        for status in (400, 401, 403, 429, 500, 503, None):
            with self.subTest(status=status):
                self.requests.post_res.return_value = (
                    _response(status) if status else None
                )
                self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))
        self.server.refresh_root_library.assert_not_called()

    def test_network_exception_and_scan_failure_are_reported(self) -> None:
        """
        网络异常、普通扫描失败及异常不会被报告为成功
        """
        self.requests.post_res.side_effect = TimeoutError
        self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))
        self.requests.post_res.side_effect = None
        self.requests.post_res.return_value = _response(404)
        self.server.refresh_root_library.return_value = False
        self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))
        self.server.refresh_root_library.side_effect = RuntimeError
        self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))

    def test_invalid_path_or_missing_service_does_not_submit(self) -> None:
        """
        相对路径、空路径或消失的服务均不会提交请求
        """
        for path in ("", "relative.strm", "C:relative.strm"):
            self.assertFalse(self.operate.notify_media_updated("Emby", path))
        self.assertFalse(
            self.operate.notify_media_updated("missing", "/movies/new.strm")
        )
        self.requests.post_res.assert_not_called()

    def test_remote_absolute_paths_are_independent_of_host_platform(self) -> None:
        """
        本机路径规则不影响远端 POSIX、Windows 盘符和 UNC 绝对路径
        """
        for local_path_type in (PurePosixPath, PureWindowsPath):
            with patch.dict(self.namespace, {"Path": local_path_type}):
                for path in (
                    "/movies/新电影.strm",
                    r"D:\Movies\新电影.strm",
                    r"\\server\Movies\新电影.strm",
                ):
                    with self.subTest(host=local_path_type.__name__, path=path):
                        self.requests.post_res.reset_mock()
                        self.assertTrue(self.operate.notify_media_updated("Emby", path))
                        self.requests.post_res.assert_called_once()
                        self.assertEqual(
                            self.requests.post_res.call_args.kwargs["json"],
                            {"Updates": [{"Path": path, "UpdateType": "Created"}]},
                        )
                for path in (
                    "",
                    "relative.strm",
                    "C:relative.strm",
                    r"\Movies\new.strm",
                ):
                    with self.subTest(host=local_path_type.__name__, path=path):
                        self.requests.post_res.reset_mock()
                        self.assertFalse(
                            self.operate.notify_media_updated("Emby", path)
                        )
                        self.requests.post_res.assert_not_called()

    def test_windows_paths_and_reverse_proxy_prefix_are_preserved(self) -> None:
        """
        保留 Windows 路径、Unicode 和反向代理地址前缀
        """
        self.service.config.config["host"] = "https://emby.invalid/prefix"
        path = r"D:\Movies\新电影\new.strm"
        self.assertTrue(self.operate.notify_media_updated("Emby", path))
        self.assertEqual(
            self.requests.post_res.call_args.kwargs["url"],
            "https://emby.invalid/prefix/emby/Library/Media/Updated",
        )
        self.assertEqual(
            self.requests.post_res.call_args.kwargs["json"]["Updates"][0]["Path"], path
        )

    def test_mapping_failure_does_not_scan(self) -> None:
        """
        配置了映射但无法匹配时不向 Emby 发送本地路径
        """
        self.refresh.mp_mediaserver = "/server#/local"
        self.namespace["PathUtils"].get_media_path.return_value = (False, None, None)
        self.assertFalse(self.refresh.refresh_mediaserver("/other/new.strm"))
        self.assertFalse(self.refresh.refresh_mediaserver())
        self.requests.post_res.assert_not_called()

    def test_mapping_only_replaces_the_leading_prefix(self) -> None:
        """
        路径内部重复出现本地目录名时只替换已匹配前缀
        """
        self.refresh.mp_mediaserver = "/server#/local"
        self.namespace["PathUtils"].get_media_path.return_value = (
            True,
            "/server",
            "/local",
        )
        self.assertTrue(
            self.refresh.refresh_mediaserver("/local/Movies/local/new.strm")
        )
        self.assertEqual(
            self.requests.post_res.call_args.kwargs["json"]["Updates"][0]["Path"],
            "/server/Movies/local/new.strm",
        )

    def test_all_servers_are_attempted_and_failures_propagate(self) -> None:
        """
        单台失败不会跳过其他服务器，也不会汇总为全部成功
        """
        self.services["Second"] = self.service
        self.requests.post_res.side_effect = [_response(403), _response(204)]
        self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))
        self.assertEqual(self.requests.post_res.call_count, 2)

    def test_mixed_server_types_report_incomplete_discovery(self) -> None:
        """
        非 Emby 服务无法补发现时返回失败
        """
        self.services["Plex"] = SimpleNamespace(type="plex", instance=self.server)
        self.assertFalse(self.refresh.refresh_mediaserver("/movies/new.strm"))
        self.requests.post_res.assert_called_once()

    def test_known_media_full_scan_and_disabled_keep_their_routes(self) -> None:
        """
        已识别媒体、全量扫描和关闭刷新不经过补发现接口
        """
        media = SimpleNamespace(
            title="Known", year="2026", type="Movie", category="电影"
        )
        self.assertTrue(
            self.refresh.refresh_mediaserver("/movies/known.strm", mediainfo=media)
        )
        self.server.refresh_library_by_items.assert_called_once()
        self.assertTrue(self.refresh.refresh_mediaserver(refresh_all=True))
        self.server.refresh_root_library.assert_called_once()
        self.refresh.enabled = False
        self.assertTrue(self.refresh.refresh_mediaserver())
        self.requests.post_res.assert_not_called()

    def test_existing_id_does_not_submit_discovery(self) -> None:
        """
        已有 ID 时直接返回，不额外提交发现请求
        """
        info = self._info()
        info.emby_operate.get_item_id_by_path.return_value = "file-id"
        self.assertEqual(
            info._get_or_discover_item_id("Emby", "/movies/new.strm"), "file-id"
        )
        info.emby_operate.notify_media_updated.assert_not_called()
        info._stop_event.wait.assert_not_called()

    def test_both_mediainfo_paths_discover_once_then_use_file_id(self) -> None:
        """
        原生及共享媒体信息提取均通知一次并等待文件 ID
        """
        for native in (True, False):
            with self.subTest(native=native):
                info = self._info()
                info.emby_operate.get_item_id_by_path.side_effect = [
                    None,
                    None,
                    "file-id",
                ]
                info._sync_media_info = MagicMock(
                    side_effect=[(False, False, None), (True, False, None)]
                )
                info.center.download_emby_mediainfo_data.return_value = {}
                if native:
                    info.get_mediainfo_native(Path("/movies/new.strm"))
                    info.emby_operate.trigger_mediainfo_refresh.assert_called_once_with(
                        "Emby", "file-id"
                    )
                else:
                    info.get_mediainfo("sha1", Path("/movies/new.strm"))
                    self.assertEqual(
                        info._sync_media_info.call_args.kwargs["item_id"], "file-id"
                    )
                info.emby_operate.notify_media_updated.assert_called_once_with(
                    "Emby", "/movies/new.strm"
                )
                self.assertEqual(info._stop_event.wait.call_count, 2)

    def test_discovery_failure_does_not_wait_or_extract(self) -> None:
        """
        提交失败时停止等待，不执行媒体信息提取
        """
        info = self._info()
        info.emby_operate.notify_media_updated.return_value = False
        info.get_mediainfo_native(Path("/movies/new.strm"))
        info._stop_event.wait.assert_not_called()
        info.emby_operate.trigger_mediainfo_refresh.assert_not_called()

    def test_timeout_is_bounded_and_does_not_resubmit(self) -> None:
        """
        等待入库超时后返回，不重复扫描或提取
        """
        info = self._info()
        self.assertIsNone(info._get_or_discover_item_id("Emby", "/movies/new.strm"))
        self.assertEqual(self.clock, 60)
        info.emby_operate.notify_media_updated.assert_called_once()
        self.assertEqual(info.emby_operate.get_item_id_by_path.call_count, 13)

    def test_stop_interrupts_wait_and_prevents_new_discovery(self) -> None:
        """
        停止信号可中断等待，并阻止后续补发现
        """
        info = self._info()
        info._stop_event.wait.side_effect = lambda seconds: True
        self.assertIsNone(info._get_or_discover_item_id("Emby", "/movies/new.strm"))
        self.assertEqual(info.emby_operate.get_item_id_by_path.call_count, 1)
        info.emby_operate.reset_mock()
        info._stop_event.is_set.return_value = True
        self.assertIsNone(info._get_or_discover_item_id("Emby", "/movies/new.strm"))
        info.emby_operate.get_item_id_by_path.assert_not_called()
        info.emby_operate.notify_media_updated.assert_not_called()

    def test_queue_stop_interrupts_actual_discovery_wait(self) -> None:
        """
        真实队列停止会通知正在等待文件入库的提取器
        """
        entered = Event()
        helpers = []
        self.namespace.update(
            Queue=Queue,
            Lock=Lock,
            Thread=Thread,
            current_thread=current_thread,
            sleep=lambda seconds: None,
            EmbyMediainfoTask=SimpleNamespace,
        )
        base_path = self.root / "core/worker_queue.py"
        if base_path.exists():
            self.namespace["WorkerQueue"] = _load_class(
                base_path, "WorkerQueue", self.namespace
            )
        queue_type = _load_class(
            self.root / "helper/mediaserver/emby.py",
            "EmbyMediainfoQueue",
            self.namespace,
        )

        def create_helper(**kwargs):
            info = self.info_type(**kwargs)
            info.emby_operate = MagicMock()
            info.emby_operate.get_item_id_by_path.return_value = None

            def notify(*args):
                entered.set()
                return True

            info.emby_operate.notify_media_updated.side_effect = notify
            helpers.append(info)
            return info

        self.namespace["EmbyMediaInfoOperate"] = create_helper
        queue = queue_type()
        queue.start()
        worker = queue._worker_thread
        try:
            queue.enqueue("test", "/movies/new.strm", mediaservers=["Emby"])
            self.assertTrue(entered.wait(2))
            queue.stop()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(helpers[0]._stop_event.is_set())
            helpers[0].emby_operate.trigger_mediainfo_refresh.assert_not_called()
            queue.start()
            self.assertFalse(queue._discovery_stop.is_set())
        finally:
            queue.stop()


class TestLibraryScanBatch(TestCase):
    """
    验证扫描批次合并和新文件不被旧批次吞掉
    """

    def test_concurrent_requests_share_submission_result(self) -> None:
        """
        同一服务器并发请求只扫描一次并共享真实结果
        """
        for result in (True, False):
            with self.subTest(result=result):
                module = _load_scan()
                scan = module.LibraryScan()
                entered, release, follower = Event(), Event(), Event()
                callback = MagicMock(return_value=result)

                def delay(seconds):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("未释放批次")

                with (
                    patch.object(module, "sleep", side_effect=delay),
                    ThreadPoolExecutor(2) as pool,
                ):
                    first = pool.submit(scan.submit, ("a", "host", "key"), callback)
                    try:
                        self.assertTrue(entered.wait(2))
                        batch = next(iter(scan._pending.values()))
                        original_wait = batch.done.wait

                        def wait():
                            follower.set()
                            return original_wait(2)

                        with patch.object(batch.done, "wait", side_effect=wait):
                            second = pool.submit(
                                scan.submit, ("a", "host", "key"), callback
                            )
                            self.assertTrue(follower.wait(2))
                            release.set()
                            self.assertEqual(first.result(2), result)
                            self.assertEqual(second.result(2), result)
                    finally:
                        release.set()
                callback.assert_called_once()
                self.assertEqual(scan._pending, {})

    def test_requests_after_scan_start_are_not_swallowed(self) -> None:
        """
        扫描已开始后新增的文件必须触发下一次扫描
        """
        module = _load_scan()
        scan = module.LibraryScan()
        entered, release = Event(), Event()

        def first_scan():
            entered.set()
            if not release.wait(2):
                raise AssertionError("未释放扫描")
            return True

        second_scan = MagicMock(return_value=True)
        with patch.object(module, "sleep"), ThreadPoolExecutor(2) as pool:
            first = pool.submit(scan.submit, ("a", "host", "key"), first_scan)
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(scan.submit, ("a", "host", "key"), second_scan)
                self.assertTrue(second.result(2))
            finally:
                release.set()
            self.assertTrue(first.result(2))
        second_scan.assert_called_once()

    def test_servers_and_instances_have_independent_batches(self) -> None:
        """
        不同服务器及独立插件实例的扫描结果不互相覆盖
        """
        module = _load_scan()
        first_instance, second_instance = module.LibraryScan(), module.LibraryScan()
        entered, release = Event(), Event()

        def delay(seconds):
            entered.set()
            if not release.wait(2):
                raise AssertionError("未释放扫描批次")

        callbacks = [MagicMock(return_value=True) for _ in range(3)]
        with (
            patch.object(module, "sleep", side_effect=delay),
            ThreadPoolExecutor(3) as pool,
        ):
            jobs = [
                pool.submit(first_instance.submit, ("a", "host", "key"), callbacks[0]),
                pool.submit(first_instance.submit, ("b", "host", "key"), callbacks[1]),
                pool.submit(second_instance.submit, ("a", "host", "key"), callbacks[2]),
            ]
            try:
                self.assertTrue(entered.wait(2))
            finally:
                release.set()
            self.assertTrue(all(job.result(2) for job in jobs))
        for callback in callbacks:
            callback.assert_called_once()

    def test_exception_clears_batch_and_allows_retry(self) -> None:
        """
        扫描异常释放等待者并允许后续重新提交
        """
        module = _load_scan()
        scan = module.LibraryScan()
        callback = MagicMock(side_effect=RuntimeError)
        with patch.object(module, "sleep"):
            with self.assertRaises(RuntimeError):
                scan.submit(("a", "host", "key"), callback)
            self.assertEqual(scan._pending, {})
            self.assertTrue(scan.submit(("a", "host", "key"), lambda: True))
