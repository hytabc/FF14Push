"""add raid daily reward limit

新增 `raid_progress.reward_day` / `rewarded_today`：每个账号每个副本每天可获得奖励的
通关次数计数（首通计入），跨天清零，用于防止反复通关刷取奖励。不重写历史数据。

Revision ID: l9d1f3a5c7e9
Revises: k8c0e2f4a6b8
Create Date: 2026-09-22 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'l9d1f3a5c7e9'
down_revision = 'k8c0e2f4a6b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('raid_progress', sa.Column('reward_day', sa.Date(), nullable=True))
    op.add_column(
        'raid_progress',
        sa.Column('rewarded_today', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('raid_progress', 'rewarded_today')
    op.drop_column('raid_progress', 'reward_day')
