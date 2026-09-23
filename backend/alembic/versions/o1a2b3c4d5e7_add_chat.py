"""add chat (rolling hall messages, websocket tickets)

新增聊天室所需结构：
- `chat_messages`：单一大厅消息（普通发言 / 管理员公告）。聊天室不保留聊天记录，
  服务层只读取最近窗口内的行并在发言时清理过期行，表仅作滚动暂存。
- `chat_tickets`：WebSocket 一次性短时效票据（镜像 `coop_tickets`）。

Revision ID: o1a2b3c4d5e7
Revises: n1f2e3d4c5b6
Create Date: 2026-09-23 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'o1a2b3c4d5e7'
down_revision = 'n1f2e3d4c5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('text', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_messages_user_id', 'chat_messages', ['user_id'], unique=False)
    op.create_index('ix_chat_messages_created_at', 'chat_messages', ['created_at'], unique=False)

    op.create_table(
        'chat_tickets',
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('token'),
    )


def downgrade() -> None:
    op.drop_table('chat_tickets')

    op.drop_index('ix_chat_messages_created_at', table_name='chat_messages')
    op.drop_index('ix_chat_messages_user_id', table_name='chat_messages')
    op.drop_table('chat_messages')
