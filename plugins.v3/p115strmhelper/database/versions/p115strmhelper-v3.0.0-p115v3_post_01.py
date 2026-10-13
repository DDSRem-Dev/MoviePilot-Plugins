from alembic import op
import sqlalchemy as sa


revision = "p115v3_post_01"
down_revision = "p115v3_db_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    建立整理后处理事件检查点和本地资源归属表
    """
    op.create_table(
        "transfer_postprocess",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
    )
    op.create_table(
        "transfer_resource",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """
    拒绝删除保护事件重放所需的归属记录
    """
    raise RuntimeError("后处理记录不可自动降级，请使用升级前的备份恢复")
