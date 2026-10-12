"""1.0.0

Revision ID: 294b0079357e
Revises:
Create Date: 2025-01-20 23:43:40.741251

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
version = "1.0.0"
revision = "294b0079357e"
down_revision = None
branch_labels = ("p115strmhelper",)
depends_on = None


def upgrade() -> None:
    """
    初始化
    """
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("files"):
        op.create_table(
            "files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("parent_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(255)),
            sa.Column("sha1", sa.String(40)),
            sa.Column("size", sa.BigInteger()),
            sa.Column("pickcode", sa.String(50)),
            sa.Column("ctime", sa.BigInteger()),
            sa.Column("mtime", sa.BigInteger()),
            sa.Column("path", sa.Text(), unique=True),
            sa.Column("extra", sa.Text()),
        )
    if not inspector.has_table("folders"):
        op.create_table(
            "folders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("parent_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("path", sa.Text(), nullable=False, unique=True),
        )


def downgrade() -> None:
    """
    回滚
    """
    pass
