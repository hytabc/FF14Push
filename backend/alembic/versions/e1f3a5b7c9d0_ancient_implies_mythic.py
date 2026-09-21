"""ancient implies mythic

规则：任何带「太古」属性的英雄都必定为神话（红色）资质（无论是否保底触发）。
存量数据里存在「自然命中太古但资质非神话」的英雄与酒馆候选，这里统一归一为神话。

只改 talent，不重掷三维（点数已是既成事实，重掷会改变战力）。

Revision ID: e1f3a5b7c9d0
Revises: d0e2f4a6b8c0
Create Date: 2026-09-21 14:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'e1f3a5b7c9d0'
down_revision = 'd0e2f4a6b8c0'
branch_labels = None
depends_on = None

MYTHIC = "mythic"

heroes = sa.table(
    "heroes",
    sa.column("id", sa.Integer),
    sa.column("talent", sa.String),
    sa.column("ancient_attr", sa.String),
)

tavern = sa.table(
    "tavern",
    sa.column("id", sa.Integer),
    sa.column("candidate", sa.JSON().with_variant(JSONB, "postgresql")),
    sa.column("multi_candidates", sa.JSON().with_variant(JSONB, "postgresql")),
)


def _fix_candidate(candidate):
    """候选（dict）：带太古属性但资质非神话 → 改为神话。"""
    if isinstance(candidate, dict) and candidate.get("ancientAttr") and candidate.get("talent") != MYTHIC:
        return {**candidate, "talent": MYTHIC}
    return candidate


def _fix_multi(multi):
    if not isinstance(multi, list):
        return multi
    fixed = [_fix_candidate(item) for item in multi]
    return fixed if fixed != multi else multi


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        heroes.update()
        .where(heroes.c.ancient_attr.isnot(None))
        .where(heroes.c.talent != MYTHIC)
        .values(talent=MYTHIC)
    )

    rows = bind.execute(sa.select(tavern.c.id, tavern.c.candidate, tavern.c.multi_candidates)).fetchall()
    for row_id, candidate, multi in rows:
        new_candidate, new_multi = _fix_candidate(candidate), _fix_multi(multi)
        if new_candidate != candidate or new_multi != multi:
            bind.execute(
                tavern.update()
                .where(tavern.c.id == row_id)
                .values(candidate=new_candidate, multi_candidates=new_multi)
            )


def downgrade() -> None:
    # 数据归一不可逆：原资质未保留，无法还原。
    pass
