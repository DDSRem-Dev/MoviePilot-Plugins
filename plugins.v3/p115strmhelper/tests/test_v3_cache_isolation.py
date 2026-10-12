import __future__
import ast
import gc
import importlib
import os
import sys
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from types import ModuleType, SimpleNamespace
from typing import Any, Dict
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from weakref import finalize

from fakeredis import FakeRedis, FakeServer
from fakeredis.aioredis import FakeRedis as FakeAsyncRedis


class TestV3CacheIsolation(IsolatedAsyncioTestCase):
    """
    使用真实宿主缓存及 Redis 适配器验证实例、对象和目录隔离
    """

    def setUp(self) -> None:
        """
        加载宿主缓存实现，仅替换启动配置与 Redis 网络连接
        """
        self.root = Path(__file__).resolve().parents[1]
        host = Path(
            os.environ.get("MOVIEPILOT_SOURCE", self.root.parents[2] / "MoviePilot")
        )
        if not (host / "app/runtime/cache.py").exists():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 主程序")
        self.prefix = "_p115_cache_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app"
            or name == "txt_tree_storage"
            or name.startswith(("app.", self.prefix))
        }
        for name in originals:
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if (
                    name == "app"
                    or name == "txt_tree_storage"
                    or name.startswith(("app.", self.prefix))
                ):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)

        def module(name: str, **attributes: Any) -> ModuleType:
            value = ModuleType(name)
            value.__dict__.update(attributes)
            sys.modules[name] = value
            return value

        self.module = module
        for name in (
            "app",
            "app.sdk",
            "app.runtime",
            "app.foundation",
            "app.adapters",
            "app.adapters.cache",
        ):
            module(name, __path__=[str(host.joinpath(*name.split(".")))])
        self.settings = SimpleNamespace(CACHE_BACKEND_TYPE="memory")
        module("app.sdk.config", settings=self.settings)
        module("app.runtime.log", logger=MagicMock())
        module(
            "app.runtime.reload", ConfigReloadMixin=type("ConfigReloadMixin", (), {})
        )
        module("app.runtime.settings", get_runtime_setting=lambda key: None)
        self.runtime = importlib.import_module("app.runtime.cache")
        sys.modules["app.sdk.cache"] = self.runtime
        self.redis_module = importlib.import_module("app.adapters.cache.redis")
        self.server = FakeServer()
        self.redis = FakeRedis(server=self.server)
        self.async_redis = FakeAsyncRedis(server=self.server)
        self.addCleanup(self.redis.close)
        self.addAsyncCleanup(self.async_redis.aclose)
        helper = self.redis_module.RedisHelper()
        helper.client = self.redis
        helper._connect = MagicMock()
        async_helper = self.redis_module.AsyncRedisHelper()
        async_helper.client = self.async_redis
        async_helper._connect = AsyncMock(return_value=self.async_redis)
        self.runtime.configure_cache_factories(
            backend_type_provider=lambda: self.settings.CACHE_BACKEND_TYPE,
            file_factory=MagicMock(),
            async_file_factory=MagicMock(),
            file_ttl_provider=lambda: 60,
            redis_factory=self.redis_module.RedisBackend,
            async_redis_factory=self.redis_module.AsyncRedisBackend,
        )
        self.rust = MagicMock()
        module("txt_tree_storage", clear=self.rust.clear)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def _load(self, suffix: str) -> Any:
        prefix = self.prefix + suffix
        for tail in ("", ".core", ".utils", ".schemas"):
            path = (
                self.root.joinpath(*tail.strip(".").split(".")) if tail else self.root
            )
            self.module(prefix + tail, __path__=[str(path)])
        return SimpleNamespace(
            prefix=prefix,
            cache=importlib.import_module(prefix + ".core.cache"),
            tree=importlib.import_module(prefix + ".utils.tree"),
        )

    async def test_host_regions_really_share_data_without_an_instance_namespace(
        self,
    ) -> None:
        """
        在两种真实宿主后端复现同名缓存共享，确保隔离测试具有回归价值
        """
        for backend in ("memory", "redis"):
            with self.subTest(backend=backend):
                self.settings.CACHE_BACKEND_TYPE = backend
                first = self.runtime.TTLCache(region="unscoped", ttl=60)
                second = self.runtime.TTLCache(region="unscoped", ttl=60)
                first["same"] = "shared"
                self.assertEqual(second["same"], "shared")
                second.clear()
                self.assertNotIn("same", first)

    async def test_path_and_rename_caches_isolate_instances_on_both_backends(
        self,
    ) -> None:
        """
        相同目录 ID 和重命名键在两个实例中独立，清除一方不影响另一方
        """
        for backend in ("memory", "redis"):
            with self.subTest(backend=backend):
                self.settings.CACHE_BACKEND_TYPE = backend
                a, b = self._load(backend + "a"), self._load(backend + "b")
                a.cache.idpathcacher.add_cache(7, "/account-a")
                b.cache.idpathcacher.add_cache(7, "/account-b")
                self.assertEqual(a.cache.idpathcacher.get_dir_by_id(7), "/account-a")
                self.assertEqual(b.cache.idpathcacher.get_dir_by_id(7), "/account-b")
                self.assertIsNone(b.cache.idpathcacher.get_id_by_dir("/account-a"))
                a.cache.idpathcacher.id_to_dir.clear()
                self.assertEqual(b.cache.idpathcacher.get_dir_by_id(7), "/account-b")
                a.cache.rename_media_fields_cacher["same"] = "A"
                b.cache.rename_media_fields_cacher["same"] = "B"
                a.cache.rename_media_fields_cacher.clear()
                self.assertEqual(b.cache.rename_media_fields_cacher["same"], "B")

    async def test_redirect_read_count_clear_and_expiry_are_scoped(self) -> None:
        """
        相同 pickcode 与 UA 的地址在两种后端独立，过期写入不复用旧链接
        """
        for backend in ("memory", "redis"):
            with self.subTest(backend=backend):
                self.settings.CACHE_BACKEND_TYPE = backend
                a, b = self._load(backend + "a"), self._load(backend + "b")
                ca, cb = a.cache.r302cacher, b.cache.r302cacher
                await ca.set("pickcode", "ua", "url-a", time() + 60)
                await cb.set("pickcode", "ua", "url-b", time() + 60)
                self.assertEqual(await ca.get("pickcode", "ua"), "url-a")
                self.assertEqual(await cb.get("pickcode", "ua"), "url-b")
                self.assertEqual(await ca.count_by_pick_code("pickcode"), 1)
                await ca.clear()
                self.assertIsNone(await ca.get("pickcode", "ua"))
                self.assertEqual(await cb.get("pickcode", "ua"), "url-b")
                await cb.set("pickcode", "ua", "expired", time() - 1)
                self.assertIsNone(await cb.get("pickcode", "ua"))

    async def test_redis_directory_groups_use_instance_and_full_directory(self) -> None:
        """
        同名目录组按实例和物理目录区分，同一实例重建后仍可读取原组
        """
        self.settings.CACHE_BACKEND_TYPE = "redis"
        a, b = self._load("a"), self._load("b")
        root = self.directory / "increment_skip"
        ca = a.cache.DirectoryCache(root)
        cb = b.cache.DirectoryCache(root)
        other = a.cache.DirectoryCache(self.directory / "other/increment_skip")
        ca.add_to_group("skip", ["/a"])
        cb.add_to_group("skip", ["/b"])
        other.add_to_group("skip", ["/other"])
        reloaded = a.cache.DirectoryCache(root / "sub/..")
        self.assertEqual(reloaded.get_group_paths("skip"), {"/a"})
        self.assertFalse(cb.is_in_cache("skip", "/a"))
        ca.clear_group("skip")
        self.assertEqual(cb.get_group_paths("skip"), {"/b"})
        self.assertEqual(other.get_group_paths("skip"), {"/other"})

    async def test_redis_tree_paths_comparison_and_clear_are_scoped(self) -> None:
        """
        同名树文件按完整路径及实例隔离，比较与行号查询仍保持原契约
        """
        self.settings.CACHE_BACKEND_TYPE = "redis"
        a, b = self._load("a"), self._load("b")
        path = self.directory / "local_tree.txt"
        ta = a.tree.DirectoryTree(path)
        tb = b.tree.DirectoryTree(path)
        other = a.tree.DirectoryTree(self.directory / "other/local_tree.txt")
        ta.generate_tree_from_list(["/a", "/common"])
        tb.generate_tree_from_list(["/b"])
        other.generate_tree_from_list(["/common"])
        self.assertEqual(list(ta.compare_trees(other)), ["/a"])
        self.assertEqual(list(ta.compare_trees_lines(other)), [1])
        self.assertEqual(tb.get_path_by_line_number(1), "/b")
        self.assertGreater(self.redis.ttl(ta._storage._set_key), 0)
        ta.clear()
        self.assertEqual(tb.count(), 1)
        self.assertEqual(other.count(), 1)

    async def test_switch_to_redis_uses_the_same_full_path_namespace(self) -> None:
        """
        切换后端与直接初始化采用相同身份，不回退到文件 stem
        """
        self.settings.CACHE_BACKEND_TYPE = "redis"
        a = self._load("a")
        path = self.directory / "tree.txt"
        direct = a.tree.DirectoryTree(path)
        switched = a.tree.DirectoryTree(path, force_backend="txt")
        switched.switch_storage("redis")
        direct.generate_tree_from_list(["/a"])
        self.assertEqual(switched.get_path_by_line_number(1), "/a")

    def _api_type(self, plugin: Any) -> Any:
        tree = ast.parse((self.root / "api.py").read_text())
        cls = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Api"
        )
        cls.decorator_list = []
        cls.body = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef)
            and n.name
            in ("__init__", "_get_user_storage_status_data", "get_user_storage_status")
        ]
        schema = importlib.import_module(plugin.prefix + ".schemas.u115")
        namespace = {
            "__name__": plugin.prefix + ".api",
            "__package__": plugin.prefix,
            "TTLCache": self.runtime.TTLCache,
            "cached": self.runtime.cached,
            "uuid4": uuid4,
            "finalize": finalize,
            "configer": SimpleNamespace(get_config=lambda key: "configured"),
            "logger": MagicMock(),
            "UserStorageStatusResponse": schema.UserStorageStatusResponse,
        }
        exec(
            compile(
                ast.Module(body=[cls], type_ignores=[]),
                "api.py",
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        return namespace["Api"]

    @staticmethod
    def _client(name: str) -> Any:
        """
        创建无网络的网盘响应，用于执行真实 API 方法
        """
        client = MagicMock()
        client.user_my_info.return_value = {"state": True, "data": {"uname": name}}
        client.fs_index_info.return_value = {"state": True, "data": {"space_info": {}}}
        return client

    async def test_api_owner_replacement_and_clone_never_reuse_account_results(
        self,
    ) -> None:
        """
        真实装饰器跳过 self 时，显式对象标识仍隔离旧账号、新账号及分身
        """
        for backend in ("memory", "redis"):
            with self.subTest(backend=backend):
                self.settings.CACHE_BACKEND_TYPE = backend
                a, b = self._load(backend + "a"), self._load(backend + "b")
                first_type, second_type = self._api_type(a), self._api_type(b)
                clients = [self._client(name) for name in ("A", "B", "C")]
                old, new, clone = (
                    first_type(clients[0]),
                    first_type(clients[1]),
                    second_type(clients[2]),
                )
                for api, name in ((old, "A"), (new, "B"), (clone, "C")):
                    self.assertEqual(api.get_user_storage_status().user_info.name, name)
                    self.assertEqual(api.get_user_storage_status().user_info.name, name)
                    api.browse_dir_pan_api_cache["/"] = name
                for client in clients:
                    client.user_my_info.assert_called_once()
                old.browse_dir_pan_api_cache.clear()
                self.assertEqual(new.browse_dir_pan_api_cache["/"], "B")
                self.assertEqual(clone.browse_dir_pan_api_cache["/"], "C")
                old._get_user_storage_status_data.cache_clear()
                self.assertEqual(clone.get_user_storage_status().user_info.name, "C")
                clients[2].user_my_info.assert_called_once()
                retired_cache = new.browse_dir_pan_api_cache
                del new
                gc.collect()
                self.assertNotIn("/", retired_cache)
                self.assertEqual(clone.browse_dir_pan_api_cache["/"], "C")

    async def test_fuse_mounts_with_same_file_ids_have_independent_caches(self) -> None:
        """
        同一实例的两个 FUSE 挂载按对象隔离目录列表，保留整数键适配
        """
        source = ast.parse((self.root / "helper/fuse/__init__.py").read_text())
        cls = next(
            n
            for n in source.body
            if isinstance(n, ast.ClassDef) and n.name == "P115FuseOperations"
        )
        cls.bases, cls.decorator_list = [], []
        cls.body = [
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ]
        a = self._load("a")
        client_type = type("P115Client", (), {"get_fs": lambda self, **kwargs: kwargs})
        namespace: Dict[str, Any] = {
            "__package__": a.prefix + ".helper.fuse",
            "FUSE_AVAILABLE": True,
            "P115Client": client_type,
            "TTLCache": self.runtime.TTLCache,
            "IntKeyCacheAdapter": a.cache.IntKeyCacheAdapter,
            "uuid4": uuid4,
            "finalize": finalize,
            "count": count,
        }
        exec(
            compile(
                ast.Module(body=[cls], type_ignores=[]),
                "fuse.py",
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            namespace,
        )
        for backend in ("memory", "redis"):
            with self.subTest(backend=backend):
                self.settings.CACHE_BACKEND_TYPE = backend
                operation = namespace["P115FuseOperations"]
                first, second = operation(client_type()), operation(client_type())
                ca, cb = first.fs["id_to_readdir"], second.fs["id_to_readdir"]
                ca[1], cb[1] = ["a"], ["b"]
                self.assertEqual(ca[1], ["a"])
                self.assertEqual(cb[1], ["b"])
                ca.clear()
                self.assertEqual(cb[1], ["b"])
                ca[1] = ["retired"]
                del first
                gc.collect()
                self.assertNotIn(1, ca)
                self.assertEqual(cb[1], ["b"])
