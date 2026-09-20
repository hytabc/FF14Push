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


def roll_rarity(box_tier: str, rng: random.Random | None = None) -> str:
    """按箱子类型抽取品阶（不含保底）。box_tier: normal | advanced"""
    rng = rng or random
    roll = rng.random()
    cumulative = 0.0
    for rarity in RARITY_ORDER:
        cumulative += float(CONFIG.rarities[rarity]["boxChance"][box_tier])
        if roll < cumulative:
            return rarity
    return RARITY_ORDER[-1]


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


def draw_rarity(box_tier: str, pity: PityState, rng: random.Random | None = None) -> tuple[str, PityState]:
    """完整抽箱：抽品阶 → 推进计数 → 保底判定。返回 (最终品阶, 新计数)。"""
    rng = rng or random
    rolled = roll_rarity(box_tier, rng)
    state = advance_pity(pity, rolled)
    final = rolled
    for rule in CONFIG.chests["pity"]:
        minimum = str(rule["minRarity"])
        if state.counter(minimum) >= int(rule["count"]) and not rarity_at_least(final, minimum):
            final = minimum
    if final != rolled:
        state = advance_pity(pity, final)
    return final, state


def equipment_drop_chance() -> float:
    return float(CONFIG.monsters["equipmentDropChance"])


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
