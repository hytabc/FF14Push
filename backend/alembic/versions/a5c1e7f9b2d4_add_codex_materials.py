"""add codex_materials table

材料图鉴：采集材料与半成品的永久解锁记录（鱼获复用 fish_records）。

Revision ID: a5c1e7f9b2d4
Revises: f2a4b6c8d0e2
Create Date: 2026-09-21 18:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'a5c1e7f9b2d4'
down_revision = 'f2a4b6c8d0e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'codex_materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(length=48), nullable=False),
        sa.Column('total_count', sa.Integer(), nullable=False),
        sa.Column('first_unlock_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'item_id', name='uq_codex_material'),
    )
    op.create_index(op.f('ix_codex_materials_item_id'), 'codex_materials', ['item_id'], unique=False)
    op.create_index(op.f('ix_codex_materials_user_id'), 'codex_materials', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_codex_materials_user_id'), table_name='codex_materials')
    op.drop_index(op.f('ix_codex_materials_item_id'), table_name='codex_materials')
    op.drop_table('codex_materials')
