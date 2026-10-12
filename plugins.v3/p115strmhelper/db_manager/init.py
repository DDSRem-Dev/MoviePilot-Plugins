from pathlib import Path
from typing import Any

from app.db.plugin.registry import ensure_database
from app.sdk.logging import logger

from .legacy import import_legacy_database, validate_target_before_migration


def initialize_database(plugin: Any, legacy_path: Path) -> None:
    """
    使用宿主迁移入口初始化插件库并导入旧版数据

    宿主首次加载在 init_plugin 返回后建库，配置重载不重复建库
    后台线程在 init_plugin 内启动，因此必须先完成同一宿主建库流程

    :param plugin (Any): 已绑定的插件实例
    :param legacy_path (Path): V2 配置指定的 SQLite 源库
    """
    plugin_id = plugin.__class__.__name__
    handle = plugin.get_database()
    if handle.db_path and Path(legacy_path).resolve() == handle.db_path.resolve():
        raise RuntimeError("旧版数据库路径与 V3 目标相同，拒绝修改源库")
    validate_target_before_migration(handle)
    ensure_database(plugin_id, migrations=Path(plugin.get_database_migrations()))
    import_legacy_database(
        handle,
        Path(legacy_path),
        is_clone=bool(plugin.is_clone),
    )
    logger.info(f"插件 {plugin_id} 数据库已就绪")
