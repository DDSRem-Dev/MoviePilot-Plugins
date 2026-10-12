from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import Connection

from alembic import context


config = context.config


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=config.attributes.get("target_metadata"),
        render_as_batch=connection.dialect.name == "sqlite",
        include_object=config.attributes.get("include_object"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    优先复用宿主限定了插件 schema 的连接
    """
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("插件迁移需要在线连接以检查表结构")
else:
    run_migrations_online()
