"""高难副本：列表、挑战会话与通关结算。来源：需求「高难副本」

与地区战斗一致的分工：客户端只上报「打完了 / 阵亡了」，奖励与时间下限由服务端裁定。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import AuditLog, RaidProgress, RaidSession
from app.schemas.game import RaidReportRequest, RaidStartRequest, RaidStopRequest
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item
from app.services.loot import chest_by_id
from app.services.progression import apply_exp
from app.services.raid_util import (
    all_raids,
    boss_stats_for_raid,
    eligibility,
    min_clear_seconds,
    raid_by_id,
    top_rarity_required,
)
from app.services.stats import compute_stats
from app.services.valuation import hero_power

router = APIRouter(prefix="/raid", tags=["raid"])
settings = get_settings()

EMPTY_GRANT = {"items": [], "autoSold": [], "autoGold": 0}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _progress(db: DbSession, user_id: int, raid_id: str) -> RaidProgress | None:
    return (
        await db.execute(
            select(RaidProgress).where(RaidProgress.user_id == user_id, RaidProgress.raid_id == raid_id)
        )
    ).scalar_one_or_none()


async def _end_active_sessions(db: DbSession, user_id: int) -> None:
    rows = (
        await db.execute(
            select(RaidSession).where(RaidSession.user_id == user_id, RaidSession.active.is_(True))
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.active = False
        row.ended_at = now


@router.get("")
async def raid_list(db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    stats = compute_stats(hero, items)
    power = hero_power(stats)
    rows = (
        await db.execute(select(RaidProgress).where(RaidProgress.user_id == user.id))
    ).scalars().all()
    progress = {row.raid_id: row for row in rows}

    entries = []
    for raid in all_raids():
        ok, reason = eligibility(raid, hero.level, stats, items)
        row = progress.get(raid["id"])
        entries.append(
            {
                "id": raid["id"],
                "order": raid["order"],
                "difficulty": raid.get("difficulty", "normal"),
                "name": raid["name"],
                "requiredLevel": raid["requiredLevel"],
                "requiredPower": raid["requiredPower"],
                "requiresAllSlots": raid["requiresAllSlots"],
                "minEquipRarity": raid.get("minEquipRarity", "common"),
                "topRarity": raid.get("topRarity"),
                "topRarityCount": top_rarity_required(raid) if raid.get("topRarity") else 0,
                "minAncientTermsPerItem": int(raid.get("minAncientTermsPerItem", 0) or 0),
                "bossNames": [b["name"] for b in raid["bosses"]],
                "dualBoss": len(raid["bosses"]) > 1,
                "reward": raid["reward"],
                "eligible": ok,
                "blockedReason": reason,
                "cleared": bool(row.cleared) if row else False,
                "clearCount": int(row.clear_count) if row else 0,
                "bestClearMs": row.best_clear_ms if row else None,
            }
        )
    return {"raids": entries, "level": hero.level, "power": power}


@router.post("/session/start")
async def start_session(
    payload: RaidStartRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    raid = raid_by_id(payload.raidId)
    if raid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="副本不存在")

    stats = compute_stats(hero, items)
    ok, reason = eligibility(raid, hero.level, stats, items)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    await _end_active_sessions(db, user.id)
    session = RaidSession(user_id=user.id, raid_id=raid["id"], active=True, cleared=False)
    db.add(session)
    await db.commit()

    return {
        "sessionId": session.id,
        "raidId": raid["id"],
        "name": raid["name"],
        "bosses": boss_stats_for_raid(raid, hero.level, stats),
        "enrage": raid["enrage"],
        "reward": raid["reward"],
    }


@router.post("/session/report")
async def report_session(
    payload: RaidReportRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    raid = raid_by_id(payload.raidId)
    if raid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="副本不存在")

    session = (
        await db.execute(
            select(RaidSession).where(
                RaidSession.id == payload.sessionId,
                RaidSession.user_id == user.id,
                RaidSession.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="挑战会话不存在或已结束")
    if session.raid_id != payload.raidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="副本与会话不一致")

    now = datetime.now(timezone.utc)
    server_elapsed_ms = int(max(0.0, (now - _as_utc(session.started_at)).total_seconds() * 1000))
    elapsed_ms = max(int(payload.elapsedMs), server_elapsed_ms)

    session.active = False
    session.ended_at = now

    if not payload.cleared:
        await db.commit()
        return {
            "cleared": False,
            "firstClear": False,
            "gold": int(user.gold),
            "goldGained": 0,
            "items": [],
            "message": "挑战失败，未获得奖励" if payload.died else "已结束挑战",
        }

    stats = compute_stats(hero, items)
    bosses = boss_stats_for_raid(raid, hero.level, stats)
    required_ms = min_clear_seconds(stats, bosses, settings.report_tolerance) * 1000.0
    if elapsed_ms < required_ms:
        db.add(
            AuditLog(
                user_id=user.id,
                reason="raid_too_fast",
                payload={"raidId": raid["id"], "elapsedMs": elapsed_ms, "requiredMs": int(required_ms)},
                rejected=True,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"rejected": ["通关时间低于理论上限"]},
        )

    row = await _progress(db, user.id, raid["id"])
    if row is None:
        row = RaidProgress(user_id=user.id, raid_id=raid["id"], cleared=False, clear_count=0)
        db.add(row)
        await db.flush()

    first_clear = not bool(row.cleared)
    reward = raid["reward"]
    gold = int(reward["firstGold"]) if first_clear else int(reward["repeatGold"])
    user.gold = int(user.gold) + gold

    level_info = {"levelsGained": 0, "exp": hero.exp, "level": hero.level}
    grant = EMPTY_GRANT
    if first_clear:
        level_info = apply_exp(hero, int(reward["firstExp"]))
        chest = chest_by_id(str(reward["chestId"]))
        generated = []
        if chest is not None:
            rng = random.Random()
            for _ in range(int(reward["boxCount"])):
                item, _ = generate_item(chest["category"], hero.level, box_tier=chest["tier"], rng=rng)
                generated.append(item)
        if generated:
            grant = await grant_generated_items(db, user, generated, source=f"raid:{raid['id']}")

    fight_ms = int(payload.fightMs or elapsed_ms)
    row.cleared = True
    row.cleared_at = row.cleared_at or now
    row.clear_count = int(row.clear_count) + 1
    row.best_clear_ms = fight_ms if row.best_clear_ms is None else min(int(row.best_clear_ms), fight_ms)
    session.cleared = True
    await db.commit()

    return {
        "cleared": True,
        "firstClear": first_clear,
        "gold": int(user.gold),
        "goldGained": gold,
        "level": level_info,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "fightMs": fight_ms,
        "message": "首次通关！" if first_clear else "再次通关",
    }


@router.post("/session/stop")
async def stop_session(payload: RaidStopRequest, db: DbSession, user: CurrentUser) -> dict:
    session = (
        await db.execute(
            select(RaidSession).where(RaidSession.id == payload.sessionId, RaidSession.user_id == user.id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="挑战会话不存在")
    session.active = False
    session.ended_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "message": "已退出副本"}
