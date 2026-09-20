"""add raid tables

Revision ID: c4d18a7e5b93
Revises: b7f3c1d92a40
Create Date: 2026-09-20 19:05:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c4d18a7e5b93'
down_revision = 'b7f3c1d92a40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('raid_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('raid_id', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('cleared', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_raid_sessions_user_id'), 'raid_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_raid_sessions_raid_id'), 'raid_sessions', ['raid_id'], unique=False)

    op.create_table('raid_progress',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('raid_id', sa.String(length=32), nullable=False),
    sa.Column('cleared', sa.Boolean(), nullable=False),
    sa.Column('cleared_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('best_clear_ms', sa.Integer(), nullable=True),
    sa.Column('clear_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'raid_id', name='uq_raid_progress')
    )
    op.create_index(op.f('ix_raid_progress_user_id'), 'raid_progress', ['user_id'], unique=False)
    op.create_index(op.f('ix_raid_progress_raid_id'), 'raid_progress', ['raid_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_raid_progress_raid_id'), table_name='raid_progress')
    op.drop_index(op.f('ix_raid_progress_user_id'), table_name='raid_progress')
    op.drop_table('raid_progress')
    op.drop_index(op.f('ix_raid_sessions_raid_id'), table_name='raid_sessions')
    op.drop_index(op.f('ix_raid_sessions_user_id'), table_name='raid_sessions')
    op.drop_table('raid_sessions')
