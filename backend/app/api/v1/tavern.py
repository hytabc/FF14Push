"""英雄酒馆：刷新、招募、解雇。来源：PRD 招募系统"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.core.deps import CurrentItems, CurrentUser, DbSession, OptionalHero
from app.models import Hero, Item, TavernState
from app.schemas.game import TavernRecruitRequest, TavernRefreshRequest
from app.services.game_config import CONFIG
from app.services.recruiting import generate_candidate, recruit_cost
from app.services.serialization import hero_to_dict
from app.services.stats import compute_stats

router = APIRouter(prefix="/tavern", tags=["tavern"])

MAX_HEROES = 1


async def _tavern(db: DbSession, user_id: int) -> TavernState:
    row = (await db.execute(select(TavernState).where(TavernState.user_id == user_id))).scalar_one_or_none()
    if row is None:
        row = TavernState(user_id=user_id, candidate=generate_candidate(1))
        db.add(row)
        await db.flush()
    return row


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 读回的时间戳可能是 naive，统一按 UTC 处理，避免 aware/naive 相减报错。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _free_refresh_state(row: TavernState, now: datetime, interval: int) -> tuple[bool, datetime | None]:
    """返回（是否可免费刷新，下次可免费刷新的时间点）。"""
    last = _as_utc(row.free_refresh_used_at)
    if last is None:
        return True, None
    next_at = last + timedelta(seconds=interval)
    if now >= next_at:
        return True, None
    return False, next_at


@router.get("")
async def tavern_state(db: DbSession, user: CurrentUser, hero: OptionalHero) -> dict:
    row = await _tavern(db, user.id)
    if row.candidate is None:
        row.candidate = generate_candidate(hero.level if hero else 1)
        await db.commit()
    level = hero.level if hero else 1
    cost = recruit_cost(row.candidate["talent"], level) if row.candidate else 0
    interval = int(CONFIG.talents["freeRefreshIntervalSec"])
    free_available, next_at = _free_refresh_state(row, datetime.now(timezone.utc), interval)
    return {
        "candidate": row.candidate,
        "recruitCost": cost,
        "refreshCost": int(CONFIG.talents["refreshCost"]),
        "freeRefreshIntervalSec": interval,
        "freeRefreshAvailable": free_available,
        "nextFreeRefreshAt": next_at.isoformat() if next_at else None,
        "currentHero": (
            {
                "name": hero.name,
                "level": hero.level,
                "talent": hero.talent,
                "attrBias": hero.attr_bias,
                "isInitial": hero.is_initial,
            }
            if hero
            else None
        ),
    }


@router.post("/refresh")
async def refresh(
    payload: TavernRefreshRequest, db: DbSession, user: CurrentUser, hero: OptionalHero
) -> dict:
    """刷新候选：200 金币 / 次，或每 10 分钟免费 1 次。来源：PRD 招募 2.3"""
    row = await _tavern(db, user.id)
    now = datetime.now(timezone.utc)
    interval = int(CONFIG.talents["freeRefreshIntervalSec"])
    free_available, next_free_at = _free_refresh_state(row, now, interval)

    if payload.useGold:
        # 金币刷新：始终按价扣费，不影响免费额度
        cost = int(CONFIG.talents["refreshCost"])
        if int(user.gold) < cost:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}")
        user.gold = int(user.gold) - cost
    else:
        # 免费刷新：冷却中直接拒绝，绝不静默扣金币
        if not free_available:
            remain = max(1, int((next_free_at - now).total_seconds())) if next_free_at else interval
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"免费刷新冷却中，还需 {remain} 秒，可使用金币刷新",
            )
        cost = 0
        row.free_refresh_used_at = now

    row.candidate = generate_candidate(hero.level if hero else 1)
    row.refreshed_at = now
    await db.commit()

    free_available, next_free_at = _free_refresh_state(row, now, interval)
    return {
        "candidate": row.candidate,
        "gold": int(user.gold),
        "cost": cost,
        "recruitCost": recruit_cost(row.candidate["talent"], hero.level if hero else 1),
        "freeRefreshAvailable": free_available,
        "nextFreeRefreshAt": next_free_at.isoformat() if next_free_at else None,
    }


@router.post("/recruit")
async def recruit(
    payload: TavernRecruitRequest, db: DbSession, user: CurrentUser, hero: OptionalHero, items: CurrentItems
) -> dict:
    """招募新英雄并替换当前英雄。来源：PRD 招募 2.4"""
    if not payload.confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先确认替换")

    row = await _tavern(db, user.id)
    candidate = row.candidate
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有候选英雄")

    current_level = hero.level if hero else 1
    cost = recruit_cost(candidate["talent"], current_level)
    if int(user.gold) < cost:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}")

    # 旧英雄装备卸下回背包（装备归属账号，不会丢失）
    await db.execute(update(Item).where(Item.user_id == user.id).values(equipped_slot=None))

    old_hero_id = hero.id if hero else None
    user.gold = int(user.gold) - cost
    if hero is not None:
        await db.delete(hero)
        await db.flush()

    new_hero = Hero(
        user_id=user.id,
        name=candidate["name"],
        level=1,
        exp=0,
        talent=candidate["talent"],
        attr_bias=candidate["attrBias"],
        strength=candidate["strength"],
        agility=candidate["agility"],
        intellect=candidate["intellect"],
        current_region_id=1,
        region_kill_count=0,
        is_initial=False,
    )
    db.add(new_hero)
    await db.flush()

    row.candidate = generate_candidate(new_hero.level)
    await db.commit()

    stats = compute_stats(new_hero, [])
    return {
        "gold": int(user.gold),
        "cost": cost,
        "previousHeroId": old_hero_id,
        "hero": hero_to_dict(new_hero, stats),
        "nextCandidate": row.candidate,
    }


@router.post("/dismiss")
async def dismiss(db: DbSession, user: CurrentUser, hero: OptionalHero) -> dict:
    """解雇当前英雄：装备卸下保留，等级经验不保留。"""
    if hero is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前没有英雄")
    if hero.is_initial:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="初始英雄不可解雇，请先招募新英雄进行替换",
        )
    await db.execute(update(Item).where(Item.user_id == user.id).values(equipped_slot=None))
    await db.delete(hero)
    await db.commit()
    return {"ok": True, "message": "英雄已解雇，装备已卸下并保留在背包中"}
