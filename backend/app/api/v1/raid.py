"""高难副本：列表、挑战会话与通关结算。来源：需求「高难副本」

与地区战斗一致的分工：客户端只上报「打完了 / 阵亡了」，奖励与时间下限由服务端裁定。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import RaidProgress, RaidSession
from app.schemas.game import (
    RaidChestClaimRequest,
    RaidReportRequest,
    RaidStartRequest,
    RaidStopRequest,
)
from app.services.drop_luck import rarity_luck, user_drop_rate
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item, generate_item_for_slot
from app.services.loot import chest_by_id
from app.services.progression import apply_exp
from app.services.raid_util import (
    all_raids,
    boss_stats_for_raid,
    eligibility,
    raid_by_id,
    top_rarity_required,
)
from app.services.regions_util import apply_exp_bonus
from app.services.slots_util import selectable_base_slots
from app.services.stats import compute_stats
from app.services.valuation import hero_power

router = APIRouter(prefix="/raid", tags=["raid"])

EMPTY_GRANT = {"items": [], "autoSold": [], "autoGold": 0}
# 高难宝箱可自选的装备种类（底材 slot）
CHEST_SLOTS = selectable_base_slots()


async def _pending_chest_count(db: DbSession, user_id: int) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(RaidSession.pending_chest), 0)).where(
            RaidSession.user_id == user_id
        )
    )
    return int(total or 0)


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
    return {
        "raids": entries,
        "level": hero.level,
        "power": power,
        # 待开启的高难宝箱（自选装备种类）
        "chest": {"count": await _pending_chest_count(db, user.id), "slots": CHEST_SLOTS},
    }


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
        "difficulty": raid.get("difficulty", "normal"),
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

    # 副本不做击杀时间校验：装备极佳时可能远快于服务端理论上限，避免误判为作弊。
    stats = compute_stats(hero, items)

    row = await _progress(db, user.id, raid["id"])
    if row is None:
        row = RaidProgress(user_id=user.id, raid_id=raid["id"], cleared=False, clear_count=0)
        db.add(row)
        await db.flush()

    first_clear = not bool(row.cleared)
    reward = raid["reward"]
    gold = int(reward["firstGold"]) if first_clear else int(reward["repeatGold"])
    user.gold = int(user.gold) + gold

    # 通关经验：首通用 firstExp，重刷用 repeatExp（高难副本的 repeatExp 更高）
    raw_exp = int(reward["firstExp"]) if first_clear else int(reward.get("repeatExp", 0))
    exp_gained = apply_exp_bonus(raw_exp, stats.term_mods) if raw_exp > 0 else 0
    level_info = apply_exp(hero, exp_gained)

    grant = EMPTY_GRANT
    pending_chest = 0
    if bool(reward.get("slotChoice")):
        # 高难宝箱：每次通关都掉落，由玩家自选装备种类后在结算界面开启
        session.pending_chest = int(session.pending_chest or 0) + int(reward["boxCount"])
        pending_chest = int(session.pending_chest)
    elif first_clear:
        chest = chest_by_id(str(reward["chestId"]))
        generated = []
        if chest is not None:
            rng = random.Random()
            luck = rarity_luck(await user_drop_rate(db, user.id))
            for _ in range(int(reward["boxCount"])):
                item, _ = generate_item(
                    chest["category"], hero.level, box_tier=chest["tier"], rng=rng, luck=luck
                )
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
        "expGained": exp_gained,
        "level": level_info,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "fightMs": fight_ms,
        "pendingChest": {"count": pending_chest, "slots": CHEST_SLOTS} if pending_chest else None,
        "message": "首次通关！" if first_clear else "再次通关",
    }


@router.post("/chest/claim")
async def claim_chest(
    payload: RaidChestClaimRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
) -> dict:
    """开启高难宝箱：自选装备种类后一次性开出所有待开启的宝箱。"""
    if payload.slot not in CHEST_SLOTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的装备种类")

    sessions = (
        await db.execute(
            select(RaidSession).where(
                RaidSession.user_id == user.id, RaidSession.pending_chest > 0
            )
        )
    ).scalars().all()
    total = sum(int(row.pending_chest or 0) for row in sessions)
    if total <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有待开启的高难宝箱")

    raid = raid_by_id(sessions[0].raid_id)
    box_tier = str((raid or {}).get("reward", {}).get("boxTier", "boss"))
    luck = rarity_luck(await user_drop_rate(db, user.id))
    rng = random.Random()
    generated = [
        generate_item_for_slot(hero.level, payload.slot, box_tier=box_tier, rng=rng, luck=luck)
        for _ in range(total)
    ]
    for row in sessions:
        row.pending_chest = 0

    grant = await grant_generated_items(db, user, generated, source="raid-chest", rng=rng)
    await db.commit()

    return {
        "gold": int(user.gold),
        "count": total,
        "slot": payload.slot,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "pendingChest": await _pending_chest_count(db, user.id),
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
