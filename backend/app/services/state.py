"""组装前端所需的完整游戏状态快照。"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AutoSellSetting,
    ChestPity,
    ChestUnlock,
    Hero,
    HeroSkillStat,
    Item,
    ItemTag,
    RegionProgress,
    TavernState,
    TutorialProgress,
    User,
)
from app.services.codex import codex_progress
from app.services.difficulty import MAX_LEVEL, active_difficulty
from app.services.dohdol_state import build_dohdol_state
from app.services.drop_luck import chest_luck_max, chest_rarity_luck, cleared_region_count
from app.services.economy import count_by_rarity
from app.services.game_config import CONFIG
from app.services.loot import drop_rate_multiplier
from app.services.progression import exp_to_next, highest_hero_level
from app.services.recruiting import initial_hero, recruit_cost, with_recruit_cost
from app.services.regions_util import boss_stats, kills_required, monster_stats, spawn_interval
from app.services.serialization import hero_to_dict, item_to_dict, loadout, tag_to_dict
from app.services.stats import compute_stats
from app.services.qualification import region_access
from app.services.balance import power_audit
from app.services.valuation import hero_power, sell_price_range


def _placeholder_hero(user_id: int) -> Hero:
    """无英雄时用于展示的默认冒险者（不落库）。来源：需求「无英雄显示为默认冒险者」。"""
    preset = initial_hero()
    return Hero(
        user_id=user_id,
        name=preset["name"],
        level=1,
        exp=0,
        talent=preset["talent"],
        attr_bias=preset["attrBias"],
        strength=preset["strength"],
        agility=preset["agility"],
        intellect=preset["intellect"],
        current_region_id=None,
        region_kill_count=0,
        is_initial=True,
    )


async def build_game_state(
    db: AsyncSession, user: User, hero: Hero | None, items: Sequence[Item] | None = None
) -> dict[str, Any]:
    if items is None:
        items = list((await db.execute(select(Item).where(Item.user_id == user.id))).scalars().all())

    if hero is None:
        hero = _placeholder_hero(user.id)

    stats = compute_stats(hero, items)
    difficulty = active_difficulty(user)

    progress_rows = (
        await db.execute(select(RegionProgress).where(RegionProgress.user_id == user.id))
    ).scalars().all()
    # 生活职业 / 采集钓鱼按「跨难度历史进度」解锁；战斗列表走 /region（按当前难度隔离）。
    access = await region_access(db,user.id,hero,items,None)
    by_region: dict[int, RegionProgress] = {}
    for row in progress_rows:
        current = by_region.get(row.region_id)
        if current is None or (not current.cleared and row.cleared):
            by_region[row.region_id] = row
    progress = {
        region_id: {
            "regionId": region_id,
            "unlocked": not access[region_id],
            "missingConditions": access[region_id],
            "cleared": row.cleared,
            "clearedAt": row.cleared_at.isoformat() if row.cleared_at else None,
            "bestClearMs": row.best_clear_ms,
        }
        for region_id, row in by_region.items()
    }
    # 通关地区数按「全难度去重」统计（周目制下不因切换难度回退），用于爆率与生产状态。
    cleared_count = await cleared_region_count(db, user.id)
    chest_luck, chest_luck_sources = await chest_rarity_luck(db, user.id, hero, items)

    pity_rows = (await db.execute(select(ChestPity).where(ChestPity.user_id == user.id))).scalars().all()
    pity = {
        row.chest_type: {
            "sinceRare": row.since_rare,
            "sinceEpic": row.since_epic,
            "sinceLegendary": row.since_legendary,
        }
        for row in pity_rows
    }

    skill_rows = (
        await db.execute(select(HeroSkillStat).where(HeroSkillStat.hero_id == hero.id))
    ).scalars().all()
    skill_stats = {row.skill_id: row.cast_count for row in skill_rows}

    tutorial = (
        await db.execute(select(TutorialProgress).where(TutorialProgress.user_id == user.id))
    ).scalar_one_or_none()
    tavern = (await db.execute(select(TavernState).where(TavernState.user_id == user.id))).scalar_one_or_none()
    auto_sell = (
        await db.execute(select(AutoSellSetting).where(AutoSellSetting.user_id == user.id))
    ).scalar_one_or_none()
    chest_unlocks = (
        await db.execute(select(ChestUnlock).where(ChestUnlock.user_id == user.id))
    ).scalars().all()
    tag_rows = (
        await db.execute(
            select(ItemTag).where(ItemTag.user_id == user.id).order_by(ItemTag.id)
        )
    ).scalars().all()

    region = CONFIG.region_by_id.get(hero.current_region_id) if hero.current_region_id else None
    if region and access[region["id"]]:
        region = None
    region_detail = None
    if region:
        region_detail = {
            **region,
            "killsRequired": kills_required(region["id"]),
            "spawnInterval": spawn_interval(region["id"]),
            "boss": boss_stats(region["id"], difficulty),
            "monsters": [
                monster_stats(region["id"], t["id"], difficulty) for t in CONFIG.monsters["templates"]
            ],
        }

    return {
        "user": {"id": user.id, "nickname": user.nickname, "gold": int(user.gold)},
        "hero": hero_to_dict(hero, stats),
        "power": hero_power(stats),
        "powerAudit": power_audit(stats),
        "expToNext": exp_to_next(hero.level),
        "catchUpExpBonusPct": 100 if hero.level < await highest_hero_level(db, user.id) else 0,
        "recruitCost": recruit_cost(hero.talent, hero.level),
        "loadout": loadout(items, hero.id),
        "activeHeroId": user.active_hero_id,
        "heroes": [hero_to_dict(h, compute_stats(h, items)) for h in (await db.scalars(select(Hero).where(Hero.user_id == user.id).order_by(Hero.id))).all()],
        "items": [item_to_dict(item, sell_price_range(item)) for item in items],
        "itemCounts": count_by_rarity(items),
        "tags": [tag_to_dict(t) for t in tag_rows],
        "regionProgress": progress,
        "currentRegion": region_detail,
        "difficulty": {
            "level": difficulty,
            "unlocked": int(user.battle_difficulty_max),
            "maxLevel": MAX_LEVEL,
        },
        "clearedRegions": cleared_count,
        "dropRateMultiplier": drop_rate_multiplier(cleared_count),
        "chestRarityLuck": {
            "luck": round(chest_luck, 6),
            "luckMax": chest_luck_max(),
            "sources": chest_luck_sources,
        },
        "pity": pity,
        "skillStats": skill_stats,
        "codex": await codex_progress(db, user.id),
        "tutorial": {
            "currentStep": tutorial.current_step if tutorial else 1,
            "completed": bool(tutorial.completed) if tutorial else False,
            "skipped": bool(tutorial.skipped) if tutorial else False,
        },
        "tavern": {
            "candidate": with_recruit_cost(tavern.candidate, hero.level) if tavern and tavern.candidate else None
        },
        "settings": {
            "autoSell": {
                "enabled": bool(auto_sell.enabled) if auto_sell else False,
                "rarities": list(auto_sell.rarities)
                if auto_sell
                else list(CONFIG.economy["sell"]["autoSellRarities"]),
            },
            # 已一次性金币解锁的连抽档位（如 50 / 100 连）；账号级。
            "chestUnlocks": sorted(int(row.draw_count) for row in chest_unlocks),
        },
        "dohdol": await build_dohdol_state(
            db, user.id, items, hero.level, cleared_count
        ),
    }
