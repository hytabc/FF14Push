"""通关进度 → 品阶爆率倍率。

只提升装备「品阶」的抽取概率（宝箱 / BOSS / 副本宝箱），不影响金币与经验，
从而在给予进度奖励的同时保证无法刷取金币。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RegionProgress
from app.services.loot import drop_rate_multiplier


async def cleared_region_count(db: AsyncSession, user_id: int) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(RegionProgress)
        .where(RegionProgress.user_id == user_id, RegionProgress.cleared.is_(True))
    )
    return int(total or 0)


async def user_drop_rate(db: AsyncSession, user_id: int) -> float:
    return drop_rate_multiplier(await cleared_region_count(db, user_id))


def rarity_luck(multiplier: float) -> float:
    """爆率倍率 → 品阶抽取的 luck 系数。"""
    return max(0.0, float(multiplier) - 1.0)
