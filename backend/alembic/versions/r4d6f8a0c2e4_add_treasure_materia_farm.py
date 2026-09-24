"""add treasure hunt, materia sockets & farming

三个新系统：
- `materia_sockets`：账号级 11 个战斗装备栏位各 5 孔的镶嵌结果（不随装备更换）。
- `farm_plots`：种田田地（账号级，初始 2 片最多 10 片）；`users.farm_unlocked` 记录已解锁片数。
- `treasure_runs`：挖宝 5 层副本的服务端权威状态机（层数 / 门 / 宝箱 / 猜大小）。

只新增表与一列，不清空任何数据。

Revision ID: r4d6f8a0c2e4
Revises: q3c5e7a9b1d4
Create Date: 2026-09-24 14:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'r4d6f8a0c2e4'
down_revision = 'q3c5e7a9b1d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('farm_unlocked', sa.Integer(), nullable=False, server_default='2'))

    op.create_table(
        'materia_sockets',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('slot', sa.String(length=16), nullable=False),
        sa.Column('index', sa.Integer(), nullable=False),
        sa.Column('materia_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'slot', 'index', name='uq_materia_user_slot_index'),
    )
    op.create_index('ix_materia_sockets_user_id', 'materia_sockets', ['user_id'], unique=False)

    op.create_table(
        'farm_plots',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('index', sa.Integer(), nullable=False),
        sa.Column('seed_id', sa.String(length=32), nullable=True),
        sa.Column('planted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'index', name='uq_farm_user_index'),
    )
    op.create_index('ix_farm_plots_user_id', 'farm_plots', ['user_id'], unique=False)

    op.create_table(
        'treasure_runs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hero_id', sa.Integer(), nullable=True),
        sa.Column('floor', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('floor_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('card', sa.Integer(), nullable=True),
        sa.Column('multiplier', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('guesses_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('event_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('chest_opened', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ended_reason', sa.String(length=24), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['hero_id'], ['heroes.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_treasure_runs_user_id', 'treasure_runs', ['user_id'], unique=False)
    op.create_index('ix_treasure_runs_status', 'treasure_runs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_treasure_runs_status', table_name='treasure_runs')
    op.drop_index('ix_treasure_runs_user_id', table_name='treasure_runs')
    op.drop_table('treasure_runs')

    op.drop_index('ix_farm_plots_user_id', table_name='farm_plots')
    op.drop_table('farm_plots')

    op.drop_index('ix_materia_sockets_user_id', table_name='materia_sockets')
    op.drop_table('materia_sockets')

    op.drop_column('users', 'farm_unlocked')
