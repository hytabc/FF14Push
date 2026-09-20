"""品阶抽取、保底与掉落。来源：PRD 2.8.2 / 2.8.3 / 2.7.2"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from app.services.game_config import CONFIG

RARITY_ORDER: list[str] = list(CONFIG.rarity_order)
PITY_COUNTERS = {"rare": "since_rare", "epic": "since_epic", "legendary": "since_legendary"}


def rarity_tier(rarity: str) -> int:
    return int(CONFIG.rarities[rarity]["tier"])


def rarity_at_least(rarity: str, minimum: str) -> bool:
    return rarity_tier(rarity) >= rarity_tier(minimum)


@dataclass
class PityState:
    since_rare: int = 0
    since_epic: int = 0
    since_legendary: int = 0

    def counter(self, minimum: str) -> int:
        return int(getattr(self, PITY_COUNTERS[minimum]))


def rarity_weights(box_tier: str, luck: float = 0.0) -> list[float]:
    """箱子品阶概率分布。

    luck>0 时按品阶线性加权 `base[i] × (1 + luck × i)` 后归一化，使高品阶更易出现。
    """
    base = [float(CONFIG.rarities[r]["boxChance"][box_tier]) for r in RARITY_ORDER]
    if luck <= 0:
        return base
    weights = [base[i] * (1.0 + luck * i) for i in range(len(base))]
    total = sum(weights)
    return [w / total for w in weights] if total > 0 else base


def roll_rarity(box_tier: str, rng: random.Random | None = None, luck: float = 0.0) -> str:
    """按箱子类型抽取品阶（不含保底）。box_tier: normal | advanced"""
    rng = rng or random
    probs = rarity_weights(box_tier, luck)
    roll = rng.random()
    cumulative = 0.0
    for rarity, chance in zip(RARITY_ORDER, probs):
        cumulative += chance
        if roll < cumulative:
            return rarity
    return RARITY_ORDER[-1]


def drop_rate_multiplier(cleared_regions: int) -> float:
    """按通关地区数计算的品阶爆率倍率（封顶，且不低于 1）。

    仅提高装备品阶抽取概率，不含金币/经验，避免刷取金币。
    """
    cfg = CONFIG.chests.get("dropRate", {})
    per = float(cfg.get("perClearedRegion", 0.0))
    cap = float(cfg.get("maxMultiplier", 1.0))
    return min(cap, max(1.0, 1.0 + per * max(0, int(cleared_regions))))


def advance_pity(pity: PityState, rarity: str) -> PityState:
    """抽到结果后推进保底计数：达到对应品阶则重置该档计数。"""
    new = PityState(
        since_rare=pity.since_rare + 1,
        since_epic=pity.since_epic + 1,
        since_legendary=pity.since_legendary + 1,
    )
    if rarity_at_least(rarity, "rare"):
        new.since_rare = 0
    if rarity_at_least(rarity, "epic"):
        new.since_epic = 0
    if rarity_at_least(rarity, "legendary"):
        new.since_legendary = 0
    return new


def draw_rarity(
    box_tier: str, pity: PityState, rng: random.Random | None = None, luck: float = 0.0
) -> tuple[str, PityState]:
    """完整抽箱：抽品阶 → 推进计数 → 保底判定。返回 (最终品阶, 新计数)。"""
    rng = rng or random
    rolled = roll_rarity(box_tier, rng, luck)
    state = advance_pity(pity, rolled)
    final = rolled
    for rule in CONFIG.chests["pity"]:
        minimum = str(rule["minRarity"])
        if state.counter(minimum) >= int(rule["count"]) and not rarity_at_least(final, minimum):
            final = minimum
    if final != rolled:
        state = advance_pity(pity, final)
    return final, state


def boss_box_for_region(region_id: int) -> str:
    """按地区序号决定 BOSS 宝箱品质。来源：PRD 地区 4.4"""
    for rule in CONFIG.chests["bossRewardBoxByTier"]:
        if region_id <= int(rule["maxRegionIndex"]):
            return str(rule["chestId"])
    return str(CONFIG.chests["bossRewardBoxByTier"][-1]["chestId"])


def chest_by_id(chest_id: str) -> dict[str, Any] | None:
    for chest in CONFIG.chests["chests"]:
        if chest["id"] == chest_id:
            return chest
    return None


def base_items_for_category(category: str) -> list[Any]:
    return [b for b in CONFIG.base_items if b.category == category]
