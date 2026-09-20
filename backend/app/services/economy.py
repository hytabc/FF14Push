"""合成 / 出售 / 重造 / 附魔的成本与规划。来源：PRD 2.9 / 出售 3.2 / 重造 4.2 / 附魔 5.2"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.game_config import CONFIG

ROUTES = {r["from"]: r for r in CONFIG.crafting["routes"]}
REQUIRED = int(CONFIG.crafting["requiredCount"])
CRAFT_CATEGORIES = list(CONFIG.crafting["categories"])


def refine_cost(rarity: str, refine_count: int = 0, mode: str = "random") -> int:
    """重造费用 = 品阶基准价 × (1 + costGrowthPerRefine × 已重造次数)。

    递增不封顶：同一件装备重造越多次越贵，避免无限重造刷属性。
    mode="basedOnCurrent"：在当前基础上随机，价格 × basedOnCurrentCostMultiplier。
    """
    base = int(CONFIG.rarities[rarity]["refineCost"])
    growth = float(CONFIG.economy["refine"]["costGrowthPerRefine"])
    cost = int(base * (1.0 + growth * max(0, int(refine_count))))
    if mode == "basedOnCurrent":
        cost = int(cost * float(CONFIG.economy["refine"]["basedOnCurrentCostMultiplier"]))
    return cost


def enchant_cost(rarity: str, mode: str = "random") -> int:
    base = int(CONFIG.rarities[rarity]["enchantCost"])
    if mode == "basedOnCurrent":
        base = int(base * float(CONFIG.economy["enchant"]["basedOnCurrentCostMultiplier"]))
    return base


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
