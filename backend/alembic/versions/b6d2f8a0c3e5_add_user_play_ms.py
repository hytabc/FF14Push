"""add users.play_ms (cumulative online time)

累计在线时长（毫秒），由各活动的服务端上报窗口累加。

Revision ID: b6d2f8a0c3e5
Revises: a5c1e7f9b2d4
Create Date: 2026-09-21 19:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'b6d2f8a0c3e5'
down_revision = 'a5c1e7f9b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('play_ms', sa.BigInteger(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'play_ms')
