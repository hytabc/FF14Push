"""开发用：推导交易板参考价基准表 → `shared/data/market-reference.json`。

参考价 = 按真实获取来源折算的公允价值：

- **装备**：抽箱期望成本（普通/高级箱与 16 合 1 合成路线取最省，含保底）按
  「品类 × 品阶 × 抽箱等级档位」落表；另存该格子的期望属性评分，供运行时算属性/词条系数。
- **堆叠物**：
  - 材料 / 半成品 / 鱼：档位价值（`materials.json` / `fish.json` 的 sell）× materialMultiplier。
  - 药水 / 食物：配方材料成本（Σ 输入 × 参考价 ÷ 产出数量，多配方取最小）。
  - 魔晶石 / 种子：挖宝入场成本的期望分摊（按奖励权重与每局期望产出数量、单件权重归一）。

只写文件、不含时间戳（保证 diff 稳定），含 meta 供测试复算。运行：`python scripts/derive-market-reference.py`
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.game_config import CONFIG  # noqa: E402
from app.services.item_factory import generate_by_rarity  # noqa: E402
from app.services.loot import pity_rarity_distribution  # noqa: E402
from app.services.valuation import attrs_score  # noqa: E402

DRAWS = 2_000_000
SEED = 20240924
SCORE_SAMPLES = 5000
OUT = ROOT / "shared" / "data" / "market-reference.json"

RARITY_ORDER = list(CONFIG.rarity_order)
REQUIRED = int(CONFIG.crafting["requiredCount"])
FEES = {r["from"]: int(r["fee"]) for r in CONFIG.crafting["routes"]}


def _ref_cfg() -> dict[str, Any]:
    return CONFIG.economy["market"]["reference"]


# ------------------------------------------------------------------ 装备
def _category_prices() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for chest in CONFIG.chests["chests"]:
        out.setdefault(chest["category"], {})[chest["tier"]] = int(chest["price"])
    return out


def _bands() -> list[int]:
    return sorted(int(b["level"]) for b in CONFIG.chests["levelBands"])


def _band_multipliers() -> dict[int, float]:
    return {int(b["level"]): float(b["priceMultiplier"]) for b in CONFIG.chests["levelBands"]}


def _expected_score(category: str, band: int, rarity: str) -> float:
    """该格子（品类·档位·品阶）生成装备的属性评分均值（固定种子，可复现）。"""
    rng = random.Random(SEED)
    total = 0.0
    for _ in range(SCORE_SAMPLES):
        item = generate_by_rarity(category, band, rarity, rng=rng)
        total += attrs_score(item["baseAttrs"], item["subAttrs"])
    return total / SCORE_SAMPLES


def _equipment_table() -> tuple[dict, dict]:
    prices = _category_prices()
    mult = _band_multipliers()
    dists = {tier: pity_rarity_distribution(tier, DRAWS, SEED) for tier in ("normal", "advanced")}

    equipment: dict[str, dict[str, dict[str, int]]] = {}
    expected: dict[str, dict[str, dict[str, float]]] = {}
    for category in sorted(prices):
        equipment[category] = {r: {} for r in RARITY_ORDER}
        expected[category] = {r: {} for r in RARITY_ORDER}
        for band in _bands():
            prev_base: float | None = None
            prev_rarity: str | None = None
            for rarity in RARITY_ORDER:
                routes = []
                for tier, price in prices[category].items():
                    p = dists[tier].get(rarity, 0.0)
                    if p > 0:
                        routes.append(price * mult[band] / p)
                if prev_base is not None and prev_rarity is not None:
                    routes.append(REQUIRED * prev_base + FEES.get(prev_rarity, 0))
                value = min(routes) if routes else 0.0
                equipment[category][rarity][str(band)] = int(round(value))
                expected[category][rarity][str(band)] = round(_expected_score(category, band, rarity), 3)
                prev_base = value
                prev_rarity = rarity
    return equipment, expected


# ------------------------------------------------------------------ 堆叠物
def _material_references() -> dict[str, int]:
    mult = float(_ref_cfg().get("materialMultiplier", 1.0))
    return {
        mid: max(0, int(round(int(m.get("sell", 0)) * mult)))
        for mid, m in CONFIG.material_by_id.items()
    }


def _consumable_references(materials: dict[str, int]) -> dict[str, dict[str, int]]:
    """药水 / 食物：配方材料成本（Σ 输入 × 参考价 ÷ 产出数量），多配方取最小。"""
    best: dict[tuple[str, str], float] = {}
    for recipe in CONFIG.recipes["recipes"]:
        output = recipe["output"]
        kind = output["kind"]
        if kind != "consumable":
            continue
        item = CONFIG.consumable_by_id.get(output["itemId"])
        if item is None:
            continue
        cost = 0.0
        for entry in recipe["inputs"]:
            cost += float(materials.get(entry["itemId"], 0)) * int(entry["count"])
        count = max(1, int(output.get("count", 1)))
        unit = cost / count
        key = (str(item["kind"]), output["itemId"])
        if key not in best or unit < best[key]:
            best[key] = unit

    out: dict[str, dict[str, int]] = {}
    for (kind, item_id), unit in best.items():
        out.setdefault(kind, {})[item_id] = int(round(unit))
    return out


def _treasure_expected_counts() -> dict[str, float]:
    """挖宝每局对各堆叠 id 的期望产出数量（解析式，含门 50/50 与逐层条目/数量递增）。"""
    cfg = CONFIG.treasure
    weights = cfg["rewardWeights"]
    total_w = sum(float(v) for v in weights.values()) or 1.0
    floors = int(cfg["floors"])
    correct = float(cfg["correctChance"])
    e_base = int(cfg["rewardsPerFloor"]["base"])
    e_per = int(cfg["rewardsPerFloor"]["perFloor"])
    q_base = int(cfg["stackQtyPerFloor"]["base"])
    q_per = int(cfg["stackQtyPerFloor"]["perFloor"])
    tipos = [t["id"] for t in CONFIG.materia["types"]]

    counts: dict[str, float] = defaultdict(float)
    for floor in range(1, floors + 1):
        reach = correct ** (floor - 1)
        entries = e_base + e_per * (floor - 1)
        qty = q_base + q_per * (floor - 1)

        p_materia = float(weights.get("materia", 0.0)) / total_w
        low, high = cfg["materiaLevelByFloor"][floor - 1]
        levels = list(range(int(low), int(high) + 1))
        per_entry = reach * entries * p_materia
        for tipo in tipos:
            for level in levels:
                counts[f"m_{tipo}_{level}"] += per_entry * (1.0 / len(tipos)) * (1.0 / len(levels)) * qty

        p_seed = float(weights.get("seed", 0.0)) / total_w
        seeds = CONFIG.farm["seeds"]
        per_seed_entry = reach * entries * p_seed
        for seed in seeds:
            counts[seed["id"]] += per_seed_entry * (1.0 / len(seeds)) * qty
    return dict(counts)


def _treasure_references() -> dict[str, dict[str, int]]:
    cfg = CONFIG.treasure
    entry = float(cfg["entryCost"])
    weights = cfg["rewardWeights"]
    total_w = sum(float(v) for v in weights.values()) or 1.0
    expected = _treasure_expected_counts()
    tipos = [t["id"] for t in CONFIG.materia["types"]]

    out: dict[str, dict[str, int]] = {"materia": {}, "seed": {}}

    # 魔晶石：单件权重 = sell(level) × typeFactor（同等级各类型 statValue 归一）。
    def _weight(item_id: str) -> float:
        m = CONFIG.materia_by_id[item_id]
        level = int(m["level"])
        values = [float(CONFIG.materia_by_id[f"m_{t}_{level}"]["value"]) for t in tipos]
        mean = sum(values) / len(values) if values else 1.0
        return float(m["sell"]) * (float(m["value"]) / mean if mean else 1.0)

    allocated = entry * (float(weights.get("materia", 0.0)) / total_w)
    denom = sum(expected.get(mid, 0.0) * _weight(mid) for mid in CONFIG.materia_by_id)
    scale = allocated / denom if denom > 0 else 0.0
    for mid in CONFIG.materia_by_id:
        out["materia"][mid] = int(round(scale * _weight(mid)))

    # 种子：按均分权重分摊；可确定收益的种子（金币）再以收益 × seedYieldFactor 兜底。
    seed_alloc = entry * (float(weights.get("seed", 0.0)) / total_w)
    seeds = CONFIG.farm["seeds"]
    seed_factor = float(_ref_cfg().get("seedYieldFactor", 0.0))
    for seed in seeds:
        count = expected.get(seed["id"], 0.0)
        base = seed_alloc * (1.0 / len(seeds)) / count if count > 0 else 0.0
        yield_spec = seed.get("yield") or {}
        if yield_spec.get("type") == "gold":
            base = max(base, float(yield_spec.get("amount", 0)) * seed_factor)
        out["seed"][seed["id"]] = int(round(base))
    return out


def main() -> None:
    equipment, expected = _equipment_table()
    materials = _material_references()
    consumables = _consumable_references(materials)
    treasure_refs = _treasure_references()

    stacks: dict[str, dict[str, int]] = {
        "material": materials,
        "potion": consumables.get("potion", {}),
        "food": consumables.get("food", {}),
        "materia": treasure_refs["materia"],
        "seed": treasure_refs["seed"],
    }

    payload = {
        "$comment": "由 scripts/derive-market-reference.py 生成，请勿手改。装备=抽箱期望成本（品类×品阶×档位），堆叠物=来源成本折算；运行时再叠加属性/词条系数（见 economy.json:market.reference）。",
        "meta": {
            "draws": DRAWS,
            "seed": SEED,
            "scoreSamples": SCORE_SAMPLES,
            "pityDistribution": {
                tier: {r: round(p, 10) for r, p in pity_rarity_distribution(tier, DRAWS, SEED).items()}
                for tier in ("normal", "advanced")
            },
        },
        "equipment": equipment,
        "expectedScore": expected,
        "stacks": stacks,
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
