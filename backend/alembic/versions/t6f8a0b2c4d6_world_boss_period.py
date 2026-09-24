"""world boss: period-based settlement (add period_ends_at / kills)

世界BOSS 由「击杀周期」改为「讨伐周期」：周期内可反复讨伐（击杀只进入短暂休整、
cycle 不变），周期到时才 cycle+1 并结算。新增两列：

- `world_bosses.period_ends_at`：当前讨伐周期结束时间（epoch 秒）。
- `world_bosses.kills`：本周期已击杀次数（展示用）。

数据修正：把现有单行重置为新周期起点（cycle+1、满血、alive），使旧周期自动进入
「已结算」状态；历史贡献 / 奖励行全部保留，**只加列 / 只更新，不清空任何数据**。

Revision ID: t6f8a0b2c4d6
Revises: s5e7a9b1d3f5
Create Date: 2026-09-24 16:00:00.000000

"""
from __future__ import annotations

import time

from alembic import op
import sqlalchemy as sa

revision = 't6f8a0b2c4d6'
down_revision = 's5e7a9b1d3f5'
branch_labels = None
depends_on = None

# 与 shared/data/worldboss.json:periodSeconds 保持一致（迁移时用于初始化周期结束时间）。
PERIOD_SECONDS = 18000


def upgrade() -> None:
    op.add_column('world_bosses', sa.Column('period_ends_at', sa.Float(), nullable=True))
    op.add_column(
        'world_bosses',
        sa.Column('kills', sa.Integer(), nullable=False, server_default='0'),
    )

    now = time.time()
    op.execute(
        sa.text(
            "UPDATE world_bosses SET cycle = cycle + 1, status = 'alive', hp = max_hp, "
            "killed_at = NULL, respawn_at = NULL, kills = 0, "
            "period_ends_at = :ends, updated_at = :now"
        ).bindparams(ends=now + PERIOD_SECONDS, now=now)
    )


def downgrade() -> None:
    op.drop_column('world_bosses', 'kills')
    op.drop_column('world_bosses', 'period_ends_at')
