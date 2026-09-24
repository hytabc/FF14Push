"""multi-account hard limits, session epoch and load-reduction indexes

并发降载 + 多账号硬限制所需结构：

- `users.session_epoch`：会话纪元，配合 JWT 的 `ep` 声明实现「同一账号单端登录」。
- `users.multi_online_blocked_at`：账号因「同一设备并发在线超限」被暂停非读请求的时刻。
- `user_devices.last_seen_at`：账号在某设备上最近的心跳 / 登录时间，用于并发在线判定。
- 复合索引：`activity_sessions(user_id, active)`、`battle_sessions(user_id, active)`、
  `chat_messages(kind, id)`，服务于互斥查询与 WS 增量广播。

见 services/devices.py、core/security.py。

Revision ID: w9c1e3f5a7b9
Revises: v8b0d2f4a6c8
Create Date: 2026-09-24 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'w9c1e3f5a7b9'
down_revision = 'v8b0d2f4a6c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('session_epoch', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'users',
        sa.Column('multi_online_blocked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'user_devices',
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'user_devices',
        sa.Column('online_since', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_user_devices_device_seen',
        'user_devices',
        ['device_id', 'last_seen_at'],
        unique=False,
    )
    op.create_index(
        'ix_activity_sessions_user_active',
        'activity_sessions',
        ['user_id', 'active'],
        unique=False,
    )
    op.create_index(
        'ix_battle_sessions_user_active',
        'battle_sessions',
        ['user_id', 'active'],
        unique=False,
    )
    op.create_index(
        'ix_chat_messages_kind_id',
        'chat_messages',
        ['kind', 'id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_chat_messages_kind_id', table_name='chat_messages')
    op.drop_index('ix_battle_sessions_user_active', table_name='battle_sessions')
    op.drop_index('ix_activity_sessions_user_active', table_name='activity_sessions')
    op.drop_index('ix_user_devices_device_seen', table_name='user_devices')
    op.drop_column('user_devices', 'online_since')
    op.drop_column('user_devices', 'last_seen_at')
    op.drop_column('users', 'multi_online_blocked_at')
    op.drop_column('users', 'session_epoch')
