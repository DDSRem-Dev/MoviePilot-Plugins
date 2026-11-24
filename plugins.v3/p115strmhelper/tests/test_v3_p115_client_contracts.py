import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from itertools import count, cycle
from os import PathLike
from pathlib import Path
from threading import Lock
from time import monotonic, sleep, time
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4
from weakref import finalize

from iterutils import run_gen_step_iter
from p115client import P115Client, check_response
from p115client.exception import P115DataError
from p115client.fs import P115FileSystem
from p115client.type import P115URL


def _load(path: Path, names: List[str], namespace: Dict[str, Any]) -> Dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
    ]
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef)):
                child.decorator_list = [
                    decorator
                    for decorator in child.decorator_list
                    if isinstance(decorator, ast.Name) and decorator.id == "dataclass"
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
