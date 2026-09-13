from pathlib import Path


PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
"""
插件根目录

基于本文件位置动态解析，避免依赖宿主 `ROOT_PATH / app / plugins / <插件名>` 的
硬编码布局。MoviePilot V3 的插件安装路径与 V2 可能不同，硬编码会在其他部署
形态下解析到不存在的目录。
"""


def get_plugin_root() -> Path:
    """
    获取插件根目录

    :return Path: 插件根目录路径
    """
    return PLUGIN_ROOT


def get_database_dir() -> Path:
    """
    获取插件数据库结构目录

    :return Path: 插件 `database` 目录路径
    """
    return PLUGIN_ROOT / "database"


def get_versions_dir() -> Path:
    """
    获取插件数据库迁移脚本目录

    :return Path: 插件 `database/versions` 目录路径
    """
    return get_database_dir() / "versions"


def get_migration_meta_path() -> Path:
    """
    获取插件数据库迁移锚点文件路径

    :return Path: `migration_meta.json` 文件路径
    """
    return PLUGIN_ROOT / "migration_meta.json"
