"""服务端装备生成（权威 RNG）。对应 PRD 2.3 装备属性系统。

所有「获得装备」的随机结果必须由本模块产出，客户端只上报「发生了一次掉落」。
"""

from __future__ import annotations

import random
from typing import Any

from app.services.game_config import CONFIG, BaseItem
from app.services.loot import RARITY_ORDER, rarity_tier
from app.services.slots_util import possible_slots

SUB_ATTR_IDS = {a["id"] for a in CONFIG.attributes}


def _float_factor(rng: random.Random, spread: float) -> float:
    return 1.0 + rng.uniform(-spread, spread)


def pick_base_item(category: str, level: int, rng: random.Random) -> BaseItem:
    """按英雄等级挑选可用底材，档位越高权重越大。"""
    candidates = [b for b in CONFIG.base_items if b.category == category]
    if not candidates:
        raise ValueError(f"未知装备大类: {category}")
    usable = [b for b in candidates if b.level_req <= level]
    if not usable:
        usable = [b for b in candidates if b.tier_index == 0]
    # 档位加权：越接近英雄等级的档位权重越高
    best_tier = max(b.tier_index for b in usable)
    weights = [4 ** max(0, b.tier_index - best_tier + 2) for b in usable]
    return rng.choices(usable, weights=weights, k=1)[0]


def roll_sub_attr_value(rng: random.Random, lo: float, hi: float, quality: str) -> float:
    """副属性数值：普通在区间内随机浮动；稀有取上限；太古取上限 ×1.25。

    与 Buff/Debuff 词条的品质规则一致（来源：PRD 附魔 5.3）。
    例：暴击区间 100-400 → 太古为 500。
    """
    if quality == "ancient":
        return _extreme_value(lo, hi) * 1.25
    if quality == "rare":
        return _extreme_value(lo, hi)
    return rng.uniform(lo, hi) * _float_factor(rng, CONFIG.sub_attr_float)


def pick_sub_attrs(base: BaseItem, rarity: str, rng: random.Random) -> list[dict[str, Any]]:
    spec = CONFIG.rarities[rarity]
    count = rng.randint(int(spec["subAttrMin"]), int(spec["subAttrMax"]))
    pool = [a for a in base.sub_attr_pool if a in SUB_ATTR_IDS]
    if not pool:
        return []
    count = min(count, len(pool))
    chosen = rng.sample(pool, count)
    out: list[dict[str, Any]] = []
    for attr_id in chosen:
        attr = CONFIG.attribute_by_id[attr_id]
        lo, hi = attr["ranges"][rarity]
        quality = _roll_quality(rng)
        value = roll_sub_attr_value(rng, float(lo), float(hi), quality)
        out.append(
            {
                "attr": attr_id,
                "value": round(value, 2),
                "type": attr["valueType"],
                "quality": quality,
            }
        )
    return out


def _extreme_value(lo: float, hi: float) -> float:
    return hi if abs(hi) >= abs(lo) else lo


def roll_terms(base: BaseItem, rarity: str, rng: random.Random) -> list[dict[str, Any]]:
    """生成 0-4 个 Buff/Debuff。来源：PRD 2.4"""
    spec = CONFIG.rarities[rarity]
    count = rng.randint(int(spec["termMin"]), int(spec["termMax"]))
    if count <= 0:
        return []

    slots = set(possible_slots(base))
    eligible = [
        t
        for t in CONFIG.terms["terms"]
        if not t.get("slots") or slots & set(t["slots"])
    ]
    if not eligible:
        return []

    debuff_chance = float(spec["debuffChance"])
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    attempts = 0
    while len(out) < count and attempts < 40:
        attempts += 1
        want_debuff = rng.random() < debuff_chance
        pool = [t for t in eligible if (t["type"] == "debuff") == want_debuff and t["id"] not in used]
        if not pool:
            pool = [t for t in eligible if t["id"] not in used]
        if not pool:
            break
        term = rng.choice(pool)
        used.add(term["id"])

        quality = _roll_quality(rng)
        lo, hi = term["range"]
        if quality == "common":
            value = rng.uniform(float(lo), float(hi))
        elif quality == "rare":
            value = _extreme_value(float(lo), float(hi))
        else:
            value = _extreme_value(float(lo), float(hi)) * 1.25

        out.append(
            {
                "id": term["id"],
                "name": term["name"],
                "type": term["type"],
                "stat": term["stat"],
                "trigger": term["trigger"],
                "value": round(value, 2),
                "quality": quality,
                "desc": term["desc"],
            }
        )
    return out


def _roll_quality(rng: random.Random) -> str:
    chances = CONFIG.economy["termQuality"]
    roll = rng.random()
    if roll < float(chances["ancient"]):
        return "ancient"
    if roll < float(chances["ancient"]) + float(chances["rare"]):
        return "rare"
    return "common"


def generate_item(
    category: str,
    level: int,
    rarity: str | None = None,
    box_tier: str = "normal",
    rng: random.Random | None = None,
    pity=None,
    base_id: str | None = None,
) -> tuple[dict[str, Any], Any]:
    """生成一件装备。[返回] (item_dict, 新的保底状态)

    base_id 用于强制指定底材（如开局赠送的起始武器），省略时按等级随机。
    """
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[base_id] if base_id else pick_base_item(category, level, rng)
    if rarity is None:
        from app.services.loot import PityState, draw_rarity

        rarity, pity = draw_rarity(box_tier, pity or PityState(), rng)
    spec = CONFIG.rarities[rarity]
    mult = float(spec["multiplier"])

    base_attrs = []
    for entry in base.base_attrs:
        value = float(entry["base"]) * mult * _float_factor(rng, CONFIG.base_attr_float)
        base_attrs.append({"attr": entry["attr"], "value": round(value, 2)})

    item = {
        "baseId": base.id,
        "name": base.name,
        "category": base.category,
        "slot": base.slot,
        "rarity": rarity,
        "levelReq": base.level_req,
        "baseAttrs": base_attrs,
        "subAttrs": pick_sub_attrs(base, rarity, rng),
        "terms": roll_terms(base, rarity, rng),
    }
    return item, pity


def generate_by_rarity(
    category: str,
    level: int,
    rarity: str,
    rng: random.Random | None = None,
    base_id: str | None = None,
) -> dict[str, Any]:
    """指定品阶生成（合成 / BOSS 宝箱 / 起始装备用）。"""
    item, _ = generate_item(category, level, rarity=rarity, rng=rng, base_id=base_id)
    return item


def regenerate_attrs(item: Any, rng: random.Random | None = None) -> dict[str, Any]:
    """重造：重新随机基础属性浮动与副属性，保留品阶/类型/等级需求/词条。"""
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[item.base_id]
    mult = float(CONFIG.rarities[item.rarity]["multiplier"])

    base_attrs = [
        {
            "attr": entry["attr"],
            "value": round(float(entry["base"]) * mult * _float_factor(rng, CONFIG.base_attr_float), 2),
        }
        for entry in base.base_attrs
    ]
    return {"baseAttrs": base_attrs, "subAttrs": pick_sub_attrs(base, item.rarity, rng)}


def roll_terms_for_enchant(item: Any, rng: random.Random | None = None) -> list[dict[str, Any]]:
    """附魔：重新随机全部 Buff/Debuff。"""
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[item.base_id]
    return roll_terms(base, item.rarity, rng)
