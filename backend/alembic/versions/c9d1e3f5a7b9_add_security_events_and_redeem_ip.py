"""add security events and redeem ip

反滥用：新增 security_events（按 IP 的滑动窗口限流事件，防多开 / 防刷），
并为 redeem_records 增加 ip（限制同一 IP 对同一兑换码的兑换次数）。

Revision ID: c9d1e3f5a7b9
Revises: b8c0d2e4f6a8
Create Date: 2026-09-21 13:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c9d1e3f5a7b9'
down_revision = 'b8c0d2e4f6a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'security_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scope', sa.String(length=32), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('occurred_at', sa.Float(), nullable=False),
    )
    op.create_index('ix_security_events_scope_key', 'security_events', ['scope', 'key'])

    op.add_column('redeem_records', sa.Column('ip', sa.String(length=64), nullable=True))
    op.create_index('ix_redeem_records_code_ip', 'redeem_records', ['code', 'ip'])


def downgrade() -> None:
    op.drop_index('ix_redeem_records_code_ip', table_name='redeem_records')
    op.drop_column('redeem_records', 'ip')
    op.drop_index('ix_security_events_scope_key', table_name='security_events')
    op.drop_table('security_events')
