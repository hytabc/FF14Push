"""add heroes.egg_id and heroes.double_reward_charges (egg heroes)

彩蛋英雄：`egg_id` 记录英雄对应的彩蛋 id；`double_reward_charges`
记录「拔豆芽」剩余的奖励翻倍怪物数（服务端权威结算）。

Revision ID: f5a7c9e1b3d5
Revises: b6d2f8a0c3e5
Create Date: 2026-09-21 20:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'f5a7c9e1b3d5'
down_revision = 'b6d2f8a0c3e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('heroes', sa.Column('egg_id', sa.String(length=32), nullable=True))
    op.add_column(
        'heroes',
        sa.Column('double_reward_charges', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('heroes', 'double_reward_charges')
    op.drop_column('heroes', 'egg_id')
