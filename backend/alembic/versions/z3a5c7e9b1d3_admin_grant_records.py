"""add admin grant records (compensation disclosure)

管理员发放金币补偿的记录，作为「补偿公示」的数据源（对全服玩家公开）。

- 独立于 `audit_logs`：公示需长期保留，而审计日志会被 retention 清理。
- 保存发放时的昵称快照与事由（事由对玩家公开）。

只新增一张表，不清空任何数据。

Revision ID: z3a5c7e9b1d3
Revises: y2f4a6b8c0d2
Create Date: 2026-09-25 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'z3a5c7e9b1d3'
down_revision = 'y2f4a6b8c0d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_grant_records',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('nickname', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('amount', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('admin_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index(
        'ix_admin_grant_records_user_id', 'admin_grant_records', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_admin_grant_records_user_id', table_name='admin_grant_records')
    op.drop_table('admin_grant_records')
