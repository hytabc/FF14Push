"""add palace of the dead (deep dungeon roguelike)

新增「死者宫殿」玩法的 2 张表：

- `palace_profiles`：账号级进度——成长点余额、代币（烈火纹章 / 玻璃南瓜）、
  通关第 10 层次数、已解锁成长节点列表。
- `palace_runs`：每账号至多一份进行中的 run 快照——副本英雄 / 装备 / BUFF / 路径图 /
  当前节点 / 待领奖励 / 战斗校验快照。

只新增表，不清空任何数据。

Revision ID: b5d7f9a1c3e5
Revises: a4c6e8b0d2f4
Create Date: 2026-09-26 13:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b5d7f9a1c3e5'
down_revision = 'a4c6e8b0d2f4'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'palace_profiles',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('growth_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_growth_earned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('flame_crest', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('glass_pumpkin', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('floor10_clears', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unlocked', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', name='uq_palace_profile_user'),
    )
    op.create_index('ix_palace_profiles_user_id', 'palace_profiles', ['user_id'], unique=False)

    op.create_table(
        'palace_runs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='choosing_hero'),
        sa.Column('ended_reason', sa.String(length=24), nullable=True),
        sa.Column('floor', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('hero', JSON_TYPE, nullable=True),
        sa.Column('hero_candidates', JSON_TYPE, nullable=True),
        sa.Column('weapon_candidates', JSON_TYPE, nullable=True),
        sa.Column('map', JSON_TYPE, nullable=True),
        sa.Column('current_node', sa.String(length=16), nullable=True),
        sa.Column('items', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('equipped', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('buffs', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('run_gold', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pending_reward', JSON_TYPE, nullable=True),
        sa.Column('pending_node', JSON_TYPE, nullable=True),
        sa.Column('revive_left', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('snapshot', JSON_TYPE, nullable=True),
        sa.Column('node_started_at', sa.Float(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', name='uq_palace_run_user'),
    )
    op.create_index('ix_palace_runs_user_id', 'palace_runs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_palace_runs_user_id', table_name='palace_runs')
    op.drop_table('palace_runs')
    op.drop_index('ix_palace_profiles_user_id', table_name='palace_profiles')
    op.drop_table('palace_profiles')
