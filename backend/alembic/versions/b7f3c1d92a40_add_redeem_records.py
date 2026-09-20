"""add redeem records

Revision ID: b7f3c1d92a40
Revises: 451f3379f026
Create Date: 2026-09-20 18:20:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'b7f3c1d92a40'
down_revision = '451f3379f026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('redeem_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('gold', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'code', name='uq_redeem_user_code')
    )
    op.create_index(op.f('ix_redeem_records_user_id'), 'redeem_records', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_redeem_records_user_id'), table_name='redeem_records')
    op.drop_table('redeem_records')
