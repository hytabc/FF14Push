"""add coop_records (expedition clear time and party battle info)

新增远征通关记录表：每次团队副本通关时，为每个真实参战账号写入一行，
保存通关时长与全席位的分角色战斗信息，用于「远征榜」。

Revision ID: k8c0e2f4a6b8
Revises: j7b9d1f3a5c7
Create Date: 2026-09-22 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'k8c0e2f4a6b8'
down_revision = 'j7b9d1f3a5c7'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'coop_records',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('battle_id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('dungeon_id', sa.String(length=32), nullable=False),
        sa.Column('mode', sa.String(length=12), nullable=False),
        sa.Column('had_clone', sa.Boolean(), nullable=False),
        sa.Column('clear_ms', sa.Integer(), nullable=False),
        sa.Column('party', JSON_TYPE, nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['battle_id'], ['coop_battles.id'], ondelete=None),
        sa.ForeignKeyConstraint(['room_id'], ['coop_rooms.id'], ondelete=None),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('battle_id', 'user_id', name='uq_coop_record'),
    )
    op.create_index('ix_coop_records_battle_id', 'coop_records', ['battle_id'], unique=False)
    op.create_index('ix_coop_records_user_id', 'coop_records', ['user_id'], unique=False)
    op.create_index('ix_coop_records_dungeon_id', 'coop_records', ['dungeon_id'], unique=False)
    op.create_index('ix_coop_record_dungeon_time', 'coop_records', ['dungeon_id', 'clear_ms'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_coop_record_dungeon_time', table_name='coop_records')
    op.drop_index('ix_coop_records_dungeon_id', table_name='coop_records')
    op.drop_index('ix_coop_records_user_id', table_name='coop_records')
    op.drop_index('ix_coop_records_battle_id', table_name='coop_records')
    op.drop_table('coop_records')
