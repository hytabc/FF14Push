"""rescale sub attrs by tier

副属性改为随档位缩放（= ranges[品阶] × levelReq/95）后，需把存量装备
已存的副属性数值按同一系数重算，否则旧的低档装备仍会显示虚高战力。

只缩放 sub_attrs，base_attrs（本就按档位生成）与 terms 不动。

Revision ID: f3a5b7c9d1e2
Revises: e2b3c4d5f6a7
Create Date: 2026-09-20 23:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'f3a5b7c9d1e2'
down_revision = 'e2b3c4d5f6a7'
branch_labels = None
depends_on = None

# 与 shared/data/base-items.json 的 tiers[].subAttrScale 保持一致（迁移自包含，不 import 应用配置）。
TIER_SCALE = {0: 0.011, 1: 0.211, 2: 0.421, 3: 0.632, 4: 0.842, 5: 1.0}

items = sa.table(
    "items",
    sa.column("id", sa.Integer),
    sa.column("base_id", sa.String),
    sa.column("sub_attrs", sa.JSON().with_variant(JSONB, "postgresql")),
)


def _tier_of(base_id: str) -> int | None:
    """底材 id 末段即档位：w_<weaponType>_<tier> / a_<slot>_<tier> / c_<slot>_<tier>。"""
    try:
        return int(str(base_id).rsplit("_", 1)[-1])
    except (ValueError, AttributeError):
        return None


def _rescale(bind, factor_of) -> None:
    rows = bind.execute(sa.select(items.c.id, items.c.base_id, items.c.sub_attrs)).fetchall()
    for row_id, base_id, sub_attrs in rows:
        if not sub_attrs:
            continue
        tier = _tier_of(base_id)
        if tier is None:
            continue
        factor = factor_of(tier)
        if factor == 1.0:
            continue
        updated = [
            {**entry, "value": round(float(entry.get("value", 0)) * factor, 2)}
            for entry in sub_attrs
        ]
        bind.execute(items.update().where(items.c.id == row_id).values(sub_attrs=updated))


def upgrade() -> None:
    bind = op.get_bind()
    _rescale(bind, lambda tier: TIER_SCALE.get(tier, 1.0))


def downgrade() -> None:
    bind = op.get_bind()

    def inverse(tier: int) -> float:
        scale = TIER_SCALE.get(tier, 1.0)
        return 1.0 / scale if scale else 1.0

    _rescale(bind, inverse)
