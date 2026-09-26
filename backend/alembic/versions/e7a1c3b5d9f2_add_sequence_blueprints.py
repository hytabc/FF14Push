"""add sequence blueprints

生产 / 采集序列的自定义序列库：新增 sequence_blueprints 表（玩家保存的命名序列 + 可分享的蓝图ID）。

Revision ID: e7a1c3b5d9f2
Revises: d4f6a8b0c2e4
Create Date: 2026-09-26 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e7a1c3b5d9f2'
down_revision = 'd4f6a8b0c2e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sequence_blueprints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=24), nullable=False),
        sa.Column(
            'steps',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column('loop_mode', sa.String(length=8), nullable=False, server_default='once'),
        sa.Column('loop_total', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('share_code', sa.String(length=12), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_sequence_blueprints_user_name'),
    )
    op.create_index(
        op.f('ix_sequence_blueprints_user_id'), 'sequence_blueprints', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_sequence_blueprints_share_code'), 'sequence_blueprints', ['share_code'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_sequence_blueprints_share_code'), table_name='sequence_blueprints')
    op.drop_index(op.f('ix_sequence_blueprints_user_id'), table_name='sequence_blueprints')
    op.drop_table('sequence_blueprints')
