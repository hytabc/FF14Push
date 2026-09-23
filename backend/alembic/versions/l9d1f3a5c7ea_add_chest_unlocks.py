"""add chest unlocks

新增 `chest_unlocks`：记录账号一次性金币解锁的抽箱连抽档位（如 50 / 100 连）。
每个 (user_id, draw_count) 唯一；解锁后所有箱子通用。

Revision ID: l9d1f3a5c7ea
Revises: l9d1f3a5c7e9
Create Date: 2026-09-23 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'l9d1f3a5c7ea'
down_revision = 'l9d1f3a5c7e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('chest_unlocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('draw_count', sa.Integer(), nullable=False),
    sa.Column('unlocked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'draw_count', name='uq_chest_unlock_user_count')
    )
    op.create_index(op.f('ix_chest_unlocks_user_id'), 'chest_unlocks', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chest_unlocks_user_id'), table_name='chest_unlocks')
    op.drop_table('chest_unlocks')
