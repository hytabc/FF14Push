"""add dohdol (crafting/gathering) tables

新增生产/采集 DLC 的表与 items.high_quality 列。

Revision ID: f2a4b6c8d0e2
Revises: e1f3a5b7c9d0
Create Date: 2026-09-21 16:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'f2a4b6c8d0e2'
down_revision = 'e1f3a5b7c9d0'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.add_column(
        'items',
        sa.Column('high_quality', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'dohdol_progress',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('exp', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'kind', name='uq_dohdol_user_kind'),
    )
    op.create_index(op.f('ix_dohdol_progress_user_id'), 'dohdol_progress', ['user_id'], unique=False)

    op.create_table(
        'stack_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('item_id', sa.String(length=48), nullable=False),
        sa.Column('count', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'kind', 'item_id', name='uq_stack_user_kind_item'),
    )
    op.create_index(op.f('ix_stack_items_user_id'), 'stack_items', ['user_id'], unique=False)

    op.create_table(
        'activity_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('job_id', sa.String(length=8), nullable=False),
        sa.Column('region_id', sa.Integer(), nullable=True),
        sa.Column('recipe_id', sa.String(length=48), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('last_report_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('credit', sa.Float(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('total_actions', sa.BigInteger(), nullable=False),
        sa.Column('insight_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('session_fish', JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_activity_sessions_user_id'), 'activity_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_activity_sessions_active'), 'activity_sessions', ['active'], unique=False)

    op.create_table(
        'fish_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fish_id', sa.String(length=48), nullable=False),
        sa.Column('region_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('count', sa.BigInteger(), nullable=False),
        sa.Column('max_size', sa.Integer(), nullable=False),
        sa.Column('first_caught_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'fish_id', name='uq_fish_user_fish'),
    )
    op.create_index(op.f('ix_fish_records_user_id'), 'fish_records', ['user_id'], unique=False)
    op.create_index(op.f('ix_fish_records_fish_id'), 'fish_records', ['fish_id'], unique=False)

    op.create_table(
        'active_consumables',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('item_id', sa.String(length=48), nullable=False),
        sa.Column('effects', JSON_TYPE, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'kind', name='uq_consumable_user_kind'),
    )
    op.create_index(op.f('ix_active_consumables_user_id'), 'active_consumables', ['user_id'], unique=False)

    op.create_table(
        'user_titles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title_id', sa.String(length=48), nullable=False),
        sa.Column('unlocked_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'title_id', name='uq_title_user_title'),
    )
    op.create_index(op.f('ix_user_titles_user_id'), 'user_titles', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_titles_user_id'), table_name='user_titles')
    op.drop_table('user_titles')
    op.drop_index(op.f('ix_active_consumables_user_id'), table_name='active_consumables')
    op.drop_table('active_consumables')
    op.drop_index(op.f('ix_fish_records_fish_id'), table_name='fish_records')
    op.drop_index(op.f('ix_fish_records_user_id'), table_name='fish_records')
    op.drop_table('fish_records')
    op.drop_index(op.f('ix_activity_sessions_active'), table_name='activity_sessions')
    op.drop_index(op.f('ix_activity_sessions_user_id'), table_name='activity_sessions')
    op.drop_table('activity_sessions')
    op.drop_index(op.f('ix_stack_items_user_id'), table_name='stack_items')
    op.drop_table('stack_items')
    op.drop_index(op.f('ix_dohdol_progress_user_id'), table_name='dohdol_progress')
    op.drop_table('dohdol_progress')
    op.drop_column('items', 'high_quality')
