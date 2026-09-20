"""地区关卡：列表、进入、推进。来源：PRD 地区关卡系统"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentUser, DbSession
from app.models import BattleSession, RegionProgress
from app.schemas.game import RegionEnterRequest
from app.services.codex import codex_progress
from app.services.game_config import CONFIG
from app.services.regions_util import boss_stats, kills_required, spawn_interval

router = APIRouter(prefix="/region", tags=["region"])


async def _progress_map(db: DbSession, user_id: int) -> dict[int, RegionProgress]:
    rows = (
        await db.execute(select(RegionProgress).where(RegionProgress.user_id == user_id))
    ).scalars().all()
    return {row.region_id: row for row in rows}


def _recommended_level(region: dict) -> int:
    return int(region["levelMin"])


@router.get("")
async def list_regions(db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    progress = await _progress_map(db, user.id)
    entries = []
    for region in CONFIG.regions["regions"]:
        row = progress.get(region["id"])
        entries.append(
            {
                **region,
                "killsRequired": kills_required(region["id"]),
                "spawnInterval": spawn_interval(region["id"]),
                "unlocked": bool(row.unlocked) if row else False,
                "cleared": bool(row.cleared) if row else False,
                "bestClearMs": row.best_clear_ms if row else None,
                "recommendedLevel": _recommended_level(region),
                "lockedHint": "需击败前一地区 BOSS 解锁",
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
        "codex": await codex_progress(db, user.id),
    }


@router.get("/current")
async def current_region(db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    region_id = hero.current_region_id or 1
    region = CONFIG.region_by_id[region_id]
    return {
        "region": region,
        "killsRequired": kills_required(region_id),
        "spawnInterval": spawn_interval(region_id),
        "boss": boss_stats(region_id),
        "killCount": int(hero.region_kill_count),
    }


@router.post("/enter")
async def enter_region(
    payload: RegionEnterRequest, db: DbSession, user: CurrentUser, hero: CurrentHero
) -> dict:
    """手动切换地区；切换后击杀计数归零。来源：PRD 地区 6.2"""
    region = CONFIG.region_by_id.get(payload.regionId)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地区不存在")

    row = (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user.id, RegionProgress.region_id == payload.regionId
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.unlocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该地区尚未解锁")

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
        "boss": boss_stats(payload.regionId),
        "killCount": 0,
    }


@router.post("/advance")
async def advance(db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    """击败 BOSS 后前往下一地区。"""
    current = hero.current_region_id or 1
    next_id = current + 1
    if next_id not in CONFIG.region_by_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已是最后一个地区")

    row = (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user.id, RegionProgress.region_id == next_id
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.unlocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需先击败当前地区 BOSS")

    hero.current_region_id = next_id
    hero.region_kill_count = 0
    await db.commit()
    return {
        "region": CONFIG.region_by_id[next_id],
        "killsRequired": kills_required(next_id),
        "spawnInterval": spawn_interval(next_id),
        "boss": boss_stats(next_id),
    }
