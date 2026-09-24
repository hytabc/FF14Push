"""add anti-alt (reg / last ip, user device linkage)

反多开所需结构：
- `users.reg_ip` / `users.last_ip`：注册 IP 与最近请求 IP（IP 维度关联判定）。
- `user_devices`：账号 ↔ 设备指纹（浏览器指纹）关联，用于「同一设备最多注册 N 个账号」
  以及关联账号之间的转账 / 交易板额度限制。见 services/devices.py。

Revision ID: u7a9c1e3b5d7
Revises: t6f8a0b2c4d6
Create Date: 2026-09-24 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'u7a9c1e3b5d7'
down_revision = 't6f8a0b2c4d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('reg_ip', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('last_ip', sa.String(length=64), nullable=True))

    op.create_table(
        'user_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=64), nullable=False),
        sa.Column('first_ip', sa.String(length=64), nullable=True),
        sa.Column('last_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'device_id', name='uq_user_device'),
    )
    op.create_index('ix_user_devices_user_id', 'user_devices', ['user_id'], unique=False)
    op.create_index('ix_user_devices_device', 'user_devices', ['device_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_devices_device', table_name='user_devices')
    op.drop_index('ix_user_devices_user_id', table_name='user_devices')
    op.drop_table('user_devices')
    op.drop_column('users', 'last_ip')
    op.drop_column('users', 'reg_ip')
