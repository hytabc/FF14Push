"""rename fishChancePct term desc to cover legend fish

提高特殊鱼概率的词条 `dolKingInstinct`（名称「渔王的直觉」）的说明由
「鱼王 / 鱼皇概率 +{v}%」改为「特殊鱼（鱼王 / 鱼皇 / 困难鱼）概率 +{v}%」，
明确困难鱼同样受益（服务端结算本就不区分特殊鱼档次）。

装备的 `terms` 是生成时快照，改配置不会更新已存档装备，需按同一文案重写，
否则旧装备仍显示旧说明。只改说明，stat / 数值 / 稀有度一律不动。

迁移自包含，不 import 应用配置。

Revision ID: f1a3c5e7b9d1
Revises: z3a5c7e9b1d3
Create Date: 2026-09-25 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'f1a3c5e7b9d1'
down_revision = 'z3a5c7e9b1d3'
branch_labels = None
depends_on = None

OLD_DESC = "鱼王 / 鱼皇概率 +{v}%"
NEW_DESC = "特殊鱼（鱼王 / 鱼皇 / 困难鱼）概率 +{v}%"

items = sa.table(
    "items",
    sa.column("id", sa.Integer),
    sa.column("terms", sa.JSON().with_variant(JSONB, "postgresql")),
)


def _rewrite(bind, old_desc: str, new_desc: str) -> None:
    """把 stat == fishChancePct 且说明为 old_desc 的词条改写为 new_desc。"""
    rows = bind.execute(sa.select(items.c.id, items.c.terms)).fetchall()
    for row_id, terms in rows:
        if not terms:
            continue
        changed = False
        updated = []
        for term in terms:
            if (
                isinstance(term, dict)
                and term.get("stat") == "fishChancePct"
                and term.get("desc") == old_desc
            ):
                updated.append({**term, "desc": new_desc})
                changed = True
            else:
                updated.append(term)
        if changed:
            bind.execute(items.update().where(items.c.id == row_id).values(terms=updated))


def upgrade() -> None:
    _rewrite(op.get_bind(), OLD_DESC, NEW_DESC)


def downgrade() -> None:
    _rewrite(op.get_bind(), NEW_DESC, OLD_DESC)
