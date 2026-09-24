"""种田：账号级田地。初始 2 片、最多 12 片，用金币扩张；作物按真实时间生长（离线也生长）。

服务端权威：成熟判定只看服务端时间戳（种植时刻 + 阶段数 × 每阶段秒数），客户端时间不参与。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FarmPlot, User
from app.services import dohdol_util
from app.services.game_config import CONFIG
from app.services.progression import LEVEL_CAP, grant_levels
from app.services.roster import owned_hero


def initial_plots() -> int:
    return int(CONFIG.farm["initialPlots"])


def max_plots() -> int:
    return int(CONFIG.farm["maxPlots"])


def expansion_costs() -> list[int]:
    return [int(cost) for cost in CONFIG.farm["expansionCosts"]]


def stages() -> int:
    return int(CONFIG.farm["stages"])


def stage_seconds() -> float:
    return float(CONFIG.farm["stageSeconds"])


def total_seconds() -> float:
    return stages() * stage_seconds()


def seed_def(seed_id: str) -> dict[str, Any] | None:
    return CONFIG.seed_by_id.get(seed_id)


def unlocked_count(user: User) -> int:
    value = int(getattr(user, "farm_unlocked", 0) or 0)
    return max(initial_plots(), min(max_plots(), value))


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:  # SQLite 返回 naive datetime
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def _plot_row(db: AsyncSession, user_id: int, index: int) -> FarmPlot | None:
    return (
        await db.execute(
            select(FarmPlot).where(FarmPlot.user_id == user_id, FarmPlot.index == index)
        )
    ).scalar_one_or_none()


async def farm_view(db: AsyncSession, user: User) -> dict[str, Any]:
    unlocked = unlocked_count(user)
    rows = {
        int(row.index): row
        for row in (
            await db.execute(select(FarmPlot).where(FarmPlot.user_id == user.id))
        ).scalars().all()
    }
    now = datetime.now(timezone.utc)
    plots = []
    for index in range(max_plots()):
        entry: dict[str, Any] = {
            "index": index,
            "locked": index >= unlocked,
            "seedId": None,
            "seedName": None,
            "plantedAt": None,
            "matureAt": None,
            "stage": 0,
            "stages": stages(),
            "stageSeconds": stage_seconds(),
            "remainingMs": 0,
            "ready": False,
        }
        row = rows.get(index)
        if row is not None and row.seed_id and row.planted_at:
            planted = _as_utc(row.planted_at)
            elapsed = max(0.0, (now - planted).total_seconds())
            total = total_seconds()
            entry.update(
                {
                    "seedId": row.seed_id,
                    "seedName": dohdol_util.material_name(row.seed_id),
                    "plantedAt": int(planted.timestamp() * 1000),
                    "matureAt": int((planted.timestamp() + total) * 1000),
                    "stage": min(stages(), int(elapsed // stage_seconds())),
                    "remainingMs": int(max(0.0, total - elapsed) * 1000),
                    "ready": elapsed >= total,
                }
            )
        plots.append(entry)

    costs = expansion_costs()
    next_cost = costs[unlocked - initial_plots()] if unlocked < max_plots() else None
    counts = await dohdol_util.stack_counts(db, user.id, dohdol_util.STACK_SEED)
    seeds = [
        {
            "id": seed["id"],
            "name": seed["name"],
            "desc": seed.get("desc", ""),
            "yield": seed.get("yield", {}),
            "count": int(counts.get(seed["id"], 0)),
        }
        for seed in CONFIG.farm["seeds"]
    ]
    return {
        "unlocked": unlocked,
        "initialPlots": initial_plots(),
        "maxPlots": max_plots(),
        "expansionCost": next_cost,
        "expansionCosts": costs,
        "stages": stages(),
        "stageSeconds": stage_seconds(),
        "plots": plots,
        "seeds": seeds,
        "gold": int(user.gold),
    }


async def expand(db: AsyncSession, user: User) -> dict[str, Any]:
    unlocked = unlocked_count(user)
    if unlocked >= max_plots():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="田地已达上限")
    cost = expansion_costs()[unlocked - initial_plots()]
    if int(user.gold) < cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}"
        )
    user.gold = int(user.gold) - cost
    user.farm_unlocked = unlocked + 1
    await db.flush()
    return {"cost": cost, "state": await farm_view(db, user)}


async def plant(db: AsyncSession, user: User, index: int, seed_id: str) -> dict[str, Any]:
    if seed_def(seed_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="种子不存在")
    if not 0 <= index < max_plots():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="田地不存在")
    if index >= unlocked_count(user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该田地尚未解锁")

    row = await _plot_row(db, user.id, index)
    if row is not None and row.seed_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该田地已有作物")

    if not await dohdol_util.stack_consume(
        db, user.id, dohdol_util.STACK_SEED, seed_id, 1
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="种子不足")

    now = datetime.now(timezone.utc)
    if row is None:
        db.add(FarmPlot(user_id=user.id, index=index, seed_id=seed_id, planted_at=now))
    else:
        row.seed_id = seed_id
        row.planted_at = now
    await db.flush()
    return {"state": await farm_view(db, user)}


async def harvest(
    db: AsyncSession,
    user: User,
    index: int,
    hero_id: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    row = await _plot_row(db, user.id, index)
    if row is None or not row.seed_id or not row.planted_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该田地没有作物")

    planted = _as_utc(row.planted_at)
    elapsed = (datetime.now(timezone.utc) - planted).total_seconds()
    if elapsed < total_seconds():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="作物尚未成熟")

    seed = seed_def(row.seed_id) or {}
    spec = seed.get("yield", {})
    kind = spec.get("type")

    if kind == "gold":
        amount = int(spec.get("amount", 0))
        user.gold = int(user.gold) + amount
        result: dict[str, Any] = {"type": "gold", "amount": amount, "gold": int(user.gold)}
    elif kind == "heroLevel":
        if hero_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择要提升的英雄")
        hero = await owned_hero(db, user.id, hero_id)
        if int(hero.level) >= LEVEL_CAP:
            if not confirm:
                # 满级英雄：前端据此弹窗，由玩家选择「取消收获」或「执意收获」。
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "hero_max_level", "level": int(hero.level), "heroName": hero.name},
                )
            result = {
                "type": "heroLevel",
                "heroId": int(hero.id),
                "heroName": hero.name,
                "levelsGained": 0,
                "level": int(hero.level),
                "noEffect": True,
            }
        else:
            info = grant_levels(hero, int(spec.get("levels", 1)))
            result = {
                "type": "heroLevel",
                "heroId": int(hero.id),
                "heroName": hero.name,
                "levelsGained": int(info["levelsGained"]),
                "level": int(info["level"]),
                "noEffect": False,
            }
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的种子产出")

    # 收获后田地清空（满级「执意收获」同样消耗种子）。
    row.seed_id = None
    row.planted_at = None
    await db.flush()
    return {"result": result, "state": await farm_view(db, user)}
