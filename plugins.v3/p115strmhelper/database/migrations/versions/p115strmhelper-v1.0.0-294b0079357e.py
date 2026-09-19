"""1.0.0

Revision ID: 294b0079357e
Revises:
Create Date: 2025-01-20 23:43:40.741251

建表 DDL 等价于 v2 时代 P115StrmHelperBase.metadata.create_all() 产出的初始
files / folders 两张表（字段与约束照抄 db_manager/models/file.py、folder.py，
两者在此版本之后从未再变过列）。v2 的实际建库流程是先 create_all 建表、再跑
alembic 盖戳，本 revision 原先的 upgrade() 因此是空操作；v3 宿主没有 create_all
这一步，纯 alembic 链条从空库出发若不补上这段 DDL，会在下一个 revision
（2606909750bf）对不存在的 files/folders 表执行 DELETE 时报错。

path 列的 unique=True 是刻意保留的重复约束：现有存量库的模型定义一直带着
unique=True，下一个 revision 又用 op.create_unique_constraint 显式加了同名
约束，两者叠加产生了重复的 UNIQUE(path)。新建库如果不复刻这一步，虽然表面更
“干净”，但会与全部存量库的实际 schema 不一致。

本 revision 只补建表，不改变 revision id / down_revision；对已经 stamp 过
294b0079357e 的存量库没有影响——alembic 不会对已应用的 revision 重新执行
upgrade()。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
version = "1.0.0"
revision = "294b0079357e"
down_revision = None
branch_labels = ("p115strmhelper",)
depends_on = None


def upgrade() -> None:
    """
    补建 v2 时代由 create_all() 产出的初始 files / folders 表
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("files"):
        op.create_table(
            "files",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("sha1", sa.String(length=40), nullable=True),
            sa.Column("size", sa.BigInteger(), nullable=True),
            sa.Column("pickcode", sa.String(length=50), nullable=True),
            sa.Column("ctime", sa.BigInteger(), nullable=True),
            sa.Column("mtime", sa.BigInteger(), nullable=True),
            sa.Column("path", sa.Text(), nullable=True),
            sa.Column("extra", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("path"),
        )

    if not inspector.has_table("folders"):
        op.create_table(
            "folders",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("path", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("path"),
        )


def downgrade() -> None:
    """
    回滚
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("folders"):
        op.drop_table("folders")
    if inspector.has_table("files"):
        op.drop_table("files")
