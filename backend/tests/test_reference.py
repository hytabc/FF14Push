"""交易板参考价：派生表结构、单调性、与保底分布自洽，以及装备/堆叠物实时折算。"""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any

from app.services import reference
from app.services.game_config import CONFIG
from app.services.item_factory import generate_by_rarity
from app.services.loot import RARITY_ORDER

EQUIP = CONFIG.market_reference["equipment"]
EXPECTED = CONFIG.market_reference["expectedScore"]
BANDS = sorted(int(b["level"]) for b in CONFIG.chests["levelBands"])
MULT = {int(b["level"]): float(b["priceMultiplier"]) for b in CONFIG.chests["levelBands"]}
FEES = {r["from"]: int(r["fee"]) for r in CONFIG.crafting["routes"]}
REQUIRED = int(CONFIG.crafting["requiredCount"])
CATEGORY_PRICES: dict[str, dict[str, int]] = {}
for _chest in CONFIG.chests["chests"]:
    CATEGORY_PRICES.setdefault(_chest["category"], {})[_chest["tier"]] = int(_chest["price"])


def _fake_item(category: str, level: int, rarity: str, *, rng_seed: int = 1) -> Any:
    generated = generate_by_rarity(category, level, rarity, rng=random.Random(rng_seed))
    return SimpleNamespace(
        base_id=generated["baseId"],
        category=generated["category"],
        rarity=generated["rarity"],
        level_req=generated["levelReq"],
        high_quality=False,
        base_attrs=generated["baseAttrs"],
        sub_attrs=generated["subAttrs"],
        terms=generated["terms"],
    )


def test_table_covers_all_combinations() -> None:
    for category in CATEGORY_PRICES:
        for rarity in RARITY_ORDER:
            for band in BANDS:
                assert EQUIP[category][rarity][str(band)] > 0
                assert EXPECTED[category][rarity][str(band)] > 0


def test_base_price_monotonic_in_rarity() -> None:
    for category in CATEGORY_PRICES:
        for band in BANDS:
            values = [EQUIP[category][rarity][str(band)] for rarity in RARITY_ORDER]
            assert values == sorted(values), f"{category} band {band} 品阶基准价非单调递增"


def test_base_price_monotonic_in_band() -> None:
    for category in CATEGORY_PRICES:
        for rarity in RARITY_ORDER:
            values = [EQUIP[category][rarity][str(band)] for band in BANDS]
            assert values == sorted(values), f"{category} {rarity} 档位基准价非单调递增"


def test_base_matches_pity_distribution() -> None:
    """派生表 = min(普通/高级箱期望成本, 16 合 1 合成)，用 meta 的保底分布复算校验。"""
    dists = CONFIG.market_reference["meta"]["pityDistribution"]
    for category, prices in CATEGORY_PRICES.items():
        for band in BANDS:
            prev_base: int | None = None
            prev_rarity: str | None = None
            for rarity in RARITY_ORDER:
                routes = [price * MULT[band] / dists[tier][rarity] for tier, price in prices.items()]
                if prev_base is not None and prev_rarity is not None:
                    routes.append(REQUIRED * prev_base + FEES.get(prev_rarity, 0))
                expected = min(routes)
                actual = EQUIP[category][rarity][str(band)]
                assert abs(actual - expected) <= 1, f"{category} {rarity} band {band}: {actual} vs {expected}"
                prev_base = actual
                prev_rarity = rarity


def test_equipment_reference_bounds_and_score_monotonic() -> None:
    item = _fake_item("weapon", 100, "mythic")
    ref = reference.item_reference(item)
    assert reference.min_price() <= ref <= reference.max_price()
    assert ref >= 0

    # 属性翻倍 → 属性评分更高 → 参考价不低于原值。
    boosted = _fake_item("weapon", 100, "mythic")
    boosted.base_attrs = [{**e, "value": float(e["value"]) * 2} for e in boosted.base_attrs]
    boosted.sub_attrs = [{**e, "value": float(e["value"]) * 2} for e in boosted.sub_attrs]
    assert reference.item_reference(boosted) >= ref


def test_equipment_reference_uses_level_band() -> None:
    # 高等级装备映射到更高的档位，基准价更高（同品阶）。
    low = reference.level_band_of(1)
    high = reference.level_band_of(100)
    assert low == 1 and high == 100
    assert reference.level_band_of(85) == 80
    assert EQUIP["weapon"]["rare"][str(high)] > EQUIP["weapon"]["rare"][str(low)]


def test_non_chest_equipment_falls_back_to_sell() -> None:
    # 非抽箱来源（这里用不存在的品类）回退系统回收价。
    item = _fake_item("weapon", 1, "common")
    item.category = "doh_tool"
    assert reference.equipment_reference(item) is None
    assert reference.item_reference(item) == reference.sell_price(item)


def test_stack_references() -> None:
    # 材料：档位价值（= sell × materialMultiplier）。
    mult = float(CONFIG.economy["market"]["reference"]["materialMultiplier"])
    for item_id in ("g_ore", "ore1", "ore40", "h_plank"):
        sell = int(CONFIG.material_by_id[item_id]["sell"])
        assert reference.stack_reference("material", item_id) == round(sell * mult)

    # 魔晶石 / 种子：来源成本折算为正，且不低于回收价。
    for item_id in ("m_crit_1", "m_crit_5", "m_str_1"):
        ref = reference.stack_reference("materia", item_id)
        assert ref >= int(CONFIG.materia_by_id[item_id]["sell"])
        assert ref > 0
    for seed in CONFIG.farm["seeds"]:
        assert reference.stack_reference("seed", seed["id"]) > 0

    # 药水 / 食物：不低于回收价。
    for item in CONFIG.consumables["items"]:
        assert reference.stack_reference(item["kind"], item["id"]) >= int(item["sell"])
