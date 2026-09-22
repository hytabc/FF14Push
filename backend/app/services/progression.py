"""英雄经验与升级。来源：PRD 2.11"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Hero

from app.services.game_config import CONFIG

LEVEL_CAP = int(CONFIG.heroes["levelCap"])


def exp_to_next(level: int) -> int:
    cfg = CONFIG.heroes["expCurve"]
    multiplier = 1.0
    start = int(cfg["reductionStartLevel"])
    if level >= start:
        end = int(cfg["reductionEndLevel"])
        fraction = min(1.0, (level - start) / max(1, end - start))
        multiplier = float(cfg["startMultiplier"]) + fraction * (
            float(cfg["endMultiplier"]) - float(cfg["startMultiplier"])
        )
    return max(1, round(float(cfg["base"]) * float(cfg["growth"]) ** max(0, level - 1) * multiplier))


def exp_to_next_cached(level: int) -> int:
    return exp_to_next(level)


def apply_exp(hero: Any, amount: int) -> dict[str, int]:
    """结算经验，返回升级信息。"""
    if amount <= 0:
        return {"levelsGained": 0, "exp": hero.exp, "level": hero.level}

    hero.exp += int(amount)
    gained = 0
    while hero.level < LEVEL_CAP:
        need = exp_to_next(hero.level)
        if hero.exp < need:
            break
        hero.exp -= need
        hero.level += 1
        gained += 1
    if hero.level >= LEVEL_CAP:
        hero.exp = 0
    return {"levelsGained": gained, "exp": hero.exp, "level": hero.level}


async def highest_hero_level(db: AsyncSession, user_id: int) -> int:
    """只比较该账号当前拥有的英雄，不包含其他玩家或登记克隆。"""
    return int(await db.scalar(select(func.max(Hero.level)).where(Hero.user_id == user_id)) or 1)


def catch_up_exp(hero: Any, amount: int, highest_level: int) -> int:
    """战斗经验追赶：现有加成结算后再 +100%，追平最高等级后的部分不翻倍。"""
    amount = max(0, int(amount))
    target = min(LEVEL_CAP, highest_level)
    if amount == 0 or hero.level >= target:
        return amount
    gap = max(0, sum(exp_to_next(level) for level in range(hero.level, target)) - int(hero.exp))
    # 每 1 点原始经验额外给 1 点；奇数差额的最后 1 点按普通经验获得。
    return amount + min(amount, gap // 2)


async def combat_exp(db: AsyncSession, hero: Hero, amount: int) -> int:
    return catch_up_exp(hero, amount, await highest_hero_level(db, hero.user_id))
