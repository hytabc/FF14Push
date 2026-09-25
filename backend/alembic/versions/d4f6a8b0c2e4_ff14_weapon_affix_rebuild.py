"""rebuild weapon base ids to FF14 role affixes

武器变体由「跨职业通用的 精准/强袭/制敌/游击」改为「按自身职业的职能词缀」
（见 shared/data/base-items.json:jobAffixes）：每种武器每档只剩「基础型 + 自身职能」两个变体。
存量武器的旧通用变体底材 id 已不存在，需重映射到自身职业的职能变体并同步名称；
基础型（无前缀）id 不变。

存量引用底材 id 的位置（已核对，仅此三处）：
  - items.base_id / name
  - codex_equipment.base_id —— 唯一约束 (user_id, base_id)，重映射后会撞车，需去重合并
  - market_listings(kind='equipment') 的 item_key / name / snapshot.baseId / snapshot.name
（hero_registrations / coop_seats / world_boss party 存的是英雄快照，不含底材 id；raid.pending_chest 为整数计数。）

迁移自包含（不 import 应用配置）；已存的 sub_attrs / terms 视为快照，不重 roll。

Revision ID: d4f6a8b0c2e4
Revises: b8d0f2a4c6e8
Create Date: 2026-09-25 00:00:00.000000

"""
from __future__ import annotations

from typing import Callable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd4f6a8b0c2e4'
down_revision = 'b8d0f2a4c6e8'
branch_labels = None
depends_on = None

# ── 词表（与 shared/data/base-items.json 保持一致）─────────────────────────────
# 武器族 → 自身职业的职能词缀 id
WEAPON_AFFIX = {
    "sword_shield": "tank", "axe": "tank", "greatsword": "tank", "gunblade": "tank",
    "fist": "str", "katana": "str",
    "lance": "det", "scythe": "det",
    "dualDagger": "dex", "twinblade": "dex",
    "bow": "crit", "gun": "crit", "chakram": "crit",
    "rod": "int", "grimoire": "int", "rapier": "int", "brush": "int",
    "staff": "bal", "book": "bal", "globe": "bal", "noulith": "bal",
}
# 武器族 → 部位后缀
WEAPON_SUFFIX = {
    "sword_shield": "长剑", "axe": "战斧", "greatsword": "大剑", "gunblade": "枪刃",
    "fist": "拳套", "lance": "长枪", "dualDagger": "双剑", "katana": "武士刀",
    "scythe": "镰刀", "twinblade": "双刃剑", "bow": "弓", "gun": "火枪", "chakram": "轮刃",
    "rod": "咒杖", "grimoire": "魔典", "rapier": "刺剑", "brush": "画笔",
    "staff": "法杖", "book": "魔导书", "globe": "天球仪", "noulith": "蛇刺剑",
}
AFFIX_NAME = {
    "tank": "御敌", "str": "强袭", "det": "制敌", "dex": "游击",
    "crit": "精准", "int": "咏咒", "bal": "治愈",
}
TIER_NAME = {
    0: "铁制", 1: "白钢", 2: "秘银", 3: "钛合金", 4: "精金",
    5: "龙鳞", 6: "苍穹", 7: "星辉", 8: "终末", 9: "绝境龙神",
}
# 旧武器变体 id（重映射前的通用变体）与改版后的全部职能变体 id
OLD_AFFIXES = {"crit", "dh", "det", "bal"}
NEW_AFFIXES = set(AFFIX_NAME)
ALL_AFFIXES = OLD_AFFIXES | NEW_AFFIXES
# 回滚用：职能变体 → 改版前曾存在的通用变体 id（低档位另按 minTier 收敛，见 downgrade_target）
REVERT_AFFIX = {"tank": "crit", "str": "dh", "det": "det", "dex": "bal", "crit": "crit", "int": "crit", "bal": "crit"}
OLD_NAME = {"crit": "精准", "dh": "强袭", "det": "制敌", "bal": "游击"}


def _parse_weapon(base_id: str) -> tuple[str, str, int] | None:
    """`w_<weaponType>[_<affix>]_<tier>` → (weaponType, affix, tier)；非武器或未知族返回 None。

    weaponType 可能含下划线（sword_shield），故按「末段是档位、倒数第二段是已知变体 id」解析。
    """
    if not base_id or not base_id.startswith("w_"):
        return None
    parts = str(base_id).split("_")
    try:
        tier = int(parts[-1])
    except (ValueError, IndexError):
        return None
    if len(parts) >= 4 and parts[-2] in ALL_AFFIXES:
        affix, weapon_type = parts[-2], "_".join(parts[1:-2])
    else:
        affix, weapon_type = "", "_".join(parts[1:-1])
    if weapon_type not in WEAPON_AFFIX:
        return None
    return weapon_type, affix, tier


def upgrade_target(base_id: str) -> tuple[str, str] | None:
    """旧底材 id → (新底材 id, 新名称)；基础型 / 非武器 / 未知族返回 None（保持不变）。"""
    parsed = _parse_weapon(base_id)
    if parsed is None:
        return None
    weapon_type, affix, tier = parsed
    if not affix:
        return None
    new_affix = WEAPON_AFFIX[weapon_type]
    new_id = f"w_{weapon_type}_{new_affix}_{tier}"
    new_name = f"{TIER_NAME.get(tier, '')}{AFFIX_NAME[new_affix]}{WEAPON_SUFFIX[weapon_type]}"
    return new_id, new_name


def downgrade_target(base_id: str) -> tuple[str, str] | None:
    """职能变体 → 改版前的通用变体 id（有损：多个旧变体曾合并为一个，回滚统一收敛）。

    旧变体出现档位：crit/dh 从档位 4、det/bal 从档位 6；不足档位的一律退回基础型。
    """
    parsed = _parse_weapon(base_id)
    if parsed is None:
        return None
    weapon_type, affix, tier = parsed
    if not affix:
        return None
    old = REVERT_AFFIX.get(affix, "crit")
    if old in ("det", "bal") and tier < 6:
        old = "crit"
    if tier < 4:
        return f"w_{weapon_type}_{tier}", f"{TIER_NAME.get(tier, '')}{WEAPON_SUFFIX[weapon_type]}"
    return (
        f"w_{weapon_type}_{old}_{tier}",
        f"{TIER_NAME.get(tier, '')}{OLD_NAME[old]}{WEAPON_SUFFIX[weapon_type]}",
    )


items = sa.table(
    "items",
    sa.column("id", sa.Integer),
    sa.column("base_id", sa.String),
    sa.column("name", sa.String),
)

codex = sa.table(
    "codex_equipment",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("base_id", sa.String),
    sa.column("unlocked_rarities", sa.JSON().with_variant(JSONB, "postgresql")),
    sa.column("total_count", sa.Integer),
    sa.column("first_unlock_at", sa.DateTime(timezone=True)),
)

listings = sa.table(
    "market_listings",
    sa.column("id", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("item_key", sa.String),
    sa.column("name", sa.String),
    sa.column("snapshot", sa.JSON().with_variant(JSONB, "postgresql")),
)

Target = Callable[[str], "tuple[str, str] | None"]


def _rewrite_items(bind, target: Target) -> None:
    rows = bind.execute(sa.select(items.c.id, items.c.base_id, items.c.name)).fetchall()
    for row_id, base_id, name in rows:
        mapped = target(str(base_id))
        if mapped is None:
            continue
        new_id, new_name = mapped
        if new_id != base_id or new_name != name:
            bind.execute(items.update().where(items.c.id == row_id).values(base_id=new_id, name=new_name))


def _dedupe_codex(bind, target: Target) -> None:
    """重映射 codex 底材；同一 (user_id, 新底材) 的多条合并（品阶取并集、计数求和、最早解锁时间）。"""
    rows = bind.execute(
        sa.select(
            codex.c.id, codex.c.user_id, codex.c.base_id,
            codex.c.unlocked_rarities, codex.c.total_count, codex.c.first_unlock_at,
        )
    ).fetchall()
    groups: dict[tuple[int, str], list] = {}
    for row in rows:
        mapped = target(str(row.base_id))
        new_base_id = mapped[0] if mapped else row.base_id
        groups.setdefault((int(row.user_id), new_base_id), []).append((row, new_base_id))

    for (_, new_base_id), entries in groups.items():
        entries.sort(key=lambda e: int(e[0].id))
        keep_row = entries[0][0]
        if len(entries) == 1:
            if keep_row.base_id != new_base_id:
                bind.execute(codex.update().where(codex.c.id == keep_row.id).values(base_id=new_base_id))
            continue
        rarities = sorted({q for row, _ in entries for q in (row.unlocked_rarities or [])})
        total = sum(int(row.total_count or 0) for row, _ in entries)
        first = [row.first_unlock_at for row, _ in entries if row.first_unlock_at is not None]
        # 先删多余行再改保留行：否则改 base_id 时可能与「本就已是该新底材」的重复行撞唯一约束。
        for row, _ in entries[1:]:
            bind.execute(codex.delete().where(codex.c.id == row.id))
        values = {"base_id": new_base_id, "unlocked_rarities": rarities, "total_count": total}
        if first:
            values["first_unlock_at"] = min(first)
        bind.execute(codex.update().where(codex.c.id == keep_row.id).values(**values))


def _rewrite_listings(bind, target: Target) -> None:
    rows = bind.execute(
        sa.select(listings.c.id, listings.c.kind, listings.c.item_key, listings.c.name, listings.c.snapshot)
    ).fetchall()
    for row_id, kind, item_key, name, snapshot in rows:
        if kind != "equipment":
            continue
        mapped = target(str(item_key))
        if mapped is None:
            continue
        new_id, new_name = mapped
        new_snapshot = {**(snapshot or {})}
        if "baseId" in new_snapshot:
            new_snapshot["baseId"] = new_id
        new_snapshot["name"] = new_name
        bind.execute(
            listings.update()
            .where(listings.c.id == row_id)
            .values(item_key=new_id, name=new_name, snapshot=new_snapshot)
        )


def _apply(bind, target: Target) -> None:
    _rewrite_items(bind, target)
    _dedupe_codex(bind, target)
    _rewrite_listings(bind, target)


def upgrade() -> None:
    _apply(op.get_bind(), upgrade_target)


def downgrade() -> None:
    _apply(op.get_bind(), downgrade_target)
