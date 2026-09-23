"""add friends (friend code, presence, friendships, coin transfers)

新增好友系统所需结构：
- `users.friend_code`：唯一好友码（旧数据在迁移中回填）。
- `users.last_seen_at`：在线状态依据（前端心跳刷新）。
- `friendships`：方向化好友关系（pending / accepted）。
- `coin_transfers`：好友金币转账流水（审计 + 每日累计额度）。

Revision ID: n1f2e3d4c5b6
Revises: m1a2b3c4d5e6
Create Date: 2026-09-23 11:00:00.000000

"""
from __future__ import annotations

import secrets

from alembic import op
import sqlalchemy as sa

revision = 'n1f2e3d4c5b6'
down_revision = 'm1a2b3c4d5e6'
branch_labels = None
depends_on = None

# 8 位易读字符：排除 0/O/1/I/L 等易混字符
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _new_code(existing: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
        if code not in existing:
            existing.add(code)
            return code


def _backfill_friend_codes() -> None:
    bind = op.get_bind()
    existing: set[str] = {
        code for code in bind.execute(
            sa.text("SELECT friend_code FROM users WHERE friend_code IS NOT NULL")
        ).scalars()
    }
    user_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM users ORDER BY id")).fetchall()]
    for user_id in user_ids:
        bind.execute(
            sa.text("UPDATE users SET friend_code = :code WHERE id = :id"),
            {"code": _new_code(existing), "id": user_id},
        )


def upgrade() -> None:
    op.add_column('users', sa.Column('friend_code', sa.String(length=12), nullable=True))
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    _backfill_friend_codes()
    op.create_index('ix_users_friend_code', 'users', ['friend_code'], unique=True)

    op.create_table(
        'friendships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('requester_id', sa.Integer(), nullable=False),
        sa.Column('addressee_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['requester_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['addressee_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('requester_id', 'addressee_id', name='uq_friendship_pair'),
    )
    op.create_index('ix_friendships_requester_id', 'friendships', ['requester_id'], unique=False)
    op.create_index('ix_friendships_addressee_id', 'friendships', ['addressee_id'], unique=False)
    op.create_index(
        'ix_friendships_requester_status', 'friendships', ['requester_id', 'status'], unique=False
    )
    op.create_index(
        'ix_friendships_addressee_status', 'friendships', ['addressee_id', 'status'], unique=False
    )

    op.create_table(
        'coin_transfers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_user_id', sa.Integer(), nullable=False),
        sa.Column('to_user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('fee', sa.BigInteger(), nullable=False),
        sa.Column('net', sa.BigInteger(), nullable=False),
        sa.Column('from_ip', sa.String(length=64), nullable=True),
        sa.Column('to_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['from_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_coin_transfers_from_user_id', 'coin_transfers', ['from_user_id'], unique=False)
    op.create_index('ix_coin_transfers_to_user_id', 'coin_transfers', ['to_user_id'], unique=False)
    op.create_index(
        'ix_coin_transfers_from_created', 'coin_transfers', ['from_user_id', 'created_at'], unique=False
    )
    op.create_index(
        'ix_coin_transfers_to_created', 'coin_transfers', ['to_user_id', 'created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_coin_transfers_to_created', table_name='coin_transfers')
    op.drop_index('ix_coin_transfers_from_created', table_name='coin_transfers')
    op.drop_index('ix_coin_transfers_to_user_id', table_name='coin_transfers')
    op.drop_index('ix_coin_transfers_from_user_id', table_name='coin_transfers')
    op.drop_table('coin_transfers')

    op.drop_index('ix_friendships_addressee_status', table_name='friendships')
    op.drop_index('ix_friendships_requester_status', table_name='friendships')
    op.drop_index('ix_friendships_addressee_id', table_name='friendships')
    op.drop_index('ix_friendships_requester_id', table_name='friendships')
    op.drop_table('friendships')

    op.drop_index('ix_users_friend_code', table_name='users')
    op.drop_column('users', 'last_seen_at')
    op.drop_column('users', 'friend_code')
