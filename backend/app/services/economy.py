"""合成 / 出售 / 重造 / 附魔的成本与规划。来源：PRD 2.9 / 出售 3.2 / 重造 4.2 / 附魔 5.2"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.game_config import CONFIG

ROUTES = {r["from"]: r for r in CONFIG.crafting["routes"]}
REQUIRED = int(CONFIG.crafting["requiredCount"])
CRAFT_CATEGORIES = list(CONFIG.crafting["categories"])


def _level_cost_scale(block: dict[str, Any], level: int) -> tuple[int, int]:
    """等级价格系数（分数：分子 / 分母）= 1 + (num / den) × (等级 − 1)。

    用整数分数结算，避免 25/3 这类系数在小数乘法下被截断（100 级神话「基于当前」精确为 750,000）。
    1 级恒为 1（分子 = 分母），故低等级装备价格不变。
    """
    num = int(block.get("costLevelGrowthNum", 0))
    den = int(block.get("costLevelGrowthDen", 1)) or 1
    lv = max(1, int(level or 1))
    return den + num * (lv - 1), den


def is_exclusive_base(base_id: str | None) -> bool:
    """是否属于世界BOSS 专属系列（绝境龙神）：重造 / 附魔成本 ×exclusiveCostMultiplier。"""
    base = CONFIG.base_item_by_id.get(base_id or "")
    return bool(getattr(base, "exclusive", False))


def _exclusive_scale(exclusive: bool) -> int:
    """绝境龙神成本倍率（整数结算，避免截断）。"""
    return int(CONFIG.economy.get("exclusiveCostMultiplier", 1)) if exclusive else 1


def refine_cost(
    rarity: str, refine_count: int = 0, mode: str = "random", level: int = 1, exclusive: bool = False
) -> int:
    """重造费用 = 品阶基准价 × (1 + costGrowthPerRefine × 已重造次数) × 等级系数。

    递增不封顶：同一件装备重造越多次越贵，避免无限重造刷属性。
    等级系数 = 1 + 2/27 × (等级 − 1)：1 级 ×1、100 级 ×25/3 ≈ 8.33，物品等级越高越贵。
    mode="basedOnCurrent"（基于当前，每条属性小幅浮动）价格 × basedOnCurrentCostMultiplier。
    """
    block = CONFIG.economy["refine"]
    base = int(CONFIG.rarities[rarity]["refineCost"])
    growth = float(block["costGrowthPerRefine"])
    cost = int(base * (1.0 + growth * max(0, int(refine_count))))
    if mode == "basedOnCurrent":
        cost = int(cost * float(block["basedOnCurrentCostMultiplier"]))
    num, den = _level_cost_scale(block, level)
    return cost * num // den * _exclusive_scale(exclusive)


def enchant_cost(rarity: str, mode: str = "random", level: int = 1, exclusive: bool = False) -> int:
    block = CONFIG.economy["enchant"]
    base = int(CONFIG.rarities[rarity]["enchantCost"])
    if mode == "basedOnCurrent":
        base = int(base * float(block["basedOnCurrentCostMultiplier"]))
    num, den = _level_cost_scale(block, level)
    return base * num // den * _exclusive_scale(exclusive)


def craft_fee(rarity: str) -> int | None:
    route = ROUTES.get(rarity)
    return int(route["fee"]) if route else None


def craft_target(rarity: str) -> str | None:
    route = ROUTES.get(rarity)
    return str(route["to"]) if route else None


def count_by_rarity(items: Iterable[Any], category: str | None = None, only_unequipped: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {r: 0 for r in CONFIG.rarity_order}
    for item in items:
        if category and item.category != category:
            continue
        if only_unequipped and item.equipped_slot is not None:
            continue
        counts[item.rarity] = counts.get(item.rarity, 0) + 1
    return counts


def build_craft_plan(items: Iterable[Any], category: str, auto: bool = True) -> dict[str, Any]:
    """生成合成预览。

    返回 {"steps": [...], "totalFee": int, "delta": {rarity: 净变化}, "produced": {rarity: 数量}}

    auto=True：从最低品阶向上逐级推演，中间产物直接投入下一级；
    auto=False：只展示当前各品阶「够 16 件」的可合成数量。
    """
    counts = count_by_rarity(items, category, only_unequipped=True)
    stock = dict(counts)
    steps: list[dict[str, Any]] = []
    delta: dict[str, int] = {r: 0 for r in CONFIG.rarity_order}

    for rarity in CONFIG.rarity_order:
        target = craft_target(rarity)
        if target is None:
            continue
        available = stock.get(rarity, 0)
        crafts = available // REQUIRED

        if crafts == 0:
            if not auto:
                steps.append(
                    {"from": rarity, "to": target, "available": available, "crafts": 0, "fee": craft_fee(rarity), "totalFee": 0}
                )
            continue

        fee = int(craft_fee(rarity) or 0)
        steps.append(
            {
                "from": rarity,
                "to": target,
                "available": available,
                "crafts": crafts,
                "fee": fee,
                "totalFee": crafts * fee,
            }
        )
        delta[rarity] = delta.get(rarity, 0) - crafts * REQUIRED
        if auto:
            stock[rarity] = available - crafts * REQUIRED
            stock[target] = stock.get(target, 0) + crafts
        else:
            delta[target] = delta.get(target, 0) + crafts

    if auto:
        for rarity in CONFIG.rarity_order:
            delta[rarity] = stock.get(rarity, 0) - counts.get(rarity, 0)

    produced = {r: v for r, v in delta.items() if v > 0}
    return {
        "steps": steps,
        "totalFee": sum(int(s["totalFee"]) for s in steps),
        "delta": delta,
        "produced": produced,
        "counts": counts,
    }
