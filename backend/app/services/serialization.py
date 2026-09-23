"""序列化：ORM 对象 → 前端可用的字典。"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.economy import enchant_cost, refine_cost
from app.services.game_config import CONFIG
from app.services.item_factory import base_attr_range, dohdol_base_attr_range, sub_attr_range
from app.services.slots_util import possible_slots
from app.services.valuation import item_score


def _attrs_with_range(entries: Any, range_fn: Any) -> list[dict[str, Any]]:
    """为每条属性附加 min/max（供前端展示「当前值【区间】」）。不改动库中的 JSON。"""
    out: list[dict[str, Any]] = []
    for entry in entries or []:
        row = dict(entry)
        if range_fn is not None:
            band = range_fn(entry["attr"])
            if band is not None:
                lo, hi = band
                row["min"], row["max"] = round(lo, 2), round(hi, 2)
        out.append(row)
    return out


def item_to_dict(item: Any, price_range: tuple[int, int] | None = None) -> dict[str, Any]:
    base = CONFIG.base_item_by_id.get(item.base_id)
    # 生产/采集专用装备走独立注册表：底材不是 BaseItem，需要单独算取值区间。
    dohdol = CONFIG.dohdol_item_by_id.get(item.base_id) if base is None else None

    def base_band(attr_id: str) -> tuple[float, float] | None:
        if base is not None:
            return base_attr_range(base, item.rarity, attr_id, getattr(item, "high_quality", False))
        if dohdol is not None:
            return dohdol_base_attr_range(item.rarity, float(dohdol["bonus"].get(attr_id, 0.0)))
        return None

    def sub_band(attr_id: str) -> tuple[float, float] | None:
        if base is not None:
            return sub_attr_range(base, item.rarity, attr_id)
        return None

    data: dict[str, Any] = {
        "id": item.id,
        "baseId": item.base_id,
        "name": item.name,
        "category": item.category,
        "slot": item.slot,
        "equipSlots": possible_slots(base) if base else [item.slot],
        "rarity": item.rarity,
        "levelReq": item.level_req,
        "score": int(round(item_score(item))),
        "highQuality": bool(getattr(item, "high_quality", False)),
        "baseAttrs": _attrs_with_range(item.base_attrs, base_band),
        "subAttrs": _attrs_with_range(item.sub_attrs, sub_band),
        "terms": item.terms or [],
        "equippedSlot": item.equipped_slot,
        "equippedHeroId": getattr(item, "equipped_hero_id", None),
        "refineCount": item.refine_count,
        "enchantCount": item.enchant_count,
        # 实付价：重造随重造次数递增、并随物品等级提高，前端直接显示这些值即可与服务端扣费一致
        "refineCost": refine_cost(item.rarity, int(item.refine_count or 0), "random", item.level_req),
        "enchantCost": enchant_cost(item.rarity, "random", item.level_req),
        # 「基于当前」模式（保底不降）的单价，供前端展示两种模式价格
        "refineCostBasedOnCurrent": refine_cost(
            item.rarity, int(item.refine_count or 0), "basedOnCurrent", item.level_req
        ),
        "enchantCostBasedOnCurrent": enchant_cost(item.rarity, "basedOnCurrent", item.level_req),
        "source": item.source,
        "weaponType": base.weapon_type if base else None,
        "jobId": base.job_id if base else None,
        "tagIds": list(item.tag_ids or []),
    }
    if price_range is not None:
        data["sellPriceMin"], data["sellPriceMax"] = price_range
    return data


def tag_to_dict(tag: Any) -> dict[str, Any]:
    """装备标签 → 前端字典。"""
    return {"id": tag.id, "name": tag.name, "color": tag.color}


def item_from_generated(generated: dict[str, Any], source: str) -> dict[str, Any]:
    """把 item_factory 生成的字典转换为 ORM 字段。"""
    return {
        "base_id": generated["baseId"],
        "name": generated["name"],
        "category": generated["category"],
        "slot": generated["slot"],
        "rarity": generated["rarity"],
        "level_req": generated["levelReq"],
        "high_quality": bool(generated.get("highQuality", False)),
        "base_attrs": generated["baseAttrs"],
        "sub_attrs": generated["subAttrs"],
        "terms": generated["terms"],
        "source": source,
    }


def loadout(items: Iterable[Any], hero_id: int | None = None) -> dict[str, dict[str, Any]]:
    """当前穿戴 → {slotId: item}。"""
    from app.services.stats import hero_items
    items = hero_items(items, hero_id) if hero_id is not None else items
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
        "ancientAttr": hero.ancient_attr,
        "eggId": hero.egg_id,
        "currentRegionId": hero.current_region_id,
        "regionKillCount": hero.region_kill_count,
        "isInitial": hero.is_initial,
        "jobId": stats.job_id,
        "stats": stats.to_dict(),
    }
