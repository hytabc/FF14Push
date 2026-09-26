"""world boss: kill-count rewards (add world_boss_cycles)

世界BOSS 新增「击杀奖励」：按周期内 BOSS 击杀次数，给所有达标玩家发放固定件数。
周期换轮会把 `world_bosses.kills` 清零，故新增 `world_boss_cycles` 表记录每个周期
结束时的击杀次数，供结算时按周期号复算。

只新建表，不修改 / 不清空任何既有数据：世界BOSS 血量、周期与总伤害榜不随版本更新重置。

Revision ID: c1d2e3f4a5b6
Revises: e7a1c3b5d9f2
Create Date: 2026-09-26 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'e7a1c3b5d9f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'world_boss_cycles',
        sa.Column('cycle', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('boss_id', sa.Integer(), nullable=False),
        sa.Column('kills', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ended_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['boss_id'], ['world_bosses.id'], ondelete='CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('world_boss_cycles')
