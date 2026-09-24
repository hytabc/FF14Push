"""交易板参考价：按真实获取来源折算的公允价值。

基准数字由 `scripts/derive-market-reference.py` 生成到 `shared/data/market-reference.json`
（`CONFIG.market_reference`）：装备 = 「品类 × 品阶 × 抽箱等级档位」的期望获取成本，
堆叠物 = 来源成本折算。本模块在此之上叠加装备的属性/词条实时系数，并做统一下限保护。

与 `sell_price`（系统回收价）解耦：参考价通常远高于回收价，两者并存展示。
"""

from __future__ import annotations

from typing import Any

from app.services.dohdol_util import sell_price as stack_sell_price
from app.services.game_config import CONFIG
from app.services.valuation import item_score, sell_price


def _ref_cfg() -> dict[str, Any]:
    return CONFIG.economy["market"].get("reference", {})


def min_price() -> int:
    return int(CONFIG.economy["market"]["minPrice"])


def max_price() -> int:
    return int(CONFIG.economy["market"]["maxPrice"])


def level_band_of(level: int) -> int:
    """物品等级 → 抽箱等级档位（≤ level 的最大档位）。"""
    bands = sorted(int(b["level"]) for b in CONFIG.chests["levelBands"])
    chosen = bands[0] if bands else 1
    for band in bands:
        if int(level) >= band:
            chosen = band
    return chosen


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _equipment_base(category: str, rarity: str, band: int) -> float | None:
    table = CONFIG.market_reference.get("equipment", {})
    entry = (table.get(category) or {}).get(rarity) or {}
    value = entry.get(str(band))
    return float(value) if value else None


def _expected_score(category: str, rarity: str, band: int) -> float:
    table = CONFIG.market_reference.get("expectedScore", {})
    entry = (table.get(category) or {}).get(rarity) or {}
    return float(entry.get(str(band)) or 0.0)


def _term_factor(terms: Any) -> float:
    cfg = _ref_cfg()
    buffs = cfg.get("termValue", {})
    debuffs = cfg.get("debuffValue", {})
    total = 0.0
    for term in terms or []:
        quality = term.get("quality", "common")
        if term.get("type") == "buff":
            total += float(buffs.get(quality, 0.0))
        else:
            total += float(debuffs.get(quality, -0.1))
    return _clamp(1.0 + total, float(cfg.get("termMin", 0.5)), float(cfg.get("termMax", 2.0)))


def equipment_reference(item: Any) -> int | None:
    """抽箱来源装备的参考价；非抽箱来源（生产/采集专用、绝境龙神）返回 None。"""
    category = getattr(item, "category", None)
    rarity = getattr(item, "rarity", None)
    if not category or not rarity:
        return None
    band = level_band_of(int(getattr(item, "level_req", 1) or 1))
    base = _equipment_base(category, rarity, band)
    if base is None:
        return None

    cfg = _ref_cfg()
    expected = _expected_score(category, rarity, band)
    score = item_score(item)
    ratio = (score / expected) if expected > 0 else 1.0
    attr_factor = _clamp(
        ratio ** float(cfg.get("attrExponent", 0.5)),
        float(cfg.get("attrMin", 0.7)),
        float(cfg.get("attrMax", 1.6)),
    )
    value = base * attr_factor * _term_factor(getattr(item, "terms", None))
    floor = max(min_price(), sell_price(item))
    return int(_clamp(round(value), floor, max_price()))


def item_reference(item: Any) -> int:
    """装备参考价：抽箱期望成本 × 属性/词条系数；非抽箱来源回退系统回收价。"""
    ref = equipment_reference(item)
    if ref is None:
        return int(sell_price(item))
    return ref


def stack_reference(kind: str, item_id: str) -> int:
    """堆叠物参考价：来源成本折算值，且不低于系统回收价（种子回收价为 0）。"""
    floor = int(stack_sell_price(kind, item_id))
    table = CONFIG.market_reference.get("stacks", {})
    value = (table.get(kind) or {}).get(item_id)
    if value is None:
        return floor
    return max(int(value), floor)
