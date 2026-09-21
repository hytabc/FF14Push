"""add activity_sessions.target_actions (制造 X 个 / 全部)

生产会话的目标制造件数：「制作X个」填 X，「制作全部」填当前材料可制造的上限；
达成后服务端自动结束会话。NULL = 不设上限（旧会话 / 采集 / 钓鱼）。

Revision ID: a7c9e1b3d5f7
Revises: f5a7c9e1b3d5
Create Date: 2026-09-21 23:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'a7c9e1b3d5f7'
down_revision = 'f5a7c9e1b3d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'activity_sessions',
        sa.Column('target_actions', sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('activity_sessions', 'target_actions')
