"""add user max_power (historical peak power)

战力榜改为按「玩家达到过的最高战力」排行：

- `users.max_power`：账号历史最高战力，只增不减。战力会随装备 / 等级变化，
  换下装备后当前战力会下降，但排行榜需要保留曾达到的最高值。
  见 services/valuation.raise_max_power 与 services/ranking._refresh_all_rankings。

只新增一列（默认 0），不清空任何数据；已有账号的峰值从下一次计算战力时开始累计。

Revision ID: d5e7f9a1b3c5
Revises: c1d2e3f4a5b6
Create Date: 2026-09-26 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'd5e7f9a1b3c5'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('max_power', sa.BigInteger(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'max_power')
