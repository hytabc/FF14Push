"""挖宝：花金币进入 5 层副本，逐层战斗 → 开箱 → 选门。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import (
    CurrentHero,
    CurrentItems,
    CurrentSockets,
    CurrentUser,
    DbSession,
)
from app.schemas.game import (
    TreasureChestOpenRequest,
    TreasureDoorRequest,
    TreasureFloorClearRequest,
    TreasureGambleRequest,
    TreasureGambleStopRequest,
    TreasureRunRequest,
)
from app.services import consumables, treasure
from app.services.egg_heroes import exp_bonus_pct
from app.services.stats import compute_stats

router = APIRouter(prefix="/treasure", tags=["treasure"])


async def _term_mods(db, user, hero, items, sockets) -> dict[str, float]:
    """金币 / 经验加成：装备词条 + 药水食物 + 彩蛋被动（与地区战斗结算同源）。"""
    stats = compute_stats(hero, items, sockets)
    mods = dict(stats.term_mods)
    for key, value in (await consumables.exp_gold_mods(db, user.id)).items():
        mods[key] = mods.get(key, 0.0) + float(value)
    egg = exp_bonus_pct(stats.egg_id)
    if egg:
        mods["expGainPct"] = mods.get("expGainPct", 0.0) + egg
    return mods


@router.get("/state")
async def treasure_state(db: DbSession, user: CurrentUser) -> dict:
    return await treasure.state(db, user.id)


@router.post("/start")
async def treasure_start(
    db: DbSession, user: CurrentUser, hero: CurrentHero
) -> dict:
    result = await treasure.start(db, user, hero)
    await db.commit()
    return result


@router.post("/floor/clear")
async def treasure_floor_clear(
    payload: TreasureFloorClearRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.clear_floor(db, user, run)
    await db.commit()
    return result


@router.post("/gamble")
async def treasure_gamble(
    payload: TreasureGambleRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.gamble(db, user, run, payload.guess)
    await db.commit()
    return result


@router.post("/gamble/stop")
async def treasure_gamble_stop(
    payload: TreasureGambleStopRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.stop_gamble(db, user, run)
    await db.commit()
    return result


@router.post("/chest/open")
async def treasure_chest_open(
    payload: TreasureChestOpenRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
    sockets: CurrentSockets,
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    mods = await _term_mods(db, user, hero, items, sockets)
    result = await treasure.open_chest(db, user, hero, run, mods)
    await db.commit()
    return result


@router.post("/door/choose")
async def treasure_door_choose(
    payload: TreasureDoorRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.choose_door(db, user, run, payload.door)
    await db.commit()
    return result


@router.post("/retry")
async def treasure_retry(
    payload: TreasureRunRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.retry(db, user, run)
    await db.commit()
    return result


@router.post("/abandon")
async def treasure_abandon(
    payload: TreasureRunRequest, db: DbSession, user: CurrentUser
) -> dict:
    run = await treasure.load_run(db, user.id, payload.runId)
    result = await treasure.abandon(db, user, run)
    await db.commit()
    return result
