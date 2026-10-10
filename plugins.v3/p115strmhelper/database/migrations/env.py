"""p115strmhelper 插件自管理数据库的 Alembic 迁移环境（v3 宿主形态）。

不依赖任何插件运行时模块（不导入 db_manager / P115StrmHelperBase）：本迁移树的全部
revision 脚本都用显式的 ``op.create_table`` / ``op.execute`` 编写，不依赖
``target_metadata`` 做 autogenerate diff，因此这里将其设为 None。

调用契约对齐 app/db/plugin/migration.py::run_migrations：
- SQLite（句柄独占引擎，owns_engine=True）：宿主只设置 ``sqlalchemy.url``，本 env.py
  需要自行从配置构建一个引擎并建立连接，即标准 Alembic 模板的 online 分支。
- PostgreSQL（句柄是宿主引擎按 schema_translate_map 派生的外观，owns_engine=False）：
  宿主把已限定 search_path 的连接放进 ``context.config.attributes["connection"]``，
  本 env.py 必须直接复用这条连接，绝不能自建引擎，否则迁移会落在 public schema。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 全部 revision 都是显式 DDL/DML，不做 autogenerate，故无需指向任何 ORM metadata
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 文本，不建立数据库连接。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：优先复用宿主注入的连接，没有注入时按 sqlalchemy.url 自建引擎。"""
    injected_connection = config.attributes.get("connection", None)
    if injected_connection is not None:
        # PostgreSQL 分支：连接已由宿主按 schema_translate_map 限定，事务边界与
        # commit 也由宿主（run_migrations）负责，这里只管跑迁移，不 close 连接
        context.configure(connection=injected_connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    # SQLite 分支：句柄独占引擎，宿主只传了 sqlalchemy.url，自建一次性引擎
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
