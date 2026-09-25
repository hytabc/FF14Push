"""auto sell fish setting (add fish_enabled / fish_kinds)

「设置」新增「自动卖鱼」：在既有 `auto_sell_settings`（与装备自动出售共用一行）上新增两列：

- `fish_enabled`：自动卖鱼开关（默认关闭，存量玩家行为不变）。
- `fish_kinds`：要自动出售的鱼档位集合（normal / king / emperor / legend），
  默认 `["normal"]`（与 shared/data/economy.json:sell.fishAutoSellKinds 一致）。

只加列，不改动任何既有数据；存量行的 `fish_enabled=false` 时档位不生效。

Revision ID: b8d0f2a4c6e8
Revises: f1a3c5e7b9d1
Create Date: 2026-09-25 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'b8d0f2a4c6e8'
down_revision = 'f1a3c5e7b9d1'
branch_labels = None
depends_on = None

DEFAULT_FISH_KINDS = '["normal"]'


def upgrade() -> None:
    op.add_column(
        'auto_sell_settings',
        sa.Column('fish_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'auto_sell_settings',
        sa.Column(
            'fish_kinds',
            sa.JSON().with_variant(JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_FISH_KINDS}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column('auto_sell_settings', 'fish_kinds')
    op.drop_column('auto_sell_settings', 'fish_enabled')
