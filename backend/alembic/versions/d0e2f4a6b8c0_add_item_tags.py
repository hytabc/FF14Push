"""add item tags

装备颜色标签：新增 item_tags 表（玩家自建命名标签，含颜色）与 items.tag_ids（标签 id 列表），
用于给装备打标并按标签筛选背包。

Revision ID: d0e2f4a6b8c0
Revises: c9d1e3f5a7b9
Create Date: 2026-09-21 13:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd0e2f4a6b8c0'
down_revision = 'c9d1e3f5a7b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'item_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=16), nullable=False),
        sa.Column('color', sa.String(length=16), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_item_tags_user_name'),
    )
    op.create_index(op.f('ix_item_tags_user_id'), 'item_tags', ['user_id'], unique=False)
    op.add_column(
        'items',
        sa.Column(
            'tag_ids',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column('items', 'tag_ids')
    op.drop_index(op.f('ix_item_tags_user_id'), table_name='item_tags')
    op.drop_table('item_tags')
