"""战力与出售价格计算。来源：PRD 排行榜 2.2、出售 3.2、三属性 5.4"""

from __future__ import annotations

from typing import Any

from app.services.game_config import CONFIG
from app.services.stats import HeroStats

POWER_WEIGHTS: dict[str, float] = CONFIG.economy["power"]["weights"]

TERM_QUALITY_SELL = {
    quality: float(rule["sellValue"]) for quality, rule in CONFIG.terms["qualityRules"].items()
}
TERM_DEBUFF_SELL = {q: float(v) for q, v in CONFIG.terms["debuffValue"].items()}


def hero_power(stats: HeroStats) -> int:
    """战力 = Σ(属性 × 权重)。

    与 `attrs_score` 共用同一权重表，使「装备战力之和」与「英雄战力」口径一致：
    战力更高的装备换上后，英雄战力必然不降。暴击/直击/信念按面板值×权重计入
    （其收益已由权重标定，不再额外叠加等级相关的速率项，避免两套口径打架）。
    """
    w = POWER_WEIGHTS
    total = 0.0
    total += stats.max_hp * w.get("hp", 0)
    total += stats.attack * w.get("attack", 0)
    total += stats.magic_attack * w.get("magicAttack", 0)
    total += stats.phys_def * w.get("physDef", 0)
    total += stats.magic_def * w.get("magicDef", 0)
    total += stats.crit_value * w.get("crit", 0)
    total += stats.dh_value * w.get("dh", 0)
    total += stats.det_value * w.get("det", 0)
    total += stats.attack_speed_pct * w.get("sks", 0)
    total += stats.haste_pct * w.get("sps", 0)
    total += stats.hp_regen * w.get("regen", 0)
    total += stats.lifesteal_pct * w.get("lifesteal", 0)
    total += stats.dodge_pct * w.get("dodge", 0)
    total += stats.hit_rate_pct * w.get("acc", 0)
    total += stats.tenacity_pct * w.get("tenacity", 0)
    return int(total)


def attrs_score(base_attrs: Any, sub_attrs: Any) -> float:
    """基础属性 + 副属性的总评分 = Σ(属性值 × 权重)。"""
    score = 0.0
    for entry in base_attrs or []:
        score += float(entry["value"]) * POWER_WEIGHTS.get(entry["attr"], 1.0)
    for entry in sub_attrs or []:
        score += float(entry["value"]) * POWER_WEIGHTS.get(entry["attr"], 1.0)
    return score


def item_score(item: Any) -> float:
    """装备总属性评分 = Σ(属性值 × 权重)。"""
    return attrs_score(item.base_attrs, item.sub_attrs)


def terms_score(terms: Any) -> float:
    """词条总价值：Buff 取正、Debuff 取负，数值越大越好（用于「基于当前」的比较）。"""
    total = 0.0
    for term in terms or []:
        magnitude = abs(float(term.get("value", 0))) * POWER_WEIGHTS.get(term.get("stat"), 1.0)
        total += magnitude if term.get("type") == "buff" else -magnitude
    return total


def ancient_count(entries: Any) -> int:
    """统计条目中的太古数量（副属性或词条通用）。"""
    return sum(1 for entry in entries or [] if entry.get("quality") == "ancient")


def attr_factor(item: Any) -> float:
    """属性加成系数 = 1 + attrBonusMax × score / (score + scoreHalf)。

    用饱和曲线封顶（1 → 1 + attrBonusMax），避免卖价随属性评分线性无上限增长：
    箱子价格是固定的，item_score 却随英雄等级/品阶膨胀，线性系数会让「买箱卖装备」稳赚。
    """
    cfg = CONFIG.economy["sell"]
    score = max(0.0, item_score(item))
    half = max(1.0, float(cfg["scoreHalf"]))
    return 1.0 + float(cfg["attrBonusMax"]) * score / (score + half)


def term_value_coefficient(item: Any) -> float:
    """Buff 价值系数 = Σ(Buff 价值) − Σ(Debuff 价值)。"""
    total = 0.0
    for term in item.terms or []:
        quality = term.get("quality", "common")
        if term.get("type") == "buff":
            total += TERM_QUALITY_SELL.get(quality, 0.1)
        else:
            total += TERM_DEBUFF_SELL.get(quality, -0.15)
    return total


def sell_price(item: Any, rng: Any | None = None) -> int:
    """出售价格 = 底价 × 品阶系数 × 属性系数 × (1 + Buff价值系数) × (1 ± 10%)。"""
    cfg = CONFIG.economy["sell"]
    base_price = float(cfg["basePrice"])
    rarity_coef = float(CONFIG.rarities[item.rarity]["sellCoef"])
    buff_coef = term_value_coefficient(item)

    price = base_price * rarity_coef * attr_factor(item) * max(0.1, 1.0 + buff_coef)
    spread = float(cfg["randomFloat"])
    if rng is not None:
        price *= 1.0 + rng.uniform(-spread, spread)
    else:
        price *= 1.0  # 展示价不带随机浮动
    return max(1, int(price))


def sell_price_range(item: Any) -> tuple[int, int]:
    spread = float(CONFIG.economy["sell"]["randomFloat"])
    base = sell_price(item)
    return max(1, int(base * (1 - spread))), int(base * (1 + spread))
