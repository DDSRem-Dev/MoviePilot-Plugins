import ast
import asyncio
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from itertools import batched, count, cycle
from os import PathLike
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic, sleep, time
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from weakref import finalize

import aiofiles
import httpx
from iterutils import run_gen_step_iter
from p115client import P115Client, check_response
from p115client.exception import P115DataError
from p115client.fs import P115FileSystem
from p115client.tool.clouddownload import clouddownload_iter
from p115client.type import P115URL
from urllib3_future.response import HTTPResponse


def _load(path: Path, names: List[str], namespace: Dict[str, Any]) -> Dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                child.decorator_list = [
                    decorator
                    for decorator in child.decorator_list
                    if isinstance(decorator, ast.Name)
                    and decorator.id in {"dataclass", "classmethod", "staticmethod"}
                ]
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *nodes,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace


class TestP115ClientContracts(TestCase):
    """
    使用真实客户端验证插件参数与文件读取合同，隔离网络和宿主依赖
    """

    def setUp(self) -> None:
        """
        准备离线 Cookie 和当前版本的插件源码
        """
        self.root = Path(__file__).resolve().parents[1]
        self.cookie = "UID=1_A1; CID=test; SEID=test"
        self.client = P115Client(self.cookie)
        self.namespace = {
            "__name__": __name__,
            "__package__": "p115_contracts",
            "P115Client": P115Client,
            "P115DataError": P115DataError,
            "PathLike": PathLike,
            "Path": Path,
            "PurePosixPath": PurePosixPath,
            "ThreadPoolExecutor": ThreadPoolExecutor,
            "as_completed": as_completed,
            "check_response": check_response,
            "count": count,
            "cycle": cycle,
            "dataclass": dataclass,
            "finalize": finalize,
            "Lock": Lock,
            "monotonic": monotonic,
            "partial": partial,
            "run_gen_step_iter": run_gen_step_iter,
            "sleep": sleep,
            "time": time,
            "uuid4": uuid4,
        }
        self.namespace.update(
            logger=MagicMock(),
            configer=SimpleNamespace(
                get_config=lambda key: self.cookie,
                get_ios_ua_app=lambda **kwargs: {"headers": {"user-agent": "test"}},
                get_user_agent=lambda: "test",
            ),
        )

    def test_cookie_life_iterator_constructs_real_client(self) -> None:
        """
        生活事件迭代器支持 Cookie 字符串初始化
        """
        ns = _load(
            self.root / "core/p115.py",
            ["iter_life_behavior_once"],
            dict(self.namespace, IGNORE_BEHAVIOR_TYPES=()),
        )
        with patch.object(
            P115Client,
            "request",
            autospec=True,
            return_value={"state": True, "data": {"list": [], "count": 0}},
        ) as request:
            self.assertEqual(list(ns["iter_life_behavior_once"](self.cookie)), [])
        self.assertEqual(request.call_count, 1)

    def test_cookie_share_iterator_constructs_real_client(self) -> None:
        """
        分享迭代器支持 Cookie 字符串初始化并调用真实分享接口
        """
        ns = _load(
            self.root / "utils/limiter.py", ["ApiEndpointCooldown"], self.namespace
        )
        ns = _load(
            self.root / "core/p115.py",
            ["ShareP115Client", "iter_share_files_with_path"],
            ns,
        )
        with patch.object(
            P115Client,
            "request",
            autospec=True,
            return_value={"state": True, "data": {"list": [], "count": 0}},
        ) as request:
            items = ns["iter_share_files_with_path"](
                self.cookie,
                "test-share",
                max_workers=1,
            )
            self.assertEqual(list(items), [])
        self.assertEqual(request.call_count, 1)

    def _fuse_class(self) -> Any:
        ns = dict(
            self.namespace,
            FUSE_AVAILABLE=True,
            Operations=object,
            TTLCache=MagicMock(),
            IntKeyCacheAdapter=lambda cache: {},
        )
        return _load(
            self.root / "helper/fuse/__init__.py",
            ["P115FuseOperations"],
            ns,
        )["P115FuseOperations"]

    def test_cookie_fuse_constructs_real_filesystem(self) -> None:
        """
        FUSE 使用 Cookie 创建真实客户端和文件系统，不执行挂载
        """
        operations = self._fuse_class()(self.cookie)
        self.assertIsInstance(operations.client, P115Client)
        self.assertIsInstance(operations.fs, P115FileSystem)

    def test_fuse_open_preserves_url_headers_and_supports_seek(self) -> None:
        """
        FUSE 打开真实文件系统时保留下载鉴权头且可定位读取
        """
        operations = self._fuse_class()(self.client)
        url = P115URL(
            "https://example.invalid/file", headers={"user-agent": "bound-ua"}
        )
        stream = BytesIO(b"0123456789")
        reader = MagicMock()
        reader.wrap.return_value = stream
        with (
            patch.object(P115FileSystem, "get_url", autospec=True, return_value=url),
            patch(
                "p115client.fs.fs_base.HTTPFileReader", return_value=reader
            ) as factory,
        ):
            handle = operations.open("/movie.mkv", 0)
        factory.assert_called_once_with(url, start=0, headers=url.get("headers"))
        self.assertEqual(operations.read("/movie.mkv", 3, 4, handle), b"456")
        operations.release("/movie.mkv", handle)
        self.assertTrue(stream.closed)
        self.assertNotIn(handle, operations._opened)

    def test_storage_status_encodes_payload_as_query_params(self) -> None:
        """
        空间查询将 payload 编码为查询参数，不泄漏到 HTTP 请求选项
        """
        ns = _load(
            self.root / "api.py",
            ["_get_user_storage_status_data"],
            self.namespace,
        )
        status = ns["_get_user_storage_status_data"]
        space = {"state": True, "data": {"space_info": {}}}
        with (
            patch.object(
                self.client, "user_my_info", return_value={"state": True, "data": {}}
            ),
            patch.object(self.client, "request", return_value=space) as request,
        ):
            owner = SimpleNamespace(_client=self.client)
            result = status(owner, "contract-test")
        self.assertTrue(result["success"], result)
        self.assertEqual(request.call_args.kwargs["params"], {"count_space_nums": 0})
        self.assertNotIn("payload", request.call_args.kwargs)

    def test_path_lookup_timeout_reaches_current_http_backend(self) -> None:
        """
        路径查询显式超时适配真实请求后端且优先于客户端默认超时
        """
        spec = importlib.util.spec_from_file_location(
            "p115_timeout_contract", self.root / "core/p115_client.py"
        )
        timeout_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(timeout_module)
        ns = _load(
            self.root / "core/p115.py",
            ["get_pid_by_path"],
            dict(self.namespace, _inject_timeout=timeout_module._inject_timeout),
        )
        config_module = ModuleType("p115_contracts.config")
        config_module.configer = self.namespace["configer"]
        client = timeout_module.create_client_with_timeout(
            self.client,
            default_timeout={"connect": 60, "read": 60},
        )
        response = HTTPResponse(body=b'{"state": true, "id": 123}', status=200)
        with (
            patch.dict(sys.modules, {"p115_contracts.config": config_module}),
            patch(
                "urllib3_future_request._DEFAULT_POOL.request", return_value=response
            ) as request,
        ):
            result = ns["get_pid_by_path"](
                client,
                "/movies",
                mkdir=False,
                by_cache=False,
                request_timeout=10,
            )
        self.assertEqual(result, 123)
        kwargs = request.call_args.kwargs
        self.assertNotIn("extensions", kwargs)
        self.assertEqual(kwargs["timeout"].connect_timeout, 10)
        self.assertEqual(kwargs["timeout"].read_timeout, 10)
        self.assertEqual(kwargs["pool_timeout"], 10)

    def test_offline_type_is_consumed_before_http_request(self) -> None:
        """
        离线任务 type 参数由底层客户端消费，不能误判为无效请求参数
        """
        ns = _load(
            self.root / "helper/offline/__init__.py",
            ["get_tasks"],
            dict(self.namespace, clouddownload_iter=clouddownload_iter),
        )
        response = {
            "state": True,
            "tasks": [{"info_hash": "task"}],
            "count": 1,
            "page": 1,
            "page_count": 1,
        }
        with patch.object(self.client, "request", return_value=response) as request:
            tasks = list(ns["get_tasks"](SimpleNamespace(client=self.client)))
        self.assertEqual(tasks, response["tasks"])
        self.assertNotIn("type", request.call_args.kwargs)
        self.assertEqual(request.call_args.kwargs["params"]["ac"], "task_lists")

    def _downloader(self) -> Any:
        ns = dict(
            self.namespace,
            aio_open=aiofiles.open,
            asyncio_run=asyncio.run,
            asyncio_sleep=asyncio.sleep,
            batched=batched,
            pickcode_to_id=lambda value: 123,
            HTTPStatusError=httpx.HTTPStatusError,
            LocalProtocolError=httpx.LocalProtocolError,
            RequestError=httpx.RequestError,
            DownloadValidationFail=ValueError,
            httpx_stream=MagicMock(),
            iter_files=MagicMock(),
            reduce_image_url_layers=lambda value: value,
            P115URL=P115URL,
        )
        _load(self.root / "utils/url.py", ["Url"], ns)
        cls = _load(
            self.root / "helper/mediainfo_download/__init__.py",
            ["MediaInfoDownloader"],
            ns,
        )["MediaInfoDownloader"]
        downloader = cls.__new__(cls)
        downloader.oof_fast_mi_cacher = MagicMock()
        downloader.client = self.client
        downloader.headers = {"Cookie": "account-cookie", "User-Agent": "account-ua"}
        downloader._record_failures_for_items = MagicMock()
        downloader._record_mediainfo_failure = MagicMock()
        downloader._record_mediainfo_success = MagicMock()
        downloader._pending_delete_scids = []
        downloader._flush_pending_deletes = MagicMock()
        downloader.async_is_file_leq_100b = AsyncMock(return_value=False)
        return downloader, ns

    def test_collected_image_uses_web_get_download(self) -> None:
        """
        受限图片无缩略图时使用网页版 GET 获取直链并保留鉴权信息
        """
        downloader, ns = self._downloader()
        item = {
            "pickcode": "image-code",
            "sha1": "digest",
            "size": 128,
            "is_collect": True,
        }
        ns["iter_files"].return_value = [item]
        download = AsyncMock()
        downloader._MediaInfoDownloader__async_download_batch_subtitle_image = download
        response = {
            "state": True,
            "file_url": "https://example.invalid/image",
            "file_id": "123",
            "file_name": "poster.jpg",
            "file_size": "128",
            "headers": {"user-agent": "image-ua", "cookie": "download-cookie"},
        }
        with (
            patch.object(
                self.client, "fs_mkdir", return_value={"state": True, "cid": "1"}
            ),
            patch.object(self.client, "fs_copy", return_value={"state": True}),
            patch.object(self.client, "to_pickcode", return_value="image-code"),
            patch.object(self.client, "request", return_value=response) as request,
        ):
            downloader.batch_image_downloader([item])
        downloader._record_failures_for_items.assert_not_called()
        self.assertTrue(request.call_args.kwargs["url"].endswith("/files/download"))
        self.assertEqual(request.call_args.kwargs.get("method", "GET"), "GET")
        self.assertNotIn("use_web_api", request.call_args.kwargs)
        url = download.call_args.args[0]["digest"]
        self.assertEqual(url.get("headers"), response["headers"])

    def test_async_download_preserves_url_auth_without_account_cookie(self) -> None:
        """
        隐藏账号 Cookie 时仍携带直链要求的专用 Cookie 和 UA，普通 CDN 不携带 Cookie
        """
        downloader, _ = self._downloader()
        authenticated = P115URL(
            "https://example.invalid/image",
            headers={"user-agent": "download-ua", "cookie": "download-cookie"},
        )
        content = b"image" * 40
        for url in (authenticated, "https://example.invalid/public"):
            with self.subTest(url=str(url)), TemporaryDirectory() as directory:
                requests = []

                def respond(request: httpx.Request) -> httpx.Response:
                    requests.append(request)
                    return httpx.Response(200, content=content)

                target = Path(directory) / "image.jpg"

                async def download() -> None:
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(respond)
                    ) as client:
                        await downloader.async_save_mediainfo_file(
                            client,
                            asyncio.Semaphore(1),
                            target,
                            target.name,
                            url,
                            hide_cookies=True,
                        )

                asyncio.run(download())
                self.assertEqual(target.read_bytes(), content)
                headers = requests[0].headers
                if isinstance(url, P115URL):
                    self.assertEqual(headers["cookie"], "download-cookie")
                    self.assertEqual(headers["user-agent"], "download-ua")
                else:
                    self.assertNotIn("cookie", headers)
                self.assertEqual(downloader.headers["Cookie"], "account-cookie")

    def test_media_url_and_sync_download_preserve_auth_headers(self) -> None:
        """
        单文件链接获取和同步保存保留响应中的专用鉴权头
        """
        from urllib.parse import unquote, urlsplit

        downloader, ns = self._downloader()
        ns.update(unquote=unquote, urlsplit=urlsplit)
        response = {
            "state": True,
            "data": {"url": "https://example.invalid/poster.jpg"},
            "headers": {"Cookie": "download-cookie", "User-Agent": "download-ua"},
        }
        with patch.object(self.client, "download_url_app", return_value=response):
            url = downloader.get_download_url("image-code")
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"image")

        with (
            TemporaryDirectory() as directory,
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
        ):
            ns["httpx_stream"] = client.stream
            target = Path(directory) / "poster.jpg"
            self.assertTrue(downloader.save_mediainfo_file(target, target.name, url))
            self.assertEqual(target.read_bytes(), b"image")
        self.assertEqual(requests[0].headers["cookie"], "download-cookie")
        self.assertEqual(requests[0].headers["user-agent"], "download-ua")

    def test_batch_downloads_preserve_url_metadata(self) -> None:
        """
        普通批量和分享批量下载将直链鉴权信息传递到保存流程
        """
        downloader, ns = self._downloader()
        ns.update(time_sleep=lambda _: None, iter_files_skim=lambda **kwargs: [item])
        downloader.stop_all_flag = False
        item = {
            "pickcode": "image-code",
            "sha1": "digest",
            "path": "/poster.jpg",
            "file_id": 123,
            "share_code": "share",
            "receive_code": "code",
        }
        url = P115URL(
            "https://example.invalid/image", sha1="digest", headers={"cookie": "bound"}
        )
        normal = AsyncMock()
        shared = AsyncMock()
        downloader._MediaInfoDownloader__async_download_batch_subtitle_image = normal
        downloader._MediaInfoDownloader__async_download_batch_share = shared
        with (
            patch.object(self.client, "download_urls", return_value={123: url}),
            patch.object(
                self.client, "fs_mkdir", return_value={"state": True, "cid": "1"}
            ),
            patch.object(self.client, "share_receive", return_value={"state": True}),
        ):
            downloader.batch_downloader([item])
            downloader.batch_share_downloader([item])
        downloader._record_failures_for_items.assert_not_called()
        self.assertIs(normal.call_args.args[0][123], url)
        self.assertIs(shared.call_args.args[0][0]["url"], url)

    def test_disk_download_preserves_url_auth_headers(self) -> None:
        """
        同版本网盘插件本地下载携带直链要求的 Cookie 和 UA
        """
        url = P115URL(
            "https://example.invalid/file",
            headers={"Cookie": "bound", "User-Agent": "bound-ua"},
        )
        ns = dict(
            self.namespace,
            settings=SimpleNamespace(USER_AGENT="default"),
            transfer_process=lambda _: lambda percent: None,
            global_vars=SimpleNamespace(is_transfer_stopped=lambda _: False),
            RequestError=httpx.RequestError,
        )
        ns = _load(
            self.root.parent / "p115disk/p115_api.py",
            ["download", "_build_download_path"],
            ns,
        )
        fileitem = SimpleNamespace(path="/file.mkv", name="file.mkv")
        owner = SimpleNamespace(
            client=self.client,
            get_item=lambda _: SimpleNamespace(pickcode="code", size=4),
        )
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"file")

        with (
            TemporaryDirectory() as directory,
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
        ):
            ns["stream"] = client.stream
            with patch.object(self.client, "download_url", return_value=url):
                result = ns["download"](owner, fileitem, Path(directory))
            self.assertIsNotNone(result)
            self.assertEqual(result.read_bytes(), b"file")
        self.assertEqual(requests[0].headers["cookie"], "bound")
        self.assertEqual(requests[0].headers["user-agent"], "bound-ua")

    def test_backup_restore_download_preserves_url_auth_headers(self) -> None:
        """
        备份恢复下载携带直链鉴权头并向解包流程提供完整文件
        """
        url = P115URL(
            "https://example.invalid/backup",
            headers={"Cookie": "bound", "User-Agent": "bound-ua"},
        )
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"archive")

        with TemporaryDirectory() as directory:
            config = SimpleNamespace(
                PLUGIN_TEMP_PATH=Path(directory), get_user_agent=lambda: "default"
            )
            ns = _load(
                self.root / "helper/backup/__init__.py",
                ["restore_from_cloud"],
                dict(
                    self.namespace,
                    configer=config,
                    HttpxClient=partial(
                        httpx.Client, transport=httpx.MockTransport(respond)
                    ),
                ),
            )
            storage = MagicMock()
            storage.list_files.return_value = [
                SimpleNamespace(name="backup.tar.gz", type="file", pickcode="code")
            ]
            contents = []

            def extract(archive: Path, target: Path) -> Any:
                contents.append(archive.read_bytes())
                return True, None

            owner = SimpleNamespace(
                _storage_chain=storage, _storage_name="u115", _extract_tar_gz=extract
            )
            with patch.object(self.client, "download_url", return_value=url):
                result = ns["restore_from_cloud"](
                    owner,
                    "/backup.tar.gz",
                    [str(Path(directory) / "target")],
                    self.client,
                )
            self.assertEqual(result, (True, None))
        self.assertEqual(contents, [b"archive"])
        self.assertEqual(requests[0].headers["cookie"], "bound")
        self.assertEqual(requests[0].headers["user-agent"], "bound-ua")

    def test_filesystem_attribute_cache_with_current_dictattr(self) -> None:
        """
        新版 AttrDict 支持真实文件系统属性缓存、刷新和属性访问
        """
        from dictattr import AttrDict

        fs = P115FileSystem(self.client)
        original = {"id": 123, "parent_id": 0, "name": "old.mkv", "is_dir": False}
        with patch("p115client.fs.fs.get_attr", return_value=original) as get_attr:
            attr = fs.get_attr(123)
            self.assertIsInstance(attr, AttrDict)
            self.assertEqual(attr.name, "old.mkv")
            self.assertIs(fs.get_attr(123), attr)
            get_attr.assert_called_once()
            get_attr.return_value = dict(original, name="new.mkv")
            self.assertIs(fs.get_attr(123, refresh=True), attr)
            self.assertEqual(attr.name, "new.mkv")
            self.assertEqual(attr["name"], "new.mkv")
