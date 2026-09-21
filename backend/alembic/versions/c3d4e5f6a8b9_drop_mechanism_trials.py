"""drop mechanism trials

取消「机制试炼」：地区不再要求本地区试炼，高难副本也不再要求试炼。
移除此功能专用的 mechanism_trials 表（historical clears / rewards 不受影响）。

Revision ID: c3d4e5f6a8b9
Revises: g4b6c8d0e2f4
Create Date: 2026-09-21 11:20:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a8b9'
down_revision = 'g4b6c8d0e2f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('mechanism_trials')


def downgrade() -> None:
    op.create_table('mechanism_trials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(40), nullable=False),
        sa.Column('version', sa.String(20), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False),
        sa.Column('challenge', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_mechanism_trials_user_id', 'mechanism_trials', ['user_id'])
