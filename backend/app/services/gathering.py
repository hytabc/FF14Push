"""采集：服务端权威会话与结算。

与战斗一致：窗口只取服务端时钟，按理论采集速率封顶，离开页面即暂停（不做离线收益）。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivitySession, Item, RegionProgress, User
from app.services import consumables, dohdol_util
from app.services.game_config import CONFIG
from app.services.playtime import add_play_ms


async def cleared_max_region(db: AsyncSession, user_id: int) -> int:
    rows = (
        await db.execute(
            select(RegionProgress.region_id).where(
                RegionProgress.user_id == user_id, RegionProgress.cleared.is_(True)
            )
        )
    ).scalars().all()
    return max([int(r) for r in rows], default=0)


async def start_gather(
    db: AsyncSession, user: User, items: Sequence[Item], job_id: str, region_id: int
) -> dict[str, Any]:
    if dohdol_util.kind_of_job(job_id) != "dol" or job_id == "FSH":
        raise ValueError("采集职业无效")
    node = CONFIG.gather_node_by.get((region_id, job_id))
    if node is None:
        raise ValueError("该地区没有对应的采集点")
    if region_id > await cleared_max_region(db, user.id) + 1:
        raise ValueError("该地区尚未解锁")

    level = await progress_level(db, user.id, "dol")
    if level < int(node["levelReq"]):
        raise ValueError(f"采集等级不足，需要采集等级 {node['levelReq']}")

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now,
        user_id=user.id, kind="gather", job_id=job_id, region_id=region_id, active=True, credit=0.0
    )
    db.add(session)
    await db.flush()
    equip = dohdol_util.equipped_bonus(items)
    seconds = dohdol_util.gather_seconds_per_action(equip.get("gatherSpeedPct", 0.0))
    return {
        "sessionId": session.id,
        "jobId": job_id,
        "regionId": region_id,
        "cycle": dohdol_util.cycle_info(seconds, 0.0, now),
    }


async def progress_level(db: AsyncSession, user_id: int, kind: str) -> int:
    from app.models import DohDolProgress

    row = (
        await db.execute(
            select(DohDolProgress).where(DohDolProgress.user_id == user_id, DohDolProgress.kind == kind)
        )
    ).scalar_one_or_none()
    return int(row.level) if row else 1


async def report_gather(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    from app.models import DohDolProgress

    node = CONFIG.gather_node_by.get((int(session.region_id), session.job_id))
    if node is None:
        raise ValueError("采集点不存在")

    progress = (
        await db.execute(
            select(DohDolProgress).where(
                DohDolProgress.user_id == user.id, DohDolProgress.kind == "dol"
            )
        )
    ).scalar_one_or_none()
    if progress is None:
        progress = DohDolProgress(user_id=user.id, kind="dol", level=1, exp=0)
        db.add(progress)
        await db.flush()

    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    equip = dohdol_util.equipped_bonus(items)
    potion = await consumables.gather_bonus(db, user.id)
    yield_pct = equip.get("gatherYieldPct", 0.0) + potion.get("gatherYieldPct", 0.0)
    speed_pct = equip.get("gatherSpeedPct", 0.0)
    seconds_per = dohdol_util.gather_seconds_per_action(speed_pct)

    total = float(session.credit) + window
    actions = int(total // seconds_per)
    session.credit = total - actions * seconds_per
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + actions

    rng = random.Random()
    gained: dict[str, int] = {}
    for _ in range(actions):
        for material_id, count in dohdol_util.roll_gather_yield(node, int(progress.level), yield_pct, rng):
            gained[material_id] = gained.get(material_id, 0) + count
    for material_id, count in gained.items():
        await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_MATERIAL, material_id, count)

    xp = round(actions * int(CONFIG.dohdol_levels["actionXp"]["gather"]) * (1.0 + max(0.0, equip.get("gatherXpPct", 0.0)) / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    return {
        "gained": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(gained.items())
        ],
        "actions": actions,
        "xp": xp,
        "level": level_info,
        "cycle": dohdol_util.cycle_info(seconds_per, float(session.credit), now),
    }


async def stop_gather(db: AsyncSession, session: ActivitySession) -> None:
    session.active = False
    session.ended_at = datetime.now(timezone.utc)
