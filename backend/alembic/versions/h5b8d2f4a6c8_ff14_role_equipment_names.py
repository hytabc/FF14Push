"""rename equipment names to FF14 role affixes

底材变体名由属性词（力量/敏捷/智力/坦克/体力/财富/暴击/直击/信念/均衡）改为
FF14 官方职能装备词缀（强袭/游击/咏咒/御敌/精准/制敌/治愈），装备名格式为
「档位 + 职能 + 部位」（如「精金强袭铠甲」）。

已存档装备的 name 是生成时快照，需同步重命名，否则旧装备仍显示旧属性词。
只有中段变体词会变，档位（铁制…终末）与部位后缀（头盔…戒指）都不含这些词，
按词替换即可。同一旧词（均衡）在防具/武器上映射不同，故按 base_id 前缀分表。

迁移自包含，不 import 应用配置。

Revision ID: h5b8d2f4a6c8
Revises: a7c9e1b3d5f7
Create Date: 2026-09-22 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'h5b8d2f4a6c8'
down_revision = 'a7c9e1b3d5f7'
branch_labels = None
depends_on = None

# 旧变体词 → 新职能词缀，与 shared/data/base-items.json 的 variants[].name 一一对应。
WEAPON = [
    ("暴击", "精准"),
    ("直击", "强袭"),
    ("信念", "制敌"),
    ("均衡", "游击"),
]
ARMOR = [
    ("力量", "强袭"),
    ("敏捷", "游击"),
    ("智力", "咏咒"),
    ("坦克", "御敌"),
    ("暴击", "精准"),
    ("信念", "制敌"),
    ("均衡", "治愈"),
]
ACCESSORY = [
    ("力量", "强袭"),
    ("敏捷", "游击"),
    ("智力", "咏咒"),
    ("体力", "御敌"),
    ("财富", "精准"),
]

items = sa.table(
    "items",
    sa.column("id", sa.Integer),
    sa.column("base_id", sa.String),
    sa.column("name", sa.String),
)


def _table_for(base_id: str) -> list[tuple[str, str]] | None:
    """装备类别 → 词表：w_ 武器 / a_ 防具 / c_ 饰品；专用装备（dh_…）等返回 None。"""
    if base_id.startswith("w_"):
        return WEAPON
    if base_id.startswith("a_"):
        return ARMOR
    if base_id.startswith("c_"):
        return ACCESSORY
    return None


def _rename(bind, mapping_of) -> None:
    rows = bind.execute(sa.select(items.c.id, items.c.base_id, items.c.name)).fetchall()
    for row_id, base_id, name in rows:
        table = _table_for(str(base_id))
        if table is None:
            continue
        renamed = name
        for old, new in mapping_of(table):
            if old in renamed:
                renamed = renamed.replace(old, new)
        if renamed != name:
            bind.execute(items.update().where(items.c.id == row_id).values(name=renamed))


def upgrade() -> None:
    _rename(op.get_bind(), lambda table: table)


def downgrade() -> None:
    _rename(op.get_bind(), lambda table: [(new, old) for old, new in table])
