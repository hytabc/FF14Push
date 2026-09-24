"""add battle difficulty

地区战斗难度等级（周目制）：
- `users.battle_difficulty` / `users.battle_difficulty_max`：当前选择难度与已解锁上限。
- `region_progress.difficulty`：地区进度按难度隔离（唯一约束改为 user_id + difficulty + region_id）。
- `battle_sessions.difficulty`：会话建立时快照难度，上报校验按此值。

已有数据 difficulty 默认 0，原基础难度进度完整保留。

Revision ID: q3c5e7a9b1d4
Revises: p2b4d6f8a0c2
Create Date: 2026-09-24 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'q3c5e7a9b1d4'
down_revision = 'p2b4d6f8a0c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('battle_difficulty', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('battle_difficulty_max', sa.Integer(), nullable=False, server_default='0'))

    op.add_column('region_progress', sa.Column('difficulty', sa.Integer(), nullable=False, server_default='0'))
    with op.batch_alter_table('region_progress') as batch_op:
        batch_op.drop_constraint('uq_progress_user_region', type_='unique')
        batch_op.create_unique_constraint(
            'uq_progress_user_region_difficulty', ['user_id', 'difficulty', 'region_id']
        )

    op.add_column('battle_sessions', sa.Column('difficulty', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('battle_sessions', 'difficulty')

    with op.batch_alter_table('region_progress') as batch_op:
        batch_op.drop_constraint('uq_progress_user_region_difficulty', type_='unique')
        batch_op.create_unique_constraint('uq_progress_user_region', ['user_id', 'region_id'])
    op.drop_column('region_progress', 'difficulty')

    op.drop_column('users', 'battle_difficulty_max')
    op.drop_column('users', 'battle_difficulty')
