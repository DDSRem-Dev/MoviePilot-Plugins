import json
import importlib
from argparse import ArgumentParser
from configparser import ConfigParser
from pathlib import Path
from re import fullmatch
from tempfile import TemporaryDirectory

from alembic.config import Config as AlembicConfig
from alembic.command import revision as alembic_revision, upgrade as alembic_upgrade
from sqlalchemy import create_engine


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and name == "p115_legacy_import")


def generate_revision(version: str) -> str:
    """
    在临时 SQLite 基线上生成迁移草稿，不连接运行中的插件数据库

    草稿使用当前模型与随包迁移 head 比较，发布前仍需在 SQLite 和 PostgreSQL 验证
    数据导入标记表由显式迁移维护，不参与模型自动生成

    :param version (str): V3 数据库版本，格式为 3.x.x

    :return str: 生成的 revision 标识
    """
    if not fullmatch(r"3\.\d+\.\d+", version):
        raise ValueError("V3 数据库版本必须使用 3.x.x 格式")
    root = Path(__file__).resolve().parents[1]
    metadata_path = root / "migration_meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    plugin_package = __package__.rsplit(".", 1)[0]
    importlib.import_module(f"{plugin_package}.{metadata['models']}")
    models_base = importlib.import_module(
        f"{plugin_package}.db_manager"
    ).P115StrmHelperBase
    config = AlembicConfig()
    config.file_config = ConfigParser(interpolation=None)
    config.set_main_option("script_location", str(root / "database"))
    config.set_main_option("file_template", f"p115strmhelper-v{version}-%(rev)s")
    config.attributes["version"] = version
    with TemporaryDirectory(prefix="p115-v3-migration-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'baseline.db'}")
        try:
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                alembic_upgrade(config, "head")
                config.attributes["target_metadata"] = models_base.metadata
                config.attributes["include_object"] = _include_object
                script = alembic_revision(config, message=version, autogenerate=True)
        finally:
            engine.dispose()
    if script is None or isinstance(script, list):
        raise RuntimeError("迁移生成器未返回唯一 revision")
    metadata.update(version=version, revision=script.revision)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )
    return script.revision


def main() -> None:
    """
    解析版本参数并生成供人工复核的迁移草稿
    """
    parser = ArgumentParser(
        description="在 V3 宿主 Python 环境中生成插件数据库迁移草稿"
    )
    parser.add_argument("version", help="数据库版本，例如 3.0.1")
    arguments = parser.parse_args()
    print(f"已生成 revision: {generate_revision(arguments.version)}")


if __name__ == "__main__":
    main()
