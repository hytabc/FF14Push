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

# 稀有取区间极值、太古取极值 ×1.25（与 PRD 附魔 5.3 一致）。
ANCIENT_FACTOR = 1.25


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


def pick_base_item_by_slot(slot: str, level: int, rng: random.Random) -> BaseItem:
    """按装备种类（底材 slot）挑选可用底材，档位越高权重越大。"""
    candidates = [b for b in CONFIG.base_items if b.slot == slot]
    if not candidates:
        raise ValueError(f"未知装备种类: {slot}")
    usable = [b for b in candidates if b.level_req <= level]
    if not usable:
        usable = [b for b in candidates if b.tier_index == 0]
    best_tier = max(b.tier_index for b in usable)
    weights = [4 ** max(0, b.tier_index - best_tier + 2) for b in usable]
    return rng.choices(usable, weights=weights, k=1)[0]


def generate_item_for_slot(
    level: int,
    slot: str,
    box_tier: str = "normal",
    rng: random.Random | None = None,
    luck: float = 0.0,
) -> dict[str, Any]:
    """按自选装备种类生成装备（高难宝箱用）。"""
    rng = rng or random.Random()
    base = pick_base_item_by_slot(slot, level, rng)
    item, _ = generate_item(base.category, level, box_tier=box_tier, rng=rng, luck=luck, base_id=base.id)
    return item


def roll_sub_attr_value(rng: random.Random, lo: float, hi: float, quality: str) -> float:
    """副属性数值：普通在区间内随机浮动；稀有取上限；太古取上限 ×1.25。

    与 Buff/Debuff 词条的品质规则一致（来源：PRD 附魔 5.3）。
    例：暴击区间 100-400 → 太古为 500。
    """
    if quality == "ancient":
        return _extreme_value(lo, hi) * ANCIENT_FACTOR
    if quality == "rare":
        return _extreme_value(lo, hi)
    return rng.uniform(lo, hi) * _float_factor(rng, CONFIG.sub_attr_float)


def base_attr_range(base: BaseItem, rarity: str, attr_id: str) -> tuple[float, float]:
    """基础属性的可达区间：[基准值 × 品阶倍率 × (1 ± baseAttrFloat)]。"""
    mult = float(CONFIG.rarities[rarity]["multiplier"])
    spread = float(CONFIG.base_attr_float)
    entry = next((e for e in base.base_attrs if e["attr"] == attr_id), None)
    if entry is None:
        return 0.0, 0.0
    value = float(entry["base"]) * mult
    return value * (1.0 - spread), value * (1.0 + spread)


def sub_attr_range(base: BaseItem, rarity: str, attr_id: str) -> tuple[float, float]:
    """副属性的**可达区间**：名义区间 × 档位缩放后再叠加 ±subAttrFloat 浮动。

    与生成逻辑（roll_sub_attr_value）保持一致，保证普通品质数值始终落在该区间内。
    """
    attr = CONFIG.attribute_by_id.get(attr_id)
    if attr is None:
        return 0.0, 0.0
    lo, hi = attr["ranges"][rarity]
    scale = float(getattr(base, "sub_attr_scale", 1.0))
    spread = float(CONFIG.sub_attr_float)
    return float(lo) * scale * (1.0 - spread), float(hi) * scale * (1.0 + spread)


def sub_attr_cap(base: BaseItem, rarity: str, attr_id: str) -> float:
    """副属性的名义极值：稀有取它、太古取其 ×1.25（与 roll_sub_attr_value 一致）。"""
    attr = CONFIG.attribute_by_id.get(attr_id)
    if attr is None:
        return 0.0
    lo, hi = attr["ranges"][rarity]
    scale = float(getattr(base, "sub_attr_scale", 1.0))
    return _extreme_value(float(lo) * scale, float(hi) * scale)


def term_range(term_id: str) -> tuple[float, float]:
    """词条区间（terms.json 的 range）。"""
    spec = CONFIG.term_by_id.get(term_id)
    if spec is None:
        return 0.0, 0.0
    lo, hi = spec["range"]
    return float(lo), float(hi)


def quality_band(
    lo: float, hi: float, quality: str, cap: float | None = None
) -> tuple[float, float]:
    """「基于当前」保留品质时，值的合法数值带。

    普通在 [下限, 上限] 内；稀有在 [名义极值, 可达上限]；太古在 [极值×1.25, 极值×1.5]。
    现有稀有/太古值取在带下沿，因此浮动只会向上，不会掉回普通。
    """
    if cap is None:
        cap = _extreme_value(lo, hi)
    lo_b, hi_b = min(lo, hi), max(lo, hi)
    if quality == "ancient":
        return cap * ANCIENT_FACTOR, cap * ANCIENT_FACTOR * 1.2
    if quality == "rare":
        # 下沿取名义极值（稀有值），上沿不超过可达上限，避免超出展示区间。
        return cap, max(cap, hi_b)
    return lo_b, hi_b


def float_near_current(
    rng: random.Random,
    current: float,
    lo: float,
    hi: float,
    quality: str,
    spread_pct: float,
    cap: float | None = None,
) -> float:
    """在 current 附近的邻域内独立浮动，并夹回该品质的数值带。

    浮动幅度 = 区间宽度 (hi − lo) × spread_pct，可升可降。
    """
    if hi <= lo:
        return current
    swing = abs(hi - lo) * spread_pct
    band_lo, band_hi = quality_band(lo, hi, quality, cap)
    if band_hi < band_lo:
        band_lo, band_hi = band_hi, band_lo
    value = current + rng.uniform(-swing, swing)
    return min(max(value, band_lo), band_hi)


def pick_sub_attrs(
    base: BaseItem, rarity: str, rng: random.Random, quality_bonus: float = 0.0
) -> list[dict[str, Any]]:
    spec = CONFIG.rarities[rarity]
    count = rng.randint(int(spec["subAttrMin"]), int(spec["subAttrMax"]))
    pool = [a for a in base.sub_attr_pool if a in SUB_ATTR_IDS]
    if not pool:
        return []
    count = min(count, len(pool))
    chosen = rng.sample(pool, count)
    # 副属性随档位缩放：底材固定属性本就按档位增长，副属性同步缩放后
    # item_score 才会随档位单调增长（避免低档高品阶装备战力虚高）。
    scale = float(getattr(base, "sub_attr_scale", 1.0))
    out: list[dict[str, Any]] = []
    for attr_id in chosen:
        attr = CONFIG.attribute_by_id[attr_id]
        lo, hi = attr["ranges"][rarity]
        quality = _roll_quality(rng, quality_bonus)
        value = roll_sub_attr_value(rng, float(lo) * scale, float(hi) * scale, quality)
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


def roll_terms(
    base: BaseItem,
    rarity: str,
    rng: random.Random,
    quality_bonus: float = 0.0,
    force_ancient: int = 0,
) -> list[dict[str, Any]]:
    """生成 0-4 个 Buff/Debuff。来源：PRD 2.4

    force_ancient>0 时，保证其中至少这么多条 Buff 为太古（制造装备的「必带太古词条」）。
    """
    slots = set(possible_slots(base))
    eligible = [
        t
        for t in CONFIG.terms["terms"]
        if not t.get("slots") or slots & set(t["slots"])
    ]
    return _roll_terms_from_pool(eligible, rarity, rng, quality_bonus, force_ancient)


def roll_dedicated_terms(
    slot: str,
    rarity: str,
    rng: random.Random,
    quality_bonus: float = 0.0,
    force_ancient: int = 0,
) -> list[dict[str, Any]]:
    """生成生产/采集专用装备的 0-4 个 Buff/Debuff。

    词条池为 `dohdol-equipment.json:terms`，按专用栏位过滤；品质规则与战斗词条一致
    （普通/稀有/太古，Debuff 恒为普通）。
    """
    eligible = [
        t
        for t in CONFIG.dohdol_equipment.get("terms", [])
        if not t.get("slots") or slot in t["slots"]
    ]
    return _roll_terms_from_pool(eligible, rarity, rng, quality_bonus, force_ancient)


def _roll_terms_from_pool(
    eligible: list[dict[str, Any]],
    rarity: str,
    rng: random.Random,
    quality_bonus: float = 0.0,
    force_ancient: int = 0,
) -> list[dict[str, Any]]:
    spec = CONFIG.rarities[rarity]
    count = rng.randint(int(spec["termMin"]), int(spec["termMax"]))
    count = max(count, int(force_ancient))
    if count <= 0 or not eligible:
        return []

    buffs = [t for t in eligible if t["type"] == "buff"]
    debuff_chance = float(spec["debuffChance"])
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    attempts = 0
    remaining_forced = int(force_ancient)
    while len(out) < count and attempts < 60:
        attempts += 1
        if remaining_forced > 0 and buffs:
            pool = [t for t in buffs if t["id"] not in used]
            force_quality = "ancient"
        else:
            want_debuff = rng.random() < debuff_chance
            pool = [t for t in eligible if (t["type"] == "debuff") == want_debuff and t["id"] not in used]
            if not pool:
                pool = [t for t in eligible if t["id"] not in used]
            force_quality = None
        if not pool:
            break
        term = rng.choice(pool)
        used.add(term["id"])

        # 始终消耗一次品质判定（保持 RNG 序列稳定），再决定是否允许稀有/太古。
        quality = _roll_quality(rng, quality_bonus)
        allow_special = term["type"] != "debuff" or bool(
            CONFIG.economy.get("debuffQualityEnabled", False)
        )
        if not allow_special:
            quality = "common"  # Debuff 仅在随机池内随机
        elif force_quality == "ancient":
            quality = "ancient"
            remaining_forced -= 1
        lo, hi = term["range"]
        if quality == "common":
            value = rng.uniform(float(lo), float(hi))
        elif quality == "rare":
            value = _extreme_value(float(lo), float(hi))
        else:
            value = _extreme_value(float(lo), float(hi)) * ANCIENT_FACTOR

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


def _roll_quality(rng: random.Random, bonus: float = 0.0) -> str:
    """词条/副属性品质掷点。

    bonus>0（制造品质药水/专用装备）时提高稀有与太古的概率质量。
    """
    chances = CONFIG.economy["termQuality"]
    rare = float(chances["rare"])
    ancient = float(chances["ancient"])
    if bonus > 0:
        rare *= 1.0 + bonus
        ancient *= 1.0 + bonus * 5.0
    total = rare + ancient
    if total > 0.5:
        scale = 0.5 / total
        rare *= scale
        ancient *= scale
    roll = rng.random()
    if roll < ancient:
        return "ancient"
    if roll < ancient + rare:
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
    luck: float = 0.0,
    quality_bonus: float = 0.0,
    high_quality: bool = False,
) -> tuple[dict[str, Any], Any]:
    """生成一件装备。[返回] (item_dict, 新的保底状态)

    base_id 用于强制指定底材（如开局赠送的起始武器），省略时按等级随机。
    luck 为品阶爆率加成（0 表示按基础概率）。
    quality_bonus 提高副属性/词条的稀有与太古概率。
    high_quality 为制造装备的「高品质」：属性区间整体上移，且必带太古词条。
    """
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[base_id] if base_id else pick_base_item(category, level, rng)
    if rarity is None:
        from app.services.loot import PityState, draw_rarity

        rarity, pity = draw_rarity(box_tier, pity or PityState(), rng, luck)
    spec = CONFIG.rarities[rarity]
    mult = float(spec["multiplier"])
    if high_quality:
        mult *= float(CONFIG.recipes["equipment"]["highQualityMultiplier"])
    force_ancient = int(CONFIG.recipes["equipment"]["guaranteedAncientTerms"]) if high_quality else 0

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
        "highQuality": bool(high_quality),
        "baseAttrs": base_attrs,
        "subAttrs": pick_sub_attrs(base, rarity, rng, quality_bonus),
        "terms": roll_terms(base, rarity, rng, quality_bonus, force_ancient),
    }
    return item, pity


def craft_rarity_scaling() -> dict[str, Any]:
    return CONFIG.recipes["equipment"].get("rarityScaling") or {}


def craft_rarity_luck(
    hero_level: int, cleared_regions: int, prod_level: int, gear_pct: float
) -> tuple[float, list[dict[str, Any]]]:
    """制造品阶「幸运进度」t 与各来源明细。

    t = Σ weight × clamp(值 / ref, 0, 1)；四项来源全部取满 → t = 1。
    """
    values = {
        "heroLevel": max(0.0, float(hero_level)),
        "clearedRegions": max(0.0, float(cleared_regions)),
        "prodLevel": max(0.0, float(prod_level)),
        "gearPct": max(0.0, float(gear_pct)),
    }
    factors: list[dict[str, Any]] = []
    total = 0.0
    for key, spec in craft_rarity_scaling().get("sources", {}).items():
        weight = float(spec.get("weight", 0.0))
        ref = float(spec.get("ref", 1.0)) or 1.0
        value = values.get(key, 0.0)
        norm = min(1.0, value / ref)
        total += weight * norm
        factors.append({"key": key, "value": value, "ref": ref, "norm": norm, "weight": weight})
    return min(1.0, max(0.0, total)), factors


def craft_rarity_distribution(luck: float = 0.0) -> dict[str, float]:
    """制造品阶概率分布：基准分布与目标分布按 t 线性插值，神话受 mythicCap 硬上限约束。"""
    scaling = craft_rarity_scaling()
    base = CONFIG.recipes["equipment"]["rarityWeights"]
    target = scaling.get("targetWeights") or base
    cap = float(scaling.get("mythicCap", 1.0))
    t = min(1.0, max(0.0, float(luck)))
    order = list(CONFIG.rarity_order)

    probs = {r: float(base.get(r, 0.0)) * (1.0 - t) + float(target.get(r, base.get(r, 0.0))) * t for r in order}
    total = sum(probs.values())
    if total <= 0:
        return {r: (1.0 if r == order[0] else 0.0) for r in order}
    probs = {r: v / total for r, v in probs.items()}

    if "mythic" in probs and probs["mythic"] > cap:
        excess = probs["mythic"] - cap
        probs["mythic"] = cap
        others = [r for r in order if r != "mythic"]
        other_total = sum(probs[r] for r in others)
        for r in others:
            probs[r] += excess * (probs[r] / other_total if other_total > 0 else 1.0 / len(others))
    return probs


def crafted_rarity(rng: random.Random, luck: float = 0.0) -> str:
    """制造装备的品阶抽取（白/绿/蓝/紫/橙/红），概率随进度提升。"""
    dist = craft_rarity_distribution(luck)
    order = list(CONFIG.rarity_order)
    roll = rng.random()
    cumulative = 0.0
    for rarity in order:
        cumulative += dist.get(rarity, 0.0)
        if roll < cumulative:
            return rarity
    return order[-1]


def generate_crafted_item(
    base_id: str,
    rng: random.Random | None = None,
    quality_bonus: float = 0.0,
    rarity_luck: float = 0.0,
) -> dict[str, Any]:
    """生产一件装备：恒为「高品质」，品阶按进度概率抽取。

    产出可为战斗装备（走 CONFIG.base_item_by_id）或生产/采集专用装备（走 dohdol 配置）。
    专用装备会额外按 `dohdol-equipment.json:terms` 抽出 Buff/Debuff 词条。
    """
    rng = rng or random.Random()
    rarity = crafted_rarity(rng, rarity_luck)

    dohdol = CONFIG.dohdol_item_by_id.get(base_id)
    if dohdol is not None:
        mult = float(CONFIG.recipes["equipment"]["highQualityMultiplier"])
        rarity_tier = int(CONFIG.rarities[rarity]["tier"])
        base_attrs = [
            {"attr": stat, "value": round(float(value) * mult * (1.0 + 0.15 * rarity_tier), 2)}
            for stat, value in dohdol["bonus"].items()
        ]
        force_ancient = int(CONFIG.recipes["equipment"]["guaranteedAncientTerms"])
        return {
            "baseId": dohdol["id"],
            "name": dohdol["name"],
            "category": dohdol["category"],
            "slot": dohdol["slot"],
            "rarity": rarity,
            "levelReq": int(dohdol["levelReq"]),
            "highQuality": True,
            "baseAttrs": base_attrs,
            "subAttrs": [],
            "terms": roll_dedicated_terms(
                dohdol["slot"], rarity, rng, quality_bonus, force_ancient
            ),
        }

    item, _ = generate_item(
        category=CONFIG.base_item_by_id[base_id].category,
        level=CONFIG.base_item_by_id[base_id].level_req,
        rarity=rarity,
        rng=rng,
        base_id=base_id,
        quality_bonus=quality_bonus,
        high_quality=True,
    )
    return item


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


def regenerate_attrs(
    item: Any, rng: random.Random | None = None, mode: str = "random"
) -> dict[str, Any]:
    """重造：随机基础属性浮动与副属性，保留品阶/类型/等级需求/词条。

    mode="random"（彻底随机）：基础属性与副属性全部重新洗牌，等同重新获得该装备。
    mode="basedOnCurrent"（基于当前）：每条属性在现有值附近独立浮动（可升可降），
    种类不变，保留品质，数值夹在该属性（或该品质）的合法区间内。
    """
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[item.base_id]

    if mode != "basedOnCurrent":
        mult = float(CONFIG.rarities[item.rarity]["multiplier"])
        base_attrs = [
            {
                "attr": entry["attr"],
                "value": round(float(entry["base"]) * mult * _float_factor(rng, CONFIG.base_attr_float), 2),
            }
            for entry in base.base_attrs
        ]
        return {"baseAttrs": base_attrs, "subAttrs": pick_sub_attrs(base, item.rarity, rng)}

    spread = float(CONFIG.economy["refine"]["basedOnCurrentSpreadPct"])
    base_attrs = []
    for entry in item.base_attrs or []:
        lo, hi = base_attr_range(base, item.rarity, entry["attr"])
        value = float_near_current(rng, float(entry["value"]), lo, hi, "common", spread)
        base_attrs.append({**entry, "value": round(value, 2)})

    sub_attrs = []
    for entry in item.sub_attrs or []:
        lo, hi = sub_attr_range(base, item.rarity, entry["attr"])
        cap = sub_attr_cap(base, item.rarity, entry["attr"])
        quality = entry.get("quality", "common")
        value = float_near_current(rng, float(entry["value"]), lo, hi, quality, spread, cap)
        sub_attrs.append({**entry, "value": round(value, 2)})

    return {"baseAttrs": base_attrs, "subAttrs": sub_attrs}


def roll_terms_for_enchant(
    item: Any, rng: random.Random | None = None, mode: str = "random"
) -> list[dict[str, Any]]:
    """附魔：重新随机全部 Buff/Debuff。

    mode="random"（彻底随机）：全部词条重新随机（数量/种类/数值）。
    mode="basedOnCurrent"（基于当前）：保留现有词条种类，每条在现有值附近独立浮动
    （可升可降），保留品质；Debuff 恒为普通。
    """
    rng = rng or random.Random()
    base = CONFIG.base_item_by_id[item.base_id]

    if mode != "basedOnCurrent":
        return roll_terms(base, item.rarity, rng)

    spread = float(CONFIG.economy["enchant"]["basedOnCurrentSpreadPct"])
    out: list[dict[str, Any]] = []
    for term in item.terms or []:
        quality = "common" if term.get("type") == "debuff" else term.get("quality", "common")
        lo, hi = term_range(term["id"])
        value = float_near_current(rng, float(term["value"]), lo, hi, quality, spread)
        out.append({**term, "quality": quality, "value": round(value, 2)})
    return out
