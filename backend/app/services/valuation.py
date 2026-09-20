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
    """战力 = Σ(属性 × 权重)。"""
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
    total += (stats.crit_rate_pct + stats.crit_damage_pct + stats.dh_rate_pct + stats.det_bonus_pct) * 10.0
    return int(total)


def item_score(item: Any) -> float:
    """装备总属性评分 = Σ(属性值 × 权重)。"""
    score = 0.0
    for entry in item.base_attrs or []:
        score += float(entry["value"]) * POWER_WEIGHTS.get(entry["attr"], 1.0)
    for entry in item.sub_attrs or []:
        score += float(entry["value"]) * POWER_WEIGHTS.get(entry["attr"], 1.0)
    return score


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
    """出售价格 = 底价 × 品阶系数 × (1 + 属性评分/100) × (1 + Buff价值系数) × (1 ± 10%)。"""
    cfg = CONFIG.economy["sell"]
    base_price = float(cfg["basePrice"])
    rarity_coef = float(CONFIG.rarities[item.rarity]["sellCoef"])
    score_coef = item_score(item) / float(cfg["scoreDivisor"])
    buff_coef = term_value_coefficient(item)

    price = base_price * rarity_coef * (1.0 + score_coef) * max(0.1, 1.0 + buff_coef)
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
