"""add world_boss tables (shared-HP world boss, per-cycle contributions & rewards)

新增世界BOSS 相关表：全局共享血量（world_bosses）、每玩家战斗会话（world_boss_sessions）、
每账号每周期总伤害贡献（world_boss_contributions，榜单真相）、击杀结算幂等奖励
（world_boss_rewards）、WebSocket 一次性 ticket（world_boss_tickets）。

只新增表，不清空任何数据：世界BOSS 血量 / 周期 / 总伤害榜不随版本更新重置。

Revision ID: p2b4d6f8a0c2
Revises: o1a2b3c4d5e7
Create Date: 2026-09-24 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'p2b4d6f8a0c2'
down_revision = 'o1a2b3c4d5e7'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'world_bosses',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('boss_key', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('cycle', sa.Integer(), nullable=False),
        sa.Column('hp', sa.BigInteger(), nullable=False),
        sa.Column('max_hp', sa.BigInteger(), nullable=False),
        sa.Column('attack', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('killed_at', sa.Float(), nullable=True),
        sa.Column('respawn_at', sa.Float(), nullable=True),
        sa.Column('last_kill_by', sa.Integer(), nullable=True),
        sa.Column('config', JSON_TYPE, nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
    )
    op.create_index('ix_world_bosses_status', 'world_bosses', ['status'], unique=False)

    op.create_table(
        'world_boss_sessions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('boss_id', sa.Integer(), nullable=False),
        sa.Column('cycle', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('state', JSON_TYPE, nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('damage', sa.BigInteger(), nullable=False),
        sa.Column('heartbeat_at', sa.Float(), nullable=False),
        sa.Column('lease_owner', sa.String(length=64), nullable=True),
        sa.Column('lease_until', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['boss_id'], ['world_bosses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('cycle', 'user_id', name='uq_world_boss_session'),
    )
    op.create_index('ix_world_boss_sessions_status', 'world_boss_sessions', ['status'], unique=False)
    op.create_index('ix_world_boss_session_user', 'world_boss_sessions', ['user_id'], unique=False)

    op.create_table(
        'world_boss_contributions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('boss_id', sa.Integer(), nullable=False),
        sa.Column('cycle', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('damage', sa.BigInteger(), nullable=False),
        sa.Column('party', JSON_TYPE, nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['boss_id'], ['world_bosses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('cycle', 'user_id', name='uq_world_boss_contribution'),
    )
    op.create_index('ix_world_boss_contributions_user_id', 'world_boss_contributions', ['user_id'], unique=False)
    op.create_index('ix_world_boss_contribution_damage', 'world_boss_contributions', ['cycle', 'damage'], unique=False)

    op.create_table(
        'world_boss_rewards',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('boss_id', sa.Integer(), nullable=False),
        sa.Column('cycle', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('items', sa.Integer(), nullable=False),
        sa.Column('receipt', JSON_TYPE, nullable=False),
        sa.Column('claimed_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['boss_id'], ['world_bosses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('cycle', 'user_id', name='uq_world_boss_reward'),
    )
    op.create_index('ix_world_boss_rewards_user_id', 'world_boss_rewards', ['user_id'], unique=False)

    op.create_table(
        'world_boss_tickets',
        sa.Column('token', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('boss_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.ForeignKeyConstraint(['boss_id'], ['world_bosses.id'], ondelete=None),
    )


def downgrade() -> None:
    op.drop_table('world_boss_tickets')
    op.drop_index('ix_world_boss_rewards_user_id', table_name='world_boss_rewards')
    op.drop_table('world_boss_rewards')
    op.drop_index('ix_world_boss_contribution_damage', table_name='world_boss_contributions')
    op.drop_index('ix_world_boss_contributions_user_id', table_name='world_boss_contributions')
    op.drop_table('world_boss_contributions')
    op.drop_index('ix_world_boss_session_user', table_name='world_boss_sessions')
    op.drop_index('ix_world_boss_sessions_status', table_name='world_boss_sessions')
    op.drop_table('world_boss_sessions')
    op.drop_index('ix_world_bosses_status', table_name='world_bosses')
    op.drop_table('world_bosses')
