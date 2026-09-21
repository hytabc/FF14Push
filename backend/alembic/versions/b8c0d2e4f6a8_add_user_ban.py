"""add user ban

封号：新增 users.banned / users.banned_at。封禁后登录与所有已认证请求都会被拒绝，
且不参与排行榜。

Revision ID: b8c0d2e4f6a8
Revises: c3d4e5f6a8b9
Create Date: 2026-09-21 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'b8c0d2e4f6a8'
down_revision = 'c3d4e5f6a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('banned', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('users', sa.Column('banned_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'banned_at')
    op.drop_column('users', 'banned')
