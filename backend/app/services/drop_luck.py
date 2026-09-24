"""抽箱品阶概率的「幸运来源」与归一化。

只提升装备「品阶」的抽取概率（宝箱 / BOSS / 副本宝箱），不影响金币与经验，
从而在给予进度奖励的同时保证无法刷取金币。

来源与生产品阶概率共用同一套归一化（见 `luck_sources.luck_progress`）：
p = Σ weight × min(值 / ref, 1)，luck = luckMax × p。各 ref 为对应来源的真实最大值
（含太古词条），因此「上限」只有所有来源（通关地区 / 装备品阶幸运 / 料理秘药 /
远征通关 / 高难通关 / 彩蛋）全满才能达到。
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RegionProgress
from app.services import consumables
from app.services.egg_heroes import luck_bonus
from app.services.game_config import CONFIG
from app.services.luck_sources import (
    coop_clear_score,
    luck_progress,
    raid_clear_score,
)
from app.services.stats import aggregate_equipment, hero_items


def chest_rarity_sources() -> dict[str, Any]:
    return dict((CONFIG.chests.get("rarityLuck") or {}).get("sources") or {})


def chest_luck_max() -> float:
    return float((CONFIG.chests.get("rarityLuck") or {}).get("luckMax", 1.0))


async def cleared_region_count(db: AsyncSession, user_id: int) -> int:
    """已通关地区数（按 region_id 去重）：难度分级后跨难度只计一次，进度不因切换回退。"""
    total = await db.scalar(
        select(func.count(func.distinct(RegionProgress.region_id)))
        .select_from(RegionProgress)
        .where(RegionProgress.user_id == user_id, RegionProgress.cleared.is_(True))
    )
    return int(total or 0)


def egg_luck(hero: Any) -> float:
    """彩蛋英雄被动的装备品阶幸运加成（如「种田JPG」的幸运）。"""
    return luck_bonus(getattr(hero, "egg_id", None))


async def chest_rarity_luck(
    db: AsyncSession,
    user_id: int,
    hero: Any = None,
    items: Sequence[Any] | None = None,
    cleared_count: int | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """抽箱品阶概率的 luck 系数与来源明细（与生产同源的归一化）。

    省略 hero / items 时装备品阶幸运与彩蛋来源记 0（如新手指引结算无英雄上下文）。
    调用方若已算过「已通关地区数」可传入 `cleared_count`，避免重复的 count(distinct) 查询。
    """
    gear_mods = (
        aggregate_equipment(hero_items(items, getattr(hero, "id", None))).term_mods
        if items is not None
        else {}
    )
    values = {
        "clearedRegions": float(
            await cleared_region_count(db, user_id) if cleared_count is None else cleared_count
        ),
        "gearPct": float(gear_mods.get("chestRarityPct", 0.0)),
        "consumablePct": await consumables.chest_luck(db, user_id),
        "coopClears": await coop_clear_score(db, user_id),
        "raidClears": await raid_clear_score(db, user_id),
        "egg": egg_luck(hero),
    }
    progress, factors = luck_progress(chest_rarity_sources(), values)
    return chest_luck_max() * progress, factors
