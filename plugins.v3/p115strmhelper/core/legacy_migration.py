import os
import sqlite3
from pathlib import Path
from shutil import copy2
from typing import Optional, Set

from app.sdk.logging import logger

from .config import ConfigManager

# 存量库涉及的 5 张表，迁移前后逐表行数比对；缺表（更早期库只有 files/folders）时跳过
_LEGACY_TABLES = ("files", "folders", "life_event", "open_files", "open_folders")

# 迁移过程临时文件名模式，与目标文件同目录（保证 os.replace 落地时同一文件系统）
_TMP_GLOB = "plugin.db.migrating.*.tmp"

# 迁移状态记录使用的插件数据 key，仅供可观测性排查，不作为是否迁移的判据
_MARKER_KEY = "legacy_db_migration"


def _resolve_legacy_source_path(config: Optional[dict]) -> Path:
    """
    解析 v2 遗留数据库的真实路径

    优先读取 init_plugin() 收到的持久化配置里的 PLUGIN_DB_PATH（v2 起可由用户通过
    高级配置覆盖的字段），持久化配置中没有该键时回落到 v2 的默认路径；不能用当前
    进程内 configer 单例的实时值代替——本函数调用时 configer 尚未套用本次传入的
    config，仍停留在构造函数阶段加载的默认值上

    :param config (Optional[Dict]): init_plugin() 收到的持久化配置字典

    :return Path: 解析出的 v2 遗留数据库路径
    """
    if isinstance(config, dict):
        raw_path = config.get("PLUGIN_DB_PATH")
        if raw_path:
            return Path(raw_path)
    return ConfigManager._get_default_plugin_db_path()


def _cleanup_stale_temp_files(target_dir: Path) -> None:
    """
    清理上一次迁移中断遗留的临时文件

    :param target_dir (Path): 新数据库所在目录
    """
    for stale in target_dir.glob(_TMP_GLOB):
        try:
            stale.unlink()
            logger.warning(f"【存量数据库迁移】已清理上次中断遗留的临时文件: {stale}")
        except OSError as error:
            logger.warning(f"【存量数据库迁移】清理临时文件 {stale} 失败: {error}")


def _checkpoint_source(source_path: Path) -> None:
    """
    对源库执行一次 WAL TRUNCATE checkpoint，确保主文件包含全部已提交数据

    这是本次迁移全程唯一允许对旧库执行的写操作：不做该操作直接复制 WAL 模式下的
    主文件，复制品可能连表结构都没有；非 WAL 模式下本操作是无害的空操作

    :param source_path (Path): 源数据库文件路径
    """
    conn = sqlite3.connect(str(source_path), timeout=30)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()
    finally:
        conn.close()


def _existing_table_names(conn: sqlite3.Connection) -> Set[str]:
    """
    返回数据库当前存在的用户表名集合

    :param conn (sqlite3.Connection): 数据库连接

    :return Set: 表名集合
    """
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _validate_copy(source_path: Path, copy_path: Path) -> None:
    """
    校验临时副本与源库一致

    只做 PRAGMA quick_check 与已知表的逐表行数比对，不做全量 integrity_check（大库
    上太慢）；源库缺失的表（更早期版本的库尚未建出 life_event/open_files 等表）视为
    合法状态，跳过该表的比对，交由后续 alembic upgrade head 补建

    :param source_path (Path): 源数据库文件路径
    :param copy_path (Path): 待校验的临时副本路径

    :raises RuntimeError: quick_check 未通过或存在行数不一致的表时抛出
    """
    copy_conn = sqlite3.connect(str(copy_path))
    try:
        check_result = copy_conn.execute("PRAGMA quick_check;").fetchone()
        if not check_result or check_result[0] != "ok":
            raise RuntimeError(f"存量数据库副本完整性校验失败: {check_result}")

        copy_tables = _existing_table_names(copy_conn)
        source_conn = sqlite3.connect(str(source_path))
        try:
            source_tables = _existing_table_names(source_conn)
            for table in _LEGACY_TABLES:
                if table not in source_tables:
                    continue
                if table not in copy_tables:
                    raise RuntimeError(f"存量数据库副本缺少表: {table}")
                source_count = source_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                copy_count = copy_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                if source_count != copy_count:
                    raise RuntimeError(
                        f"存量数据库副本表 {table} 行数不一致："
                        f"源库 {source_count} / 副本 {copy_count}"
                    )
        finally:
            source_conn.close()
    finally:
        copy_conn.close()


def run_legacy_migration(instance, config: Optional[dict]) -> None:
    """
    在 init_plugin() 最早期执行一次性存量数据库迁移

    必须是 init_plugin() 中最先执行的动作，且在本次调用返回前不得有任何代码路径
    触达 self.get_database()：该方法会立即在磁盘上建出（哪怕零表的）物理库文件，
    一旦先建出空文件，"目标文件是否存在" 这个判据就会被空文件污染，导致真正的
    存量数据永远不会被迁移

    分身（self.is_clone 为真）一律从空库起步，不做任何迁移。本体按"目标文件是否
    存在"这一文件系统事实作为唯一权威判据；插件数据里的迁移标记只用于可观测性
    排查，不参与是否跳过迁移的判定——先前哪怕误写过 "done"，只要目标文件不存在，
    仍然会重新尝试迁移

    :param instance: 插件主类实例，用于读取 is_clone 与取得新库所在目录
    :param config (Optional[Dict]): init_plugin() 收到的持久化配置字典

    :raises RuntimeError: 迁移失败且未显式开启 skip_legacy_db_import 时抛出
    """
    if getattr(instance, "is_clone", False):
        return

    target_dir = instance.get_data_path()
    target_path = target_dir / "plugin.db"
    _cleanup_stale_temp_files(target_dir)

    if target_path.exists():
        # 文件系统事实优先于一切 KV 标记：目标库已存在，视为迁移已完成或本就是
        # 全新安装产出的库，不再重复处理
        return

    source_path = _resolve_legacy_source_path(config)

    if not source_path.exists():
        logger.warning(
            f"【存量数据库迁移】未在 {source_path} 发现存量数据库，将以全新安装继续；"
            "如为老用户升级，请检查旧版 PLUGIN_DB_PATH 配置是否正确"
        )
        instance.save_data(_MARKER_KEY, {"status": "not_found", "source": str(source_path)})
        return

    if bool((config or {}).get("skip_legacy_db_import", False)):
        logger.warning(
            f"【存量数据库迁移】检测到存量数据库 {source_path}，但配置已显式开启 "
            "skip_legacy_db_import，跳过导入，存量数据不会出现在新库中"
        )
        instance.save_data(
            _MARKER_KEY, {"status": "skipped_by_config", "source": str(source_path)}
        )
        return

    tmp_path = target_dir / f"plugin.db.migrating.{os.getpid()}.tmp"
    try:
        logger.info(f"【存量数据库迁移】开始将 {source_path} 迁移到 {target_path}")
        _checkpoint_source(source_path)
        copy2(source_path, tmp_path)
        _validate_copy(source_path, tmp_path)
        os.replace(tmp_path, target_path)
        logger.info("【存量数据库迁移】迁移完成")
        instance.save_data(
            _MARKER_KEY,
            {"status": "done", "source": str(source_path), "target": str(target_path)},
        )
    except Exception as error:
        tmp_path.unlink(missing_ok=True)
        instance.save_data(
            _MARKER_KEY, {"status": "failed", "source": str(source_path), "error": str(error)}
        )
        logger.error(
            f"【存量数据库迁移】迁移失败: {error}；如确认旧库已损坏、同意放弃存量数据，"
            "可将插件配置 skip_legacy_db_import 显式设为 true 后重新加载插件",
            exc_info=True,
        )
        raise RuntimeError(f"存量数据库迁移失败，插件本次加载中止: {error}") from error
