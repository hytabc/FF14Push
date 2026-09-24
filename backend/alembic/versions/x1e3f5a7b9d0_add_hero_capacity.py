"""add hero roster capacity

远征队（英雄名册）容量扩充：

- `users.hero_capacity`：名册当前容量（席位数）。基准 8 席，可用金币扩充，
  每多开一席价格线性递增（首价 2500 万，之后每席 +2500 万），上限 20 席。
  见 services/roster.py 与 shared/data/heroes.json:roster。

只新增一列（默认 8），不清空任何数据。

Revision ID: x1e3f5a7b9d0
Revises: w9c1e3f5a7b9
Create Date: 2026-09-24 16:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'x1e3f5a7b9d0'
down_revision = 'w9c1e3f5a7b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('hero_capacity', sa.Integer(), nullable=False, server_default='8'),
    )


def downgrade() -> None:
    op.drop_column('users', 'hero_capacity')
