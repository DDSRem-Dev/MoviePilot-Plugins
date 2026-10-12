from alembic import op
import sqlalchemy as sa


revision = "p115v3_db_01"
down_revision = "c76c9a1f52dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    支持 PostgreSQL 的 64 位网盘标识并记录原子导入状态
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("files", "folders", "open_files", "open_folders", "life_event"):
            columns = ["id", "parent_id"]
            if table == "life_event":
                columns.append("file_id")
            for column in columns:
                op.alter_column(table, column, type_=sa.BigInteger())
    if not sa.inspect(bind).has_table("p115_legacy_import"):
        op.create_table(
            "p115_legacy_import",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("counts", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    """
    拒绝自动撤销数据导入标记或缩窄网盘标识
    """
    raise RuntimeError("V3 数据库不可自动降级，请使用升级前的备份恢复")
