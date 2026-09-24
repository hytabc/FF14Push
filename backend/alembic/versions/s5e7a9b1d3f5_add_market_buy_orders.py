"""add market_buy_orders (market buy orders / 收购单)

新增收购单表：发布者托管 `unit_price × quantity` 金币求购某堆叠物，卖家手动按
剩余数量部分成交（成交额抽手续费），未成交部分在下架 / 到期时退还。仅支持堆叠物，
不做自动撮合。

Revision ID: s5e7a9b1d3f5
Revises: r4d6f8a0c2e4
Create Date: 2026-09-24 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 's5e7a9b1d3f5'
down_revision = 'r4d6f8a0c2e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'market_buy_orders',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('buyer_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('item_key', sa.String(length=48), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('filled', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.BigInteger(), nullable=False),
        sa.Column('reference_price', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('buyer_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_market_buy_orders_buyer_id', 'market_buy_orders', ['buyer_id'], unique=False)
    op.create_index('ix_market_buy_orders_kind', 'market_buy_orders', ['kind'], unique=False)
    op.create_index('ix_market_buy_orders_item_key', 'market_buy_orders', ['item_key'], unique=False)
    op.create_index('ix_market_buy_orders_status', 'market_buy_orders', ['status'], unique=False)
    op.create_index(
        'ix_market_buy_orders_status_kind_price',
        'market_buy_orders',
        ['status', 'kind', 'unit_price'],
        unique=False,
    )
    op.create_index(
        'ix_market_buy_orders_buyer_status',
        'market_buy_orders',
        ['buyer_id', 'status'],
        unique=False,
    )
    op.create_index(
        'ix_market_buy_orders_status_expires',
        'market_buy_orders',
        ['status', 'expires_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_market_buy_orders_status_expires', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_buyer_status', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_status_kind_price', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_status', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_item_key', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_kind', table_name='market_buy_orders')
    op.drop_index('ix_market_buy_orders_buyer_id', table_name='market_buy_orders')
    op.drop_table('market_buy_orders')
