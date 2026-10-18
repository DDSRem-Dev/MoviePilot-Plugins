import importlib
import logging
import os
import sqlite3
import sys
from contextlib import closing
from random import Random
from shutil import copytree, copyfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, declarative_base


class TestV3Database(TestCase):
    """
    使用真实宿主句柄注册表和 Alembic 迁移验证插件数据库
    """

    database_url = None

    def setUp(self) -> None:
        """
        隔离宿主启动配置并加载实际数据库基础设施
        """
        self.root = Path(__file__).resolve().parents[1]
        self.host = Path(
            os.environ.get("MOVIEPILOT_SOURCE", self.root.parents[2] / "MoviePilot")
        )
        if not (self.host / "app/db/plugin/registry.py").is_file():
            self.skipTest("需要 MOVIEPILOT_SOURCE 指向 V3 宿主源码")
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "legacy.db"
        self.prefix = "_p115_database_test"
        originals = {
            name: value
            for name, value in sys.modules.items()
            if name == "app" or name.startswith("app.")
        }
        for name in list(originals):
            sys.modules.pop(name)

        def restore() -> None:
            for name in list(sys.modules):
                if (
                    name == "app"
                    or name.startswith("app.")
                    or name.startswith(self.prefix)
                ):
                    sys.modules.pop(name)
            sys.modules.update(originals)

        self.addCleanup(restore)

        def module(name: str, **values: Any) -> ModuleType:
            result = ModuleType(name)
            result.__dict__.update(values)
            sys.modules[name] = result
            return result

        for name in (
            "app",
            "app.db",
            "app.db.plugin",
            "app.runtime",
            "app.sdk",
            "app.runtime.extensions",
            "app.runtime.extensions.plugin",
        ):
            module(name, __path__=[str(self.host.joinpath(*name.split(".")))])
        module("app.runtime.log", logger=logging.getLogger("p115-db-test"))
        module("app.sdk.logging", logger=logging.getLogger("p115-db-test"))
        module(
            "app.runtime.extensions.plugin.datadir",
            resolve_plugin_data_directory=lambda plugin_id: self.directory / plugin_id,
        )
        self.host_engine = (
            create_engine(self.database_url) if self.database_url else None
        )
        if self.host_engine is not None:
            self.addCleanup(self.host_engine.dispose)
        module(
            "app.runtime.settings",
            get_runtime_setting=lambda key: (
                "postgresql" if self.database_url else "sqlite"
            ),
        )
        module(
            "app.db.engine",
            build_sqlite_engine=create_engine,
            apply_sqlite_journal_mode=lambda engine: None,
            get_engine=lambda: self.host_engine,
        )
        base = importlib.import_module("app.db.plugin.base")
        container = importlib.import_module("app.db.plugin.container")
        module(
            "app.sdk.database",
            plugin_declarative_base=base.plugin_declarative_base,
            PluginDatabaseHandle=container.PluginDatabaseHandle,
        )
        self.registry = importlib.import_module("app.db.plugin.registry")
        self.addCleanup(self._release_databases)
        for suffix in ("", ".core"):
            module(self.prefix + suffix, __path__=[str(self.root / suffix.strip("."))])
        self.config = SimpleNamespace(PLUGIN_DB_PATH=self.source)
        module(f"{self.prefix}.core.config", configer=self.config)
        schemas = module("app.schemas", __path__=[str(self.host / "app/schemas")])
        self.file_item = importlib.import_module("app.schemas.file").FileItem
        schemas.FileItem = self.file_item
        self.db = importlib.import_module(f"{self.prefix}.db_manager")
        self.models = importlib.import_module(f"{self.prefix}.db_manager.models")
        self.legacy = importlib.import_module(f"{self.prefix}.db_manager.legacy")
        v2_root = self.root.parents[1] / "plugins.v2" / "p115strmhelper"
        module(self.prefix + ".v2", __path__=[str(v2_root)])
        self.v2_base = declarative_base()
        module(
            self.prefix + ".v2.db_manager",
            __path__=[str(v2_root / "db_manager")],
            P115StrmHelperBase=self.v2_base,
            db_query=lambda function: function,
            db_update=lambda function: function,
        )
        importlib.import_module(self.prefix + ".v2.db_manager.models")
        self.bind_owner()

    def _release_databases(self) -> None:
        schemas = [
            handle.schema
            for handle in self.registry.database_handles()
            if handle.schema
        ]
        self.registry.release_all_databases()
        if self.host_engine is not None:
            with self.host_engine.begin() as connection:
                for schema in schemas:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

    def bind_owner(self, clone: bool = False) -> Any:
        """
        建立具有宿主真实句柄访问合同的插件实例
        """
        owner = type("P115Test" + uuid4().hex, (), {})()
        owner.is_clone = clone
        owner.get_database_migrations = lambda: self.root / "database"
        owner.get_database = lambda: self.registry.get_database(
            owner.__class__.__name__
        )
        self.owner = owner
        self.config.plugin_instance = owner
        return owner

    def create_legacy(self) -> None:
        """
        构造 V2 最后一个 revision 的真实 SQLite 库
        """
        engine = create_engine(f"sqlite:///{self.source}")
        try:
            self.v2_base.metadata.create_all(engine)
        finally:
            engine.dispose()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
            connection.execute("INSERT INTO alembic_version VALUES ('c76c9a1f52dc')")
            connection.execute(
                "INSERT INTO files (id,parent_id,name,path,extra) VALUES (5000000001,5000000002,'电影','/电影','原数据')"
            )
            connection.execute(
                "INSERT INTO folders (id,parent_id,name,path) VALUES (5000000002,0,'根目录','/')"
            )
            connection.execute(
                "INSERT INTO open_files (id,parent_id,name,path) VALUES (5000000003,0,'开放接口','/open')"
            )
            connection.execute(
                "INSERT INTO open_folders (id,parent_id,name,path) VALUES (5000000004,0,'目录','/目录')"
            )
            connection.execute(
                "INSERT INTO life_event (id,type,file_id,parent_id,file_category,file_type) VALUES (5000000005,1,5000000001,5000000002,1,1)"
            )

    def count(self, model: Any) -> int:
        """
        使用宿主句柄检查持久化数量
        """
        with self.owner.get_database().session() as session:
            return session.scalar(select(func.count()).select_from(model))

    def test_fresh_install_and_repeated_initialization(self) -> None:
        """
        空库建表与重复初始化幂等，使用宿主实际迁移到 V3 head
        """
        self.assertTrue(self.db.init_database())
        self.assertTrue(self.db.init_database())
        with self.owner.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                "p115v3_post_01",
            )
            self.assertEqual(
                connection.scalar(text("SELECT source FROM p115_legacy_import")),
                "new-install",
            )
        self.assertEqual(self.count(self.models.File), 0)

    def test_import_all_tables_and_preserve_original(self) -> None:
        """
        五张旧表及 64 位标识无损导入，原 SQLite 主文件不改写
        """
        self.create_legacy()
        original = self.source.read_bytes()
        self.db.init_database()
        for model in (
            self.models.File,
            self.models.Folder,
            self.models.LifeEvent,
            self.models.OpenFile,
            self.models.OpenFolder,
        ):
            self.assertEqual(self.count(model), 1)
            with closing(sqlite3.connect(self.source)) as source:
                source.row_factory = sqlite3.Row
                expected = [
                    dict(row)
                    for row in source.execute(f'SELECT * FROM "{model.__tablename__}"')
                ]
            self.assertEqual([item.to_dict() for item in model.list(None)], expected)
        item = self.models.File.get_by_id(None, 5000000001)
        self.assertEqual(item.to_dict()["extra"], "原数据")
        self.assertEqual(self.source.read_bytes(), original)
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 1)

    def test_reads_uncheckpointed_wal(self) -> None:
        """
        源库仍有活动连接时读取未 checkpoint 的已提交 WAL 数据
        """
        self.create_legacy()
        writer = sqlite3.connect(self.source)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO files (id,parent_id,path) VALUES (99,0,'/wal')")
        writer.commit()
        self.assertGreater(Path(str(self.source) + "-wal").stat().st_size, 0)
        self.db.init_database()
        self.assertIsNotNone(self.models.File.get_by_id(None, 99))

    def test_failed_import_rolls_back_and_retries(self) -> None:
        """
        数据写入后异常不留下半库或完成标记，下次可重新导入
        """
        self.create_legacy()
        original_copy = self.legacy._copy_rows

        def fail_after_copy(*args: Any) -> None:
            original_copy(*args)
            raise RuntimeError("模拟导入中断")

        with patch.object(self.legacy, "_copy_rows", fail_after_copy):
            with self.assertRaisesRegex(RuntimeError, "模拟导入中断"):
                self.db.init_database()
        self.assertEqual(self.count(self.models.File), 0)
        with self.owner.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT COUNT(*) FROM p115_legacy_import")), 0
            )
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 1)

    def test_clone_does_not_import_main_data(self) -> None:
        """
        分身保留独立空库与导入状态
        """
        self.create_legacy()
        main = self.owner
        self.db.init_database()
        self.bind_owner(clone=True)
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 0)
        self.assertNotEqual(
            main.get_database().plugin_id, self.owner.get_database().plugin_id
        )
        with self.owner.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT source FROM p115_legacy_import")),
                "clone",
            )

    def test_new_install_does_not_import_a_late_legacy_file(self) -> None:
        """
        新安装完成后出现旧文件也不重新导入
        """
        self.db.init_database()
        self.create_legacy()
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 0)

    def test_unknown_revision_refuses_import(self) -> None:
        """
        不认识的旧版 revision 明确失败
        """
        self.create_legacy()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute(
                "UPDATE alembic_version SET version_num='future_revision'"
            )
        with self.assertRaisesRegex(RuntimeError, "版本无法识别"):
            self.db.init_database()

    def test_nonempty_unmarked_target_is_not_overwritten(self) -> None:
        """
        已有目标数据且没有完成标记时拒绝混合或覆盖
        """
        self.registry.ensure_database(
            self.owner.__class__.__name__, migrations=self.root / "database"
        )
        with self.owner.get_database().engine.begin() as connection:
            connection.execute(
                text("INSERT INTO files (id,parent_id,path) VALUES (1,0,'/existing')")
            )
        with self.assertRaisesRegex(RuntimeError, "已有数据"):
            self.db.init_database()
        self.assertEqual(self.count(self.models.File), 1)

    def test_caller_transaction_is_not_committed(self) -> None:
        """
        显式会话在多个模型操作后可整体回滚
        """
        self.db.init_database()
        with self.owner.get_database().session() as session:
            self.models.File.upsert_batch_by_list(
                session, [{"id": 7, "parent_id": 0, "path": "/a"}]
            )
            self.models.Folder.upsert_batch_by_list(
                session, [{"id": 8, "parent_id": 0, "name": "b", "path": "/b"}]
            )
            session.rollback()
        self.assertEqual(self.count(self.models.File), 0)
        self.assertEqual(self.count(self.models.Folder), 0)

    def test_implicit_session_commits_and_detaches_loaded_fields(self) -> None:
        """
        自动事务提交且查询返回值在会话关闭后仍可读取
        """
        self.db.init_database()
        self.models.File.upsert_batch_by_list(
            None, [{"id": 7, "parent_id": 0, "name": "已提交", "path": "/a"}]
        )
        item = self.models.File.get_by_path(db=None, file_path="/a")
        self.assertTrue(inspect(item).detached)
        self.assertEqual(item.name, "已提交")
        item.update(None, {"name": "新名称"})
        self.assertEqual(item.name, "新名称")
        self.assertEqual(self.models.File.get_by_id(None, 7).name, "新名称")

    def test_replace_preserves_sequential_id_and_path_conflicts(self) -> None:
        """
        交叉主键、路径覆盖和默认值行为与顺序 REPLACE 一致
        """
        self.db.init_database()
        self.models.File.upsert_batch_by_list(
            None, [{"id": 3, "parent_id": 0, "path": "/x"}]
        )
        self.models.File.upsert_batch_by_list(
            None,
            [
                {"id": 1, "parent_id": 0, "path": "/x", "name": "旧"},
                {"id": 1, "parent_id": 0, "path": "/y"},
                {"id": 2, "parent_id": 0, "path": "/y"},
                {"id": 4, "parent_id": 0},
                {"id": 5, "parent_id": 0},
            ],
        )
        self.assertEqual({item.id for item in self.models.File.list(None)}, {2, 4, 5})
        self.assertEqual(self.models.File.get_by_id(None, 2).name, "")

    def test_open_file_writes_preserve_baseline_tables(self) -> None:
        """
        Open 文件写入保留复制基线的双表效果
        """
        self.db.init_database()
        helper = importlib.import_module(
            f"{self.prefix}.db_manager.open_file_oper"
        ).OpenFileOper()
        helper.upsert_batch([{"id": 9, "parent_id": 0, "path": "/video.mkv"}])
        self.assertEqual(self.count(self.models.OpenFile), 1)
        self.assertEqual(self.count(self.models.OpenFolder), 1)
        self.assertEqual(
            list(helper.get_files_info_by_id({9}))[0]["path"], "/video.mkv"
        )

    def test_stop_rejects_new_sessions_without_disposing_host(self) -> None:
        """
        插件停止不释放宿主句柄或 PostgreSQL 共享连接池
        """
        self.db.init_database()
        handle = self.owner.get_database()
        with patch.object(type(handle), "dispose") as dispose:
            self.db.ct_db_manager.close_database()
            dispose.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "已停止"):
            self.models.File.get_by_id(None, 1)
        with handle.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT 1")), 1)

    def test_invalid_source_fails_without_completion_marker(self) -> None:
        """
        空文件、损坏文件及未知表结构不会被当成新安装
        """
        for content in (b"", b"not a sqlite database"):
            with self.subTest(content=content):
                self.source.write_bytes(content)
                with self.assertRaises((RuntimeError, sqlite3.DatabaseError)):
                    self.db.init_database()
                with self.owner.get_database().engine.connect() as connection:
                    self.assertEqual(
                        connection.scalar(
                            text("SELECT COUNT(*) FROM p115_legacy_import")
                        ),
                        0,
                    )
        self.source.unlink()
        self.create_legacy()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute("CREATE TABLE unsupported (id INTEGER)")
        with self.assertRaisesRegex(RuntimeError, "表结构无法识别"):
            self.db.init_database()
        self.assertEqual(self.count(self.models.File), 0)

    def test_initial_v2_tables_import_without_later_tables(self) -> None:
        """
        初始 V2 revision 仅有文件与目录表时仍能迁移
        """
        self.create_legacy()
        with closing(sqlite3.connect(self.source)) as connection, connection:
            for table in ("open_files", "open_folders", "life_event"):
                connection.execute(f'DROP TABLE "{table}"')
            connection.execute("UPDATE alembic_version SET version_num='294b0079357e'")
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 1)
        self.assertEqual(self.count(self.models.LifeEvent), 0)

    def test_same_source_and_target_rejected_before_migrations(self) -> None:
        """
        错配相同 SQLite 路径时不会先升级并修改源库
        """
        handle = self.owner.get_database()
        if handle.db_path is None:
            self.skipTest("同路径保护仅适用于 SQLite 目标")
        self.source = handle.db_path
        self.config.PLUGIN_DB_PATH = self.source
        self.create_legacy()
        original = self.source.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "目标相同"):
            self.db.init_database()
        self.assertEqual(self.source.read_bytes(), original)

    def test_unknown_target_revision_is_preserved(self) -> None:
        """
        宿主拒绝升级不认识的目标 revision 并保留原记录
        """
        self.db.init_database()
        with self.owner.get_database().engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num='future_target'")
            )
        with self.assertRaisesRegex(RuntimeError, "future_target"):
            self.db.init_database()
        with self.owner.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                "future_target",
            )

    def test_unmarked_old_target_is_rejected_before_schema_changes(self) -> None:
        """
        目标已有旧表数据时不先运行旧迁移或改写 revision
        """
        with self.owner.get_database().engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT)")
            )
            connection.execute(
                text("INSERT INTO files (id,path) VALUES (1,NULL),(2,NULL)")
            )
            connection.execute(
                text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
                )
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES ('294b0079357e')")
            )
        with self.assertRaisesRegex(RuntimeError, "已有数据"):
            self.db.init_database()
        with self.owner.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT version_num FROM alembic_version")),
                "294b0079357e",
            )
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM files")), 2)
            self.assertNotIn("folders", inspect(connection).get_table_names())

    def test_failed_batch_rolls_back_conflict_deletions(self) -> None:
        """
        批次后续记录无效时前面的删除与插入一并回滚
        """
        self.db.init_database()
        self.models.Folder.upsert_batch_by_list(
            None, [{"id": 1, "parent_id": 0, "name": "保留", "path": "/old"}]
        )
        with self.assertRaises(IntegrityError):
            self.models.Folder.upsert_batch_by_list(
                None,
                [
                    {"id": 1, "parent_id": 0, "name": "覆盖", "path": "/new"},
                    {"id": 2, "parent_id": 0, "path": "/invalid"},
                ],
            )
        self.assertEqual(self.models.Folder.get_by_id(None, 1).name, "保留")
        self.assertEqual(self.count(self.models.Folder), 1)

    def test_large_replace_matches_sequential_sqlite_reference(self) -> None:
        """
        超过分块大小的随机冲突批次与原生 SQLite 顺序替换结果一致
        """
        self.db.init_database()
        random = Random(115)
        rows = [
            {
                "id": random.randrange(800),
                "parent_id": 0,
                "name": str(index),
                "path": random.choice([None, "", f"/路径/{random.randrange(800)}"]),
            }
            for index in range(1800)
        ]
        rows[:0] = [
            {"id": index, "parent_id": 0, "name": "初始", "path": f"/initial/{index}"}
            for index in range(1000, 2200)
        ]
        with closing(sqlite3.connect(":memory:")) as reference:
            reference.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, name TEXT, path TEXT UNIQUE)"
            )
            reference.executemany(
                "INSERT OR REPLACE INTO files (id,parent_id,name,path) VALUES (:id,:parent_id,:name,:path)",
                rows,
            )
            expected = reference.execute(
                "SELECT id, parent_id, name, path FROM files ORDER BY id"
            ).fetchall()
        self.models.File.upsert_batch_by_list(None, rows)
        actual = sorted(
            (item.id, item.parent_id, item.name, item.path)
            for item in self.models.File.list(None)
        )
        self.assertEqual(actual, expected)

    def test_string_and_integer_ids_share_replace_identity(self) -> None:
        """
        API 混用数字字符串与整数 ID 时遵循相同主键覆盖语义
        """
        self.db.init_database()
        self.models.File.upsert_batch_by_list(
            None,
            [
                {"id": "5000000001", "parent_id": 0, "path": "/old"},
                {"id": 5000000001, "parent_id": 0, "path": "/new"},
            ],
        )
        self.assertEqual(self.count(self.models.File), 1)
        self.assertEqual(self.models.File.get_by_id(None, 5000000001).path, "/new")

    def test_path_operations_match_original_sqlite(self) -> None:
        """
        两种宿主数据库的路径操作与原 SQLite 实现逐行对照
        """
        self.db.init_database()
        reference_engine = create_engine("sqlite://")
        self.addCleanup(reference_engine.dispose)
        self.v2_base.metadata.create_all(reference_engine)
        paths = [
            "/A_%",
            "/A_%/电影1.mkv",
            "/ABx/文件2",
            "/a_%/文件3",
            "/A_%2/文件4",
            "/Ä/文件5",
            "/ä/文件6",
            r"/A\q/文件7",
            "/A_q/文件8",
            "/aXq/文件9",
            "/other/文件10",
            "/line\nbreak/文件11",
        ]
        scenarios = (
            [
                ("remove_by_path_batch", (prefix,))
                for prefix in ("/A_%", "/a_%", r"/A\q", "/Ä", "/missing", "", "/line\n")
            ]
            + [
                ("remove_by_path_prefix_not_in_ids", (prefix, {2, 9}))
                for prefix in ("/A_%", r"/A\q", "/Ä")
            ]
            + [
                ("update_path_prefix", ("/A_%", "/")),
                ("update_path_prefix", ("/A_%", "/target")),
                ("update_path_prefix", (r"/A\q", "/target")),
                ("update_path_prefix", ("/", "/target")),
            ]
        )
        records = [
            {"id": index, "parent_id": 0, "name": str(index), "path": path}
            for index, path in enumerate(paths, start=1)
        ]
        for model in (self.models.File, self.models.Folder):
            original_model = getattr(
                importlib.import_module(
                    f"{self.prefix}.v2.db_manager.models.{model.__name__.lower()}"
                ),
                model.__name__,
            )
            for method, arguments in scenarios:
                with self.subTest(model=model.__name__, method=method, args=arguments):
                    model.truncate(None)
                    model.upsert_batch_by_list(None, records)
                    with Session(reference_engine) as reference:
                        reference.execute(delete(original_model))
                        original_model.upsert_batch_by_list(reference, records)
                        expected_result = getattr(original_model, method)(
                            reference, *arguments
                        )
                        expected = reference.execute(
                            select(original_model.id, original_model.path).order_by(
                                original_model.id
                            )
                        ).all()
                        actual_result = getattr(model, method)(None, *arguments)
                        with self.owner.get_database().session() as actual:
                            rows = actual.execute(
                                select(model.id, model.path).order_by(model.id)
                            ).all()
                        self.assertEqual(actual_result, expected_result)
                        self.assertEqual(rows, expected)

    def test_helper_preserves_original_export_shape(self) -> None:
        """
        辅助方法保留原文件目录字段与内部状态占位约定
        """
        self.db.init_database()
        self.models.Folder.upsert_batch_by_list(
            None, [{"id": 1, "parent_id": 0, "name": "目录", "path": "/parent"}]
        )
        self.models.File.upsert_batch_by_list(
            None, [{"id": 2, "parent_id": 1, "name": "文件", "path": "/parent/file"}]
        )
        helper_type = importlib.import_module(
            f"{self.prefix}.db_manager.file_oper"
        ).FileDbHelper
        result = helper_type().get_children("/parent")
        self.assertEqual(result["files"][0]["id"], 2)
        self.assertEqual(result["files"][0]["type"], "file")
        self.assertNotIn("_sa_instance_state", result["files"][0])
        self.assertEqual(result["subfolders"], [])
        self.assertEqual(
            result["meta"],
            {
                "parent_path": "/parent",
                "parent_id": 1,
                "total_count": 1,
            },
        )
        self.assertIsNone(helper_type().get_by_id(2)["_sa_instance_state"])
        self.assertEqual(helper_type().get_by_path("/parent")["type"], "folder")

    def test_host_fileitem_timestamp_preserves_baseline(self) -> None:
        """
        保留原 FileItem 时间转换，仅适配宿主数据库存储
        """
        self.db.init_database()
        helper = importlib.import_module(
            f"{self.prefix}.db_manager.file_oper"
        ).FileDbHelper()
        item = self.file_item(
            type="file", fileid="5000000001", path="/file.mkv", name="file.mkv"
        )
        with self.assertRaises(TypeError):
            helper.process_fileitem(item)
        item.modify_time = 1700000000.5
        helper.upsert_batch(helper.process_fileitem(item))
        cached = self.models.File.get_by_id(None, 5000000001)
        self.assertEqual(cached.mtime, 1700000000)
        self.assertEqual(cached.parent_id, -1)
        self.assertEqual(cached.size, -1)

    def test_replace_and_raw_sql_remain_in_current_instance(self) -> None:
        """
        本体与分身使用相同主键及路径时不会跨库覆盖
        """
        self.db.init_database()
        main = self.owner
        self.models.File.upsert_batch_by_list(
            None, [{"id": 1, "parent_id": 0, "path": "/same", "name": "本体"}]
        )
        self.bind_owner(clone=True)
        self.db.init_database()
        self.models.File.upsert_batch_by_list(
            None, [{"id": 1, "parent_id": 0, "path": "/same", "name": "分身"}]
        )
        with main.get_database().engine.connect() as connection:
            self.assertEqual(
                connection.scalar(text("SELECT name FROM files WHERE id=1")), "本体"
            )
        self.assertEqual(self.models.File.get_by_id(None, 1).name, "分身")

    def test_owned_sqlite_busy_retries_and_caller_session_does_not(self) -> None:
        """
        只重试自行创建的 SQLITE_BUSY 事务，调用方事务保持原异常
        """
        self.db.init_database()
        calls = []
        original = sqlite3.OperationalError("database is locked")
        original.sqlite_errorcode = sqlite3.SQLITE_BUSY

        @self.db.db_update
        def operation(db: Any) -> None:
            calls.append(db)
            if len(calls) < 3:
                raise OperationalError("test", {}, original)

        with patch.object(self.db, "sleep"):
            operation(None)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len({id(session) for session in calls}), 3)
        calls.clear()
        with self.owner.get_database().session() as session:
            with self.assertRaises(OperationalError):
                operation(session)
        self.assertEqual(len(calls), 1)

    def test_migration_generator_uses_temporary_database(self) -> None:
        """
        在隔离源码副本生成真实迁移草稿且不访问运行中的插件库
        """
        generator = importlib.import_module(f"{self.prefix}.database.gen")
        copy_root = self.directory / "generator"
        copytree(self.root / "database", copy_root / "database")
        copyfile(self.root / "migration_meta.json", copy_root / "migration_meta.json")
        with patch.object(generator, "__file__", str(copy_root / "database/gen.py")):
            revision = generator.generate_revision("3.0.1")
        scripts = list((copy_root / "database/versions").glob(f"*-{revision}.py"))
        self.assertEqual(len(scripts), 1)
        namespace = {}
        exec(compile(scripts[0].read_text(), str(scripts[0]), "exec"), namespace)
        self.assertEqual(namespace["down_revision"], "p115v3_post_01")
        namespace["upgrade"]()
        namespace["downgrade"]()
        self.assertEqual(self.registry.database_handles(), ())

    def test_locked_legacy_snapshot_times_out_and_can_retry(self) -> None:
        """
        持续独占锁触发有界等待，释放锁后仍可完整导入
        """
        self.create_legacy()
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute("BEGIN EXCLUSIVE")
            with patch.object(self.legacy, "_BACKUP_LOCK_TIMEOUT", 0):
                with self.assertRaisesRegex(RuntimeError, "持续被锁定"):
                    self.db.init_database()
            writer.rollback()
        self.db.init_database()
        self.assertEqual(self.count(self.models.File), 1)

    def test_postprocess_migration_preserves_existing_v3_data(self) -> None:
        """
        已安装 V3 的数据库升级后保留原数据并创建事件和资源表
        """
        self.db.init_database()
        self.models.File.upsert_batch_by_list(
            None, [dict(id=1, parent_id=0, name="kept", path="/kept")]
        )
        with self.owner.get_database().engine.begin() as connection:
            self.models.TransferPostprocess.__table__.drop(connection)
            self.models.TransferResource.__table__.drop(connection)
            connection.execute(
                text("UPDATE alembic_version SET version_num='p115v3_db_01'")
            )
        self.registry.release_all_databases()
        self.db.init_database()
        self.assertEqual(self.models.File.get_by_id(None, 1).name, "kept")
        self.assertEqual(self.count(self.models.TransferPostprocess), 0)
        self.assertEqual(self.count(self.models.TransferResource), 0)

    def test_postprocess_list_filters_paginates_and_isolates_instances(self) -> None:
        """
        后处理列表稳定分页、筛选状态并隔离不同实例的数据
        """
        self.db.init_database()
        module = importlib.import_module(
            f"{self.prefix}.db_manager.transfer_postprocess"
        )
        store = module.TransferPostprocessStore()
        plan = {
            "identity": {"path": "/电影/a.mkv", "size": 0},
            "operations": [{"path": "/媒体/a.strm"}],
            "superseded_reason": "大小不一致",
        }
        for key, state in (("c", "done"), ("b", "superseded"), ("a", "pending")):
            store.save(key * 64, plan, state)
        first = store.list_records(page_size=1)
        second = store.list_records(page=2, page_size=1)
        self.assertEqual(first["total"], 2)
        self.assertEqual(first["items"][0]["key"], "a" * 64)
        self.assertEqual(second["items"][0]["key"], "b" * 64)
        self.assertEqual(first["items"][0]["size"], 0)
        self.assertNotIn("plan", first["items"][0])
        self.assertEqual(store.list_records("done")["total"], 1)
        self.assertEqual(store.list_records("all")["total"], 3)
        self.assertEqual(store.list_records(page=99)["items"], [])
        first["items"][0]["cloud_path"] = "changed"
        self.assertEqual(store.load("a" * 64)["plan"], plan)
        self.bind_owner(clone=True)
        self.db.init_database()
        self.assertEqual(module.TransferPostprocessStore().list_records()["total"], 0)

    def test_postprocess_file_and_checkpoint_commit_atomically(self) -> None:
        """
        事件计划与文件归属在同一事务提交，失败不留下单边成功记录
        """
        self.db.init_database()
        module = importlib.import_module(
            f"{self.prefix}.db_manager.transfer_postprocess"
        )
        store = module.TransferPostprocessStore()
        path = self.directory / "library/电影.strm"
        operation = {
            "path": str(path),
            "identity": {"fileid": "123"},
            "after": {"sha256": "abc"},
        }
        plan = {"operations": [operation]}
        key = "a" * 64
        store.save(key, plan)
        with patch.object(Session, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(RuntimeError):
                store.complete_file(key, plan, operation)
        self.assertIsNone(store.owner(path))
        store.complete_file(key, plan, operation)
        self.assertEqual(store.owner(path)["event_key"], key)
        self.assertEqual(store.load(key)["plan"], plan)
        store.save(key, plan, "done")
        self.assertEqual(module.TransferPostprocessStore().load(key)["state"], "done")


@skipUnless(os.environ.get("P115_TEST_POSTGRES_URL"), "需要隔离的 PostgreSQL 测试服务")
class TestV3PostgresDatabase(TestV3Database):
    """
    在真实 PostgreSQL 上复用相同的数据迁移与事务验收
    """

    database_url = os.environ.get("P115_TEST_POSTGRES_URL")
