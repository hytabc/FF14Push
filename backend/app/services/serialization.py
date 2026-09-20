"""序列化：ORM 对象 → 前端可用的字典。"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.game_config import CONFIG
from app.services.slots_util import possible_slots


def item_to_dict(item: Any, price_range: tuple[int, int] | None = None) -> dict[str, Any]:
    base = CONFIG.base_item_by_id.get(item.base_id)
    data: dict[str, Any] = {
        "id": item.id,
        "baseId": item.base_id,
        "name": item.name,
        "category": item.category,
        "slot": item.slot,
        "equipSlots": possible_slots(base) if base else [item.slot],
        "rarity": item.rarity,
        "levelReq": item.level_req,
        "baseAttrs": item.base_attrs or [],
        "subAttrs": item.sub_attrs or [],
        "terms": item.terms or [],
        "equippedSlot": item.equipped_slot,
        "refineCount": item.refine_count,
        "enchantCount": item.enchant_count,
        "source": item.source,
        "weaponType": base.weapon_type if base else None,
        "jobId": base.job_id if base else None,
    }
    if price_range is not None:
        data["sellPriceMin"], data["sellPriceMax"] = price_range
    return data


def item_from_generated(generated: dict[str, Any], source: str) -> dict[str, Any]:
    """把 item_factory 生成的字典转换为 ORM 字段。"""
    return {
        "base_id": generated["baseId"],
        "name": generated["name"],
        "category": generated["category"],
        "slot": generated["slot"],
        "rarity": generated["rarity"],
        "level_req": generated["levelReq"],
        "base_attrs": generated["baseAttrs"],
        "sub_attrs": generated["subAttrs"],
        "terms": generated["terms"],
        "source": source,
    }


def loadout(items: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """当前穿戴 → {slotId: item}。"""
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.equipped_slot:
            out[item.equipped_slot] = item_to_dict(item)
    return out


def hero_to_dict(hero: Any, stats: Any) -> dict[str, Any]:
    return {
        "id": hero.id,
        "name": hero.name,
        "level": hero.level,
        "exp": hero.exp,
        "talent": hero.talent,
        "talentName": CONFIG.talents["talents"][hero.talent]["name"],
        "attrBias": hero.attr_bias,
        "strength": hero.strength,
        "agility": hero.agility,
        "intellect": hero.intellect,
        "currentRegionId": hero.current_region_id,
        "regionKillCount": hero.region_kill_count,
        "isInitial": hero.is_initial,
        "jobId": stats.job_id,
        "stats": stats.to_dict(),
    }
