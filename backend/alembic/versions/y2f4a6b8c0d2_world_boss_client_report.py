"""add world boss client-side report cursor

世界BOSS 运算下放客户端：`world_boss_sessions` 新增两列，用于服务端校验上报。

- `last_report_at`：上次接受上报的服务端时间（epoch 秒），据此算上报窗口；
  客户端 `elapsedMs` 仅供参考，不参与额度计算（防加速 / 改系统时间）。
- `last_report_seq`：客户端单调递增的上报序号，用于幂等去重（重放不重复扣血 / 加贡献）。

只新增两列（默认 0），不清空任何数据。

Revision ID: y2f4a6b8c0d2
Revises: x1e3f5a7b9d0
Create Date: 2026-09-25 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'y2f4a6b8c0d2'
down_revision = 'x1e3f5a7b9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'world_boss_sessions',
        sa.Column('last_report_at', sa.Float(), nullable=False, server_default='0'),
    )
    op.add_column(
        'world_boss_sessions',
        sa.Column('last_report_seq', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('world_boss_sessions', 'last_report_seq')
    op.drop_column('world_boss_sessions', 'last_report_at')
