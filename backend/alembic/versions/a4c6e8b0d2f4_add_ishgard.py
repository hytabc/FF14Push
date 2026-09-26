"""add ishgard restoration (rebuild ishgard)

新增「重建伊修加德」玩法的 4 张表：

- `ishgard_state`：全局单行，轮次 / 阶段 / 全服阶段进度 / 称号窗口与两位称号持有者。
- `ishgard_members`：每账号累计总积分（跨轮次保留）。
- `ishgard_tools`：每账号每类（doh / dol）的可成长主手装备与紫色附魔。
- `ishgard_contributions`：每账号每轮的贡献积分（永久保留）。

只新增表，不清空任何数据。

Revision ID: a4c6e8b0d2f4
Revises: d5e7f9a1b3c5
Create Date: 2026-09-26 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a4c6e8b0d2f4'
down_revision = 'd5e7f9a1b3c5'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'ishgard_state',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('round', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('stage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('stage_points', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('stage_target', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('title_period_ends_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('saint_user_id', sa.Integer(), nullable=True),
        sa.Column('saint_since', sa.Float(), nullable=False, server_default='0'),
        sa.Column('apostle_user_id', sa.Integer(), nullable=True),
        sa.Column('apostle_since', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
    )

    op.create_table(
        'ishgard_members',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('points', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', name='uq_ishgard_member_user'),
    )
    op.create_index('ix_ishgard_members_user_id', 'ishgard_members', ['user_id'], unique=False)

    op.create_table(
        'ishgard_tools',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('pink_id', sa.String(length=48), nullable=True),
        sa.Column('pink_values', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('unlocked_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('user_id', 'kind', name='uq_ishgard_tool_user_kind'),
    )
    op.create_index('ix_ishgard_tools_user_id', 'ishgard_tools', ['user_id'], unique=False)

    op.create_table(
        'ishgard_contributions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('points', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('round', 'user_id', name='uq_ishgard_contribution'),
    )
    op.create_index('ix_ishgard_contributions_round', 'ishgard_contributions', ['round'], unique=False)
    op.create_index(
        'ix_ishgard_contributions_user_id', 'ishgard_contributions', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_ishgard_contributions_user_id', table_name='ishgard_contributions')
    op.drop_index('ix_ishgard_contributions_round', table_name='ishgard_contributions')
    op.drop_table('ishgard_contributions')
    op.drop_index('ix_ishgard_tools_user_id', table_name='ishgard_tools')
    op.drop_table('ishgard_tools')
    op.drop_index('ix_ishgard_members_user_id', table_name='ishgard_members')
    op.drop_table('ishgard_members')
    op.drop_table('ishgard_state')
