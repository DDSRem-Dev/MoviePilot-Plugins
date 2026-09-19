"""
存量数据库迁移模块测试（core/legacy_migration.py）

覆盖：全新安装、迁移成功、幂等跳过、分身跳过、H1 自定义路径、H2 标记不得
凌驾文件事实、崩溃残留清理、校验失败中止、skip_legacy_db_import 逃生阀、
WAL 数据完整性

沿用 test_transfer_classify.py 的手法：手工向 sys.modules 注册假依赖模块，
再用 importlib 按文件路径加载被测模块本体，脱离 MoviePilot 宿主环境运行
"""

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple
from unittest import TestCase

plugin_root = Path(__file__).resolve().parents[1]

# 与 core/legacy_migration.py 中 _LEGACY_TABLES 保持一致的夹具表清单
_FIXTURE_TABLES: Tuple[str, ...] = (
    "files",
    "folders",
    "life_event",
    "open_files",
    "open_folders",
)

# 刻意指向一个不存在的路径，用于验证代码没有误用「默认路径」兜底
_UNUSED_DEFAULT_DB_PATH = Path(
    "/nonexistent-default-should-never-be-read/p115strmhelper_file.db"
)


def _make_module(name: str, **attrs: Any) -> ModuleType:
    """
    创建并注册假模块

    :param name (str): 模块名
    :param attrs (Dict): 模块属性

    :return ModuleType: 假模块
    """
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _RecordingLogger:
    """
    记录调用参数的假日志器，供测试断言具体级别是否被调用
    """

    def __init__(self) -> None:
        """
        初始化各级别调用记录列表
        """
        self.info_calls: List[str] = []
        self.warning_calls: List[str] = []
        self.error_calls: List[str] = []
        self.debug_calls: List[str] = []

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.info_calls.append(msg)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append(msg)

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append(msg)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_calls.append(msg)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.debug_calls.append(msg)


class _FakeConfigManager:
    """
    假 ConfigManager，仅暴露 legacy_migration 依赖的默认路径解析静态方法
    """

    @staticmethod
    def _get_default_plugin_db_path() -> Path:
        return _UNUSED_DEFAULT_DB_PATH


class FakePluginInstance:
    """
    假插件主类实例，提供 run_legacy_migration 所需的最小接口
    """

    def __init__(self, data_path: Path, is_clone: bool = False) -> None:
        """
        初始化假插件实例

        :param data_path (Path): get_data_path() 返回的目录
        :param is_clone (bool): 是否分身
        """
        self.is_clone = is_clone
        self._data_path = data_path
        self._data_store: Dict[str, Any] = {}
        self.save_data_calls: List[Tuple[str, Any]] = []

    def get_data_path(self) -> Path:
        return self._data_path

    def save_data(self, key: str, value: Any) -> None:
        self._data_store[key] = value
        self.save_data_calls.append((key, value))

    def get_data(self, key: str, default: Any = None) -> Any:
        return self._data_store.get(key, default)


def _setup_mock_env() -> None:
    """
    注册 legacy_migration 模块 import 时需要的假依赖模块
    """
    _make_module(
        "app.sdk.logging",
        logger=_RecordingLogger(),
    )
    _make_module(
        "app.plugins.p115strmhelper.core.config",
        ConfigManager=_FakeConfigManager,
    )


def _load_module(rel_path: str) -> ModuleType:
    """
    按插件相对路径加载真实模块（绕过插件包 __init__，避免触发运行依赖）

    :param rel_path (str): 插件内相对路径，点号或斜杠均可

    :return ModuleType: 已加载模块
    """
    module_name = f"app.plugins.p115strmhelper.{rel_path.replace('/', '.')}"
    file_rel = f"{rel_path.replace('.', '/')}.py"
    spec = importlib.util.spec_from_file_location(module_name, plugin_root / file_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _create_legacy_db(
    path: Path,
    *,
    wal: bool = False,
    rows_per_table: int = 5,
    checkpoint: bool = True,
) -> Optional[sqlite3.Connection]:
    """
    创建一个包含 5 张业务表 + alembic_version 的 v2 存量库夹具

    :param path (Path): 数据库文件路径，父目录需已存在
    :param wal (bool): 是否切换为 WAL 模式
    :param rows_per_table (int): 每张业务表插入的行数
    :param checkpoint (bool): WAL 模式下是否在返回前落盘；设为 False 时刻意让
        数据滞留在 -wal 文件中，用于模拟迁移前未 checkpoint 的存量库

    :return Optional[sqlite3.Connection]: wal=True 且 checkpoint=False 时返回
        保持打开的写连接——调用方必须持有该连接直到断言结束再关闭，否则
        sqlite 在最后一个连接关闭时会自动 checkpoint，导致夹具失真；其余
        情况返回 None
    """
    conn = sqlite3.connect(str(path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA wal_autocheckpoint=0;")
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES ('c76c9a1f52dc')")
    for table in _FIXTURE_TABLES:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, payload TEXT)")
        conn.executemany(
            f"INSERT INTO {table} (payload) VALUES (?)",
            [(f"{table}-{i}",) for i in range(rows_per_table)],
        )
    conn.commit()
    if wal and not checkpoint:
        return conn
    conn.close()
    return None


def _table_row_counts(
    db_path: Path, tables: Tuple[str, ...] = _FIXTURE_TABLES
) -> Dict[str, int]:
    """
    读取数据库中若干表各自的行数

    :param db_path (Path): 数据库文件路径
    :param tables (Tuple[str, ...]): 待统计的表名

    :return Dict[str, int]: 表名到行数的映射
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        conn.close()


class TestRunLegacyMigration(TestCase):
    """
    测试 run_legacy_migration 的十种既定场景
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        注册假依赖并加载被测模块（全部用例共享同一份已加载模块）
        """
        _setup_mock_env()
        cls.module = _load_module("core.legacy_migration")

    def setUp(self) -> None:
        """
        每个用例使用独立临时目录，并重置假日志器避免跨用例串扰
        """
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

        self.target_dir = self.tmp_path / "data"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.target_path = self.target_dir / "plugin.db"

        self.fake_logger = _RecordingLogger()
        self.module.logger = self.fake_logger

        self._open_connections: List[sqlite3.Connection] = []
        self.addCleanup(self._close_open_connections)

    def _close_open_connections(self) -> None:
        for conn in self._open_connections:
            try:
                conn.close()
            except Exception:
                pass

    def _make_instance(self, is_clone: bool = False) -> FakePluginInstance:
        return FakePluginInstance(self.target_dir, is_clone=is_clone)

    # ---- 场景 1：全新安装 ----------------------------------------------

    def test_fresh_install_when_legacy_db_missing(self) -> None:
        """
        旧库不存在时不执行复制，必须打 WARNING 日志，目标库不被创建
        """
        missing_source = self.tmp_path / "legacy" / "not_there.db"
        instance = self._make_instance()

        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(missing_source)}
        )

        self.assertFalse(self.target_path.exists())
        self.assertTrue(
            self.fake_logger.warning_calls,
            "旧库不存在时必须打 WARNING 日志，而不是静默跳过",
        )

    # ---- 场景 2：存量迁移成功 --------------------------------------------

    def test_successful_migration_copies_all_data(self) -> None:
        """
        旧库存在且有数据时，目标库出现且逐表行数与源库一致，旧库原地保留
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"
        _create_legacy_db(source_path, rows_per_table=7)

        instance = self._make_instance()
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(source_path)}
        )

        self.assertTrue(self.target_path.exists())
        self.assertEqual(
            _table_row_counts(self.target_path),
            {table: 7 for table in _FIXTURE_TABLES},
        )

        self.assertTrue(source_path.exists(), "旧库不应被删除")
        self.assertEqual(
            _table_row_counts(source_path),
            {table: 7 for table in _FIXTURE_TABLES},
            "旧库中的数据不应被改变",
        )

    # ---- 场景 3：幂等 ------------------------------------------------------

    def test_skips_when_target_already_exists(self) -> None:
        """
        目标库已存在时直接跳过，不覆盖已有目标库内容
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"
        _create_legacy_db(source_path, rows_per_table=3)

        # 目标库已存在，且带有与源库不同的、可辨识的内容
        target_conn = sqlite3.connect(str(self.target_path))
        target_conn.execute("CREATE TABLE sentinel (id INTEGER)")
        target_conn.execute("INSERT INTO sentinel VALUES (999)")
        target_conn.commit()
        target_conn.close()

        instance = self._make_instance()
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(source_path)}
        )

        check_conn = sqlite3.connect(str(self.target_path))
        try:
            sentinel_value = check_conn.execute(
                "SELECT id FROM sentinel"
            ).fetchone()[0]
            table_names = {
                row[0]
                for row in check_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            check_conn.close()

        self.assertEqual(sentinel_value, 999, "已有目标库的内容不应被覆盖")
        self.assertNotIn(
            "files", table_names, "不应把源库的表写入已存在的目标库"
        )

    # ---- 场景 4：分身跳过 ----------------------------------------------

    def test_clone_instance_skips_migration_entirely(self) -> None:
        """
        分身（is_clone=True）不执行任何复制，目标库不产生
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"
        _create_legacy_db(source_path, rows_per_table=2)

        instance = self._make_instance(is_clone=True)
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(source_path)}
        )

        self.assertFalse(self.target_path.exists())
        self.assertEqual(
            instance.save_data_calls, [], "分身不应触发任何迁移相关的数据写入"
        )

    # ---- 场景 5：H1 自定义路径 --------------------------------------------

    def test_custom_plugin_db_path_from_config_is_honored(self) -> None:
        """
        config 中的自定义 PLUGIN_DB_PATH 优先于默认路径被读取和迁移

        回归点：若实现忽略 config 而写死默认路径，本用例中默认路径指向的
        文件并不存在，将被误判为「全新安装」，导致自定义路径下的存量数据
        永远不会被迁移
        """
        custom_dir = self.tmp_path / "user_customized_location"
        custom_dir.mkdir(parents=True, exist_ok=True)
        custom_source_path = custom_dir / "my_custom_name.db"
        _create_legacy_db(custom_source_path, rows_per_table=4)

        # 确认默认路径确实不存在，证明下面的成功迁移只能来自读取自定义路径
        self.assertFalse(_UNUSED_DEFAULT_DB_PATH.exists())

        instance = self._make_instance()
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(custom_source_path)}
        )

        self.assertTrue(self.target_path.exists())
        self.assertEqual(
            _table_row_counts(self.target_path),
            {table: 4 for table in _FIXTURE_TABLES},
        )

    # ---- 场景 6：H2 标记不得凌驾文件事实 ------------------------------------

    def test_stale_done_marker_does_not_block_migration(self) -> None:
        """
        KV 标记已是 done，但目标文件不存在时，仍然执行迁移

        回归点：判据必须始终是文件系统事实（目标文件是否存在），不能让
        插件数据里可能过期或误写的标记锁死迁移逻辑
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"
        _create_legacy_db(source_path, rows_per_table=6)

        instance = self._make_instance()
        # 预置一个「已完成」的旧标记，但目标库实际并不存在
        instance.save_data(
            self.module._MARKER_KEY,
            {"status": "done", "source": "stale", "target": "stale"},
        )
        self.assertFalse(self.target_path.exists())

        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(source_path)}
        )

        self.assertTrue(
            self.target_path.exists(), "标记为 done 不应阻止实际迁移的发生"
        )
        self.assertEqual(
            _table_row_counts(self.target_path),
            {table: 6 for table in _FIXTURE_TABLES},
        )

    # ---- 场景 7：崩溃残留清理 --------------------------------------------

    def test_stale_temp_file_is_cleaned_up(self) -> None:
        """
        目标目录中预置的迁移残留临时文件会在本次调用中被清理
        """
        stale_tmp = self.target_dir / "plugin.db.migrating.99999.tmp"
        stale_tmp.write_bytes(b"leftover from a crashed previous migration")
        self.assertTrue(stale_tmp.exists())

        instance = self._make_instance()
        # 源库也不存在，这里只关心清理动作本身，不关心迁移是否发生
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(self.tmp_path / "legacy" / "none.db")}
        )

        self.assertFalse(stale_tmp.exists(), "崩溃残留的临时文件应被清理")

    # ---- 场景 8：校验失败即中止 --------------------------------------------

    def test_corrupted_source_raises_and_leaves_no_target(self) -> None:
        """
        源库已损坏时函数 raise，且不留下半成品目标库或残留临时文件
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        corrupted_source = legacy_dir / "corrupted.db"
        corrupted_source.write_bytes(b"this is not a valid sqlite database" * 50)

        instance = self._make_instance()

        with self.assertRaises(RuntimeError):
            self.module.run_legacy_migration(
                instance, {"PLUGIN_DB_PATH": str(corrupted_source)}
            )

        self.assertFalse(
            self.target_path.exists(), "校验/迁移失败不应留下目标库半成品"
        )
        leftover_tmp = list(self.target_dir.glob("plugin.db.migrating.*.tmp"))
        self.assertEqual(leftover_tmp, [], "失败后不应残留迁移临时文件")

    # ---- 场景 9：逃生阀 --------------------------------------------------

    def test_skip_legacy_db_import_escape_hatch(self) -> None:
        """
        配置 skip_legacy_db_import=True 时跳过迁移，不报错
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"
        _create_legacy_db(source_path, rows_per_table=3)

        instance = self._make_instance()
        self.module.run_legacy_migration(
            instance,
            {"PLUGIN_DB_PATH": str(source_path), "skip_legacy_db_import": True},
        )

        self.assertFalse(self.target_path.exists())

    # ---- 场景 10：WAL 数据完整性（最关键） ----------------------------------

    def test_wal_data_not_yet_checkpointed_is_fully_migrated(self) -> None:
        """
        源库为 WAL 模式且大量数据仍滞留在 -wal 文件中未落盘时，迁移后
        目标库数据完整

        若实现遗漏对源库执行 PRAGMA wal_checkpoint(TRUNCATE) 而直接复制
        主文件，目标库将连表结构都没有——这是本模块设计上唯一不允许回归
        的场景
        """
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        source_path = legacy_dir / "p115strmhelper_file.db"

        row_count = 500
        writer_conn = _create_legacy_db(
            source_path, wal=True, rows_per_table=row_count, checkpoint=False
        )
        self.assertIsNotNone(writer_conn)
        self._open_connections.append(writer_conn)

        wal_file = Path(str(source_path) + "-wal")
        self.assertTrue(wal_file.exists())
        self.assertGreater(
            wal_file.stat().st_size, 0, "夹具应确保数据仍滞留在 -wal 文件中"
        )

        # 前置条件自检：以 immutable 模式只读主文件（忽略 -wal），确认此时
        # 主文件本身确实还没有任何表结构——证明夹具真实模拟了「未 checkpoint」
        raw_conn = sqlite3.connect(f"file:{source_path}?immutable=1", uri=True)
        try:
            raw_tables = raw_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        finally:
            raw_conn.close()
        self.assertEqual(
            raw_tables, [], "前置条件不成立：主文件不应在 checkpoint 前就有表结构"
        )

        instance = self._make_instance()
        self.module.run_legacy_migration(
            instance, {"PLUGIN_DB_PATH": str(source_path)}
        )

        self.assertTrue(self.target_path.exists())
        self.assertEqual(
            _table_row_counts(self.target_path),
            {table: row_count for table in _FIXTURE_TABLES},
            "WAL 中未落盘的数据必须完整出现在迁移后的目标库中",
        )

        # 源库自身的数据也应保持完整（checkpoint 是允许的写操作，但不能丢数据）
        self.assertEqual(
            _table_row_counts(source_path),
            {table: row_count for table in _FIXTURE_TABLES},
        )
