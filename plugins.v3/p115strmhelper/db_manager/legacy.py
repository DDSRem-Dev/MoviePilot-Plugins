from contextlib import closing
from json import dumps
from pathlib import Path
from sqlite3 import Connection, connect, SQLITE_BUSY, SQLITE_LOCKED
from tempfile import TemporaryDirectory
from typing import Dict, Optional
from time import monotonic

from sqlalchemy import func, select, text, inspect
from sqlalchemy.engine import Connection as TargetConnection

from app.sdk.database import PluginDatabaseHandle
from app.sdk.logging import logger

from .models import File, Folder, LifeEvent, OpenFile, OpenFolder


_TABLES = {
    model.__tablename__: model.__table__
    for model in (File, Folder, LifeEvent, OpenFile, OpenFolder)
}
_REVISIONS = {"294b0079357e", "2606909750bf", "d8dccb5dc598", "c76c9a1f52dc"}
_BACKUP_LOCK_TIMEOUT = 30


def validate_target_before_migration(handle: PluginDatabaseHandle) -> None:
    """
    在结构迁移前拒绝来源不明的已有数据，避免旧迁移先修改记录

    :param handle (PluginDatabaseHandle): 宿主管理的目标数据库
    """
    with handle.engine.connect() as target:
        tables = set(inspect(target).get_table_names())
        if "p115_legacy_import" in tables:
            if target.execute(
                text("SELECT id FROM p115_legacy_import WHERE id=1")
            ).first():
                return
        for name, table in _TABLES.items():
            if name in tables and target.scalar(
                select(func.count()).select_from(table)
            ):
                raise RuntimeError("V3 目标库已有数据但没有导入标记，拒绝迁移或覆盖")


def _backup_snapshot(source: Connection, snapshot: Connection) -> None:
    blocked_since: Optional[float] = None

    def check_progress(status: int, remaining: int, total: int) -> None:
        nonlocal blocked_since
        if status not in (SQLITE_BUSY, SQLITE_LOCKED):
            blocked_since = None
            return
        if blocked_since is None:
            blocked_since = monotonic()
        if monotonic() - blocked_since >= _BACKUP_LOCK_TIMEOUT:
            raise RuntimeError("旧版数据库持续被锁定，请停止旧版写入后重试")

    source.backup(snapshot, pages=1024, progress=check_progress, sleep=0.05)


def _validate_source(source: Connection) -> Dict[str, int]:
    result = source.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError(f"旧版数据库完整性校验失败: {result}")
    tables = {
        row[0]
        for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    unknown = tables - set(_TABLES) - {"alembic_version"}
    if unknown or not {"files", "folders"}.issubset(tables):
        raise RuntimeError("旧版数据库表结构无法识别，已停止导入")
    if "alembic_version" in tables:
        revisions = {
            row[0] for row in source.execute("SELECT version_num FROM alembic_version")
        }
        if revisions - _REVISIONS or len(revisions) > 1:
            raise RuntimeError(f"旧版数据库版本无法识别: {sorted(revisions)}")
    counts = {}
    for name, table in _TABLES.items():
        if name not in tables:
            continue
        columns = {row[1] for row in source.execute(f'PRAGMA table_info("{name}")')}
        if columns != set(table.columns.keys()):
            raise RuntimeError(f"旧版数据库 {name} 字段与已支持结构不一致")
        counts[name] = source.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    return counts


def _copy_rows(
    source: Connection, target: TargetConnection, counts: Dict[str, int]
) -> None:
    for name, count in counts.items():
        table = _TABLES[name]
        cursor = source.execute(f'SELECT * FROM "{name}"')
        columns = [item[0] for item in cursor.description]
        while rows := cursor.fetchmany(1000):
            target.execute(table.insert(), [dict(zip(columns, row)) for row in rows])
        actual = target.scalar(select(func.count()).select_from(table))
        if actual != count:
            raise RuntimeError(f"旧版数据库 {name} 导入数量不一致: {count} / {actual}")
        logger.info(f"【数据库迁移】{name} 已校验 {count} 行")


def import_legacy_database(
    handle: PluginDatabaseHandle, source_path: Path, is_clone: bool = False
) -> None:
    """
    将旧 SQLite 数据快照原子导入宿主管理的插件库

    源库以只读连接配合 SQLite backup API 读取，包括尚未 checkpoint 的 WAL
    导入数据与完成标记位于同一目标事务，失败后可重新执行且不修改原库
    分身与新安装也写入完成标记，避免未来误导入本体或迟到的旧库

    :param handle (PluginDatabaseHandle): 宿主提供的目标数据库
    :param source_path (Path): 旧版 SQLite 文件路径
    :param is_clone (bool): 是否为宿主分身实例
    """
    with handle.engine.begin() as target:
        if target.dialect.name == "postgresql":
            target.execute(text('LOCK TABLE "p115_legacy_import" IN EXCLUSIVE MODE'))
        else:
            target.exec_driver_sql("BEGIN IMMEDIATE")
        if target.execute(text("SELECT id FROM p115_legacy_import WHERE id=1")).first():
            return
        for table in _TABLES.values():
            if target.scalar(select(func.count()).select_from(table)):
                raise RuntimeError(
                    "V3 目标库已有数据但没有导入标记，请先核实来源，拒绝覆盖"
                )
        source_label = "clone" if is_clone else "new-install"
        counts = {}
        if not is_clone and source_path.exists():
            if handle.db_path and source_path.resolve() == handle.db_path.resolve():
                raise RuntimeError("旧版数据库路径与 V3 目标相同，拒绝自导入")
            if not source_path.is_file() or source_path.stat().st_size == 0:
                raise RuntimeError("旧版数据库不是有效文件，拒绝以空库继续初始化")
            with TemporaryDirectory(prefix="p115-v3-import-") as directory:
                snapshot_path = Path(directory) / "snapshot.db"
                with closing(
                    connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
                ) as source:
                    with closing(connect(snapshot_path)) as snapshot:
                        _backup_snapshot(source, snapshot)
                        counts = _validate_source(snapshot)
                        _copy_rows(snapshot, target, counts)
            source_label = str(source_path.resolve())
        target.execute(
            text(
                "INSERT INTO p115_legacy_import (id, source, counts) VALUES (1, :source, :counts)"
            ),
            {"source": source_label, "counts": dumps(counts, ensure_ascii=False)},
        )
