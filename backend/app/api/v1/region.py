"""地区关卡：列表、进入、推进。来源：PRD 地区关卡系统

按当前地区战斗难度作用域：每个难度独立记录解锁/通关（周目制）。
难度 0 = 基础进度（历史数据）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import BattleSession, RegionProgress
from app.schemas.game import RegionEnterRequest
from app.services.codex import codex_progress
from app.services.difficulty import MAX_LEVEL, active_difficulty
from app.services.game_config import CONFIG
from app.services.regions_util import boss_stats, kills_required, spawn_interval

from app.services.qualification import ensure_region_progress, region_access, require_region

router = APIRouter(prefix="/region", tags=["region"])


async def _progress_map(db: DbSession, user_id: int, difficulty: int) -> dict[int, RegionProgress]:
    rows = (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user_id, RegionProgress.difficulty == difficulty
            )
        )
    ).scalars().all()
    return {row.region_id: row for row in rows}


def _recommended_level(region: dict) -> int:
    return int(region["levelMin"])


@router.get("")
async def list_regions(db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    difficulty = active_difficulty(user)
    progress = await _progress_map(db, user.id, difficulty)
    access = await region_access(db,user.id,hero,items,difficulty)
    entries = []
    for region in CONFIG.regions["regions"]:
        row = progress.get(region["id"])
        entries.append(
            {
                **region,
                "killsRequired": kills_required(region["id"]),
                "spawnInterval": spawn_interval(region["id"]),
                "unlocked": not access[region["id"]],
                "cleared": bool(row.cleared) if row else False,
                "bestClearMs": row.best_clear_ms if row else None,
                "recommendedLevel": _recommended_level(region),
                "lockedHint": "；".join(access[region["id"]]),
                "missingConditions": access[region["id"]],
                "isCurrent": hero.current_region_id == region["id"],
            }
        )
    chapters = [
        {
            **chapter,
            "regionIds": [r["id"] for r in CONFIG.regions["regions"] if r["chapter"] == chapter["id"]],
        }
        for chapter in CONFIG.regions["chapters"]
    ]
    return {
        "chapters": chapters,
        "regions": entries,
        "currentRegionId": hero.current_region_id,
        "killCount": int(hero.region_kill_count),
        "difficulty": {"level": difficulty, "unlocked": int(user.battle_difficulty_max), "maxLevel": MAX_LEVEL},
        "codex": await codex_progress(db, user.id),
    }


@router.get("/current")
async def current_region(db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    difficulty = active_difficulty(user)
    region_id = hero.current_region_id or 1
    region = CONFIG.region_by_id[region_id]
    await require_region(db,user.id,hero,items,region_id,difficulty)
    return {
        "region": region,
        "killsRequired": kills_required(region_id),
        "spawnInterval": spawn_interval(region_id),
        "boss": boss_stats(region_id, difficulty),
        "killCount": int(hero.region_kill_count),
    }


@router.post("/enter")
async def enter_region(
    payload: RegionEnterRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    """手动切换地区；切换后击杀计数归零。来源：PRD 地区 6.2"""
    difficulty = active_difficulty(user)
    region = CONFIG.region_by_id.get(payload.regionId)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地区不存在")

    await require_region(db,user.id,hero,items,payload.regionId,difficulty)
    row = await ensure_region_progress(db, user.id, difficulty, payload.regionId)
    row.unlocked = True

    # 结束进行中的会话（切换地区即暂停）
    active = (
        await db.execute(
            select(BattleSession).where(BattleSession.user_id == user.id, BattleSession.active.is_(True))
        )
    ).scalars().all()
    for session in active:
        session.active = False

    hero.current_region_id = payload.regionId
    hero.region_kill_count = 0
    await db.commit()

    return {
        "region": region,
        "killsRequired": kills_required(payload.regionId),
        "spawnInterval": spawn_interval(payload.regionId),
        "boss": boss_stats(payload.regionId, difficulty),
        "killCount": 0,
    }


@router.post("/advance")
async def advance(db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    """击败 BOSS 后前往下一地区。"""
    difficulty = active_difficulty(user)
    current = hero.current_region_id or 1
    next_id = current + 1
    if next_id not in CONFIG.region_by_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已是最后一个地区")

    await require_region(db,user.id,hero,items,next_id,difficulty)
    row = await ensure_region_progress(db, user.id, difficulty, next_id)
    row.unlocked = True

    hero.current_region_id = next_id
    hero.region_kill_count = 0
    await db.commit()
    return {
        "region": CONFIG.region_by_id[next_id],
        "killsRequired": kills_required(next_id),
        "spawnInterval": spawn_interval(next_id),
        "boss": boss_stats(next_id, difficulty),
    }
