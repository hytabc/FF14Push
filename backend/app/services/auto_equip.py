"""一键最强：按当前主手武器的职业 / 职能，为英雄挑选各栏位战力最高的装备。

主手武器作为职业锚点**保持不变**（英雄职业由武器决定）；其余栏位只在「职能兼容」的
装备里取战力最高者。已被其他英雄装备的装备默认不参与，除非显式允许（此时会从原英雄卸下）。
"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.game_config import CONFIG
from app.services.slots_util import accepts, all_slot_ids, role_of_base
from app.services.valuation import item_score

# 生产 / 采集专用装备不参与战斗配装。
_DEDICATED_CATEGORIES = {"doh_tool", "doh_gear", "dol_tool", "dol_gear"}
_WEAPON_SLOT = "mainHand"


def hero_job_role(items: Iterable[Any], hero_id: int) -> tuple[str | None, str | None]:
    """由该英雄已装备的主手武器推出 (jobId, role)。

    无主手武器、或武器底材缺少职业（如基础型）时返回 (None, None)——调用方据此提示
    「请先装备一把武器」。
    """
    for item in items:
        if getattr(item, "equipped_hero_id", None) != hero_id:
            continue
        if getattr(item, "equipped_slot", None) != _WEAPON_SLOT:
            continue
        base = CONFIG.base_item_by_id.get(item.base_id)
        if base is None or not base.job_id:
            return None, None
        return base.job_id, role_of_base(base)
    return None, None


def plan_auto_equip(items: Iterable[Any], hero_id: int, include_equipped: bool) -> dict[str, Any]:
    """规划各栏位（不含主手武器）应装备的最强装备，返回 {slotId: Item}。

    - 职能兼容：装备职能为空（基础型 / 世界BOSS 专属）或与英雄当前武器职能一致。
    - `include_equipped=False` 时排除已被其他英雄装备的装备。
    - 每件装备至多占用一个栏位；戒指两栏按「各取一件最优的不同戒指」分配。
    """
    items = list(items)
    _, role = hero_job_role(items, hero_id)
    if role is None:
        return {}

    pool: list[tuple[Any, float]] = []
    for item in items:
        if getattr(item, "category", None) in _DEDICATED_CATEGORIES:
            continue
        if getattr(item, "slot", None) == _WEAPON_SLOT:
            continue
        owner = getattr(item, "equipped_hero_id", None)
        if not include_equipped and owner not in (None, hero_id):
            continue
        base = CONFIG.base_item_by_id.get(item.base_id)
        if base is None:
            continue
        base_role = role_of_base(base)
        if base_role and base_role != role:
            continue
        pool.append((item, item_score(item)))

    pool.sort(key=lambda pair: pair[1], reverse=True)

    plan: dict[str, Any] = {}
    used: set[int] = set()
    for slot in all_slot_ids():
        if slot == _WEAPON_SLOT:
            continue
        for item, _score in pool:
            if item.id in used:
                continue
            base = CONFIG.base_item_by_id.get(item.base_id)
            if base is None or not accepts(slot, base):
                continue
            plan[slot] = item
            used.add(item.id)
            break
    return plan
