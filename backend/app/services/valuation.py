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
    """递减后的战斗属性贡献；非战斗成长不参与。"""
    from app.services.balance import power_audit
    return power_audit(stats)['total']


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
