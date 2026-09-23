"""add market_listings (player-to-player market board)

新增玩家间交易板表：上架即从卖家背包 / 库存扣除进入托管，整单买断成交并抽取
手续费（金币回收），未售出到期自动退回卖家。

Revision ID: m1a2b3c4d5e6
Revises: l9d1f3a5c7ea
Create Date: 2026-09-23 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'm1a2b3c4d5e6'
down_revision = 'l9d1f3a5c7ea'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'market_listings',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('seller_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('item_key', sa.String(length=48), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('rarity', sa.String(length=16), nullable=True),
        sa.Column('category', sa.String(length=16), nullable=True),
        sa.Column('slot', sa.String(length=16), nullable=True),
        sa.Column('level_req', sa.Integer(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.BigInteger(), nullable=False),
        sa.Column('reference_price', sa.BigInteger(), nullable=False),
        sa.Column('snapshot', JSON_TYPE, nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('buyer_id', sa.Integer(), nullable=True),
        sa.Column('sold_price', sa.BigInteger(), nullable=True),
        sa.Column('fee', sa.BigInteger(), nullable=True),
        sa.Column('seller_ip', sa.String(length=64), nullable=True),
        sa.Column('buyer_ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_market_listings_seller_id', 'market_listings', ['seller_id'], unique=False)
    op.create_index('ix_market_listings_kind', 'market_listings', ['kind'], unique=False)
    op.create_index('ix_market_listings_item_key', 'market_listings', ['item_key'], unique=False)
    op.create_index('ix_market_listings_status', 'market_listings', ['status'], unique=False)
    op.create_index(
        'ix_market_listings_status_kind_price',
        'market_listings',
        ['status', 'kind', 'unit_price'],
        unique=False,
    )
    op.create_index(
        'ix_market_listings_seller_status',
        'market_listings',
        ['seller_id', 'status'],
        unique=False,
    )
    op.create_index(
        'ix_market_listings_status_expires',
        'market_listings',
        ['status', 'expires_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_market_listings_status_expires', table_name='market_listings')
    op.drop_index('ix_market_listings_seller_status', table_name='market_listings')
    op.drop_index('ix_market_listings_status_kind_price', table_name='market_listings')
    op.drop_index('ix_market_listings_status', table_name='market_listings')
    op.drop_index('ix_market_listings_item_key', table_name='market_listings')
    op.drop_index('ix_market_listings_kind', table_name='market_listings')
    op.drop_index('ix_market_listings_seller_id', table_name='market_listings')
    op.drop_table('market_listings')
