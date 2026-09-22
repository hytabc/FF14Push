"""钓鱼（捕鱼人）：后台自动抛竿，服务端权威结算。

机制：普通鱼按权重随机、尺寸随机；钓起指定普通鱼后开启「捕鱼人之识」（30-60s，随鱼种），
期间才有小概率出现鱼王/鱼皇（鱼皇概率低于鱼王）。每个钓场各 1 条鱼王 + 1 条鱼皇。
钓全所有地区的鱼王 / 鱼皇各解锁一个称号。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivitySession, DohDolProgress, FishRecord, Item, User, UserTitle
from app.services import consumables, dohdol_util
from app.services.game_config import CONFIG
from app.services.gathering import cleared_max_region
from app.services.playtime import add_play_ms

MAX_CASTS_PER_REPORT = 200


async def _progress(db: AsyncSession, user_id: int) -> DohDolProgress:
    row = (
        await db.execute(
            select(DohDolProgress).where(
                DohDolProgress.user_id == user_id, DohDolProgress.kind == "dol"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DohDolProgress(user_id=user_id, kind="dol", level=1, exp=0)
        db.add(row)
        await db.flush()
    return row


async def start_fish(db: AsyncSession, user: User, items: Sequence[Item], region_id: int) -> dict[str, Any]:
    if region_id not in CONFIG.fish_region_by_id:
        raise ValueError("该地区没有钓场")
    if region_id > await cleared_max_region(db, user.id) + 1:
        raise ValueError("该地区尚未解锁")

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now,
        user_id=user.id, kind="fish", job_id="FSH", region_id=region_id, active=True,
        credit=0.0, session_fish=[],
    )
    db.add(session)
    await db.flush()
    speed = dohdol_util.equipped_bonus(items).get("gatherSpeedPct", 0.0)
    return {
        "sessionId": session.id,
        "regionId": region_id,
        "cycle": dohdol_util.cycle_info(dohdol_util.fish_seconds_per_cast(speed), 0.0, now),
    }


def _pick_normal(region: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    normal = region["normal"]
    total = sum(float(f["weight"]) for f in normal)
    roll = rng.random() * total
    cumulative = 0.0
    for fish in normal:
        cumulative += float(fish["weight"])
        if roll < cumulative:
            return fish
    return normal[-1]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _record_fish(
    db: AsyncSession, user_id: int, fish_id: str, region_id: int, kind: str, size: int
) -> None:
    row = (
        await db.execute(
            select(FishRecord).where(FishRecord.user_id == user_id, FishRecord.fish_id == fish_id)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            FishRecord(
                user_id=user_id, fish_id=fish_id, region_id=region_id, kind=kind,
                count=1, max_size=size,
            )
        )
    else:
        row.count = int(row.count) + 1
        row.max_size = max(int(row.max_size), size)


async def _unlock_titles(db: AsyncSession, user_id: int, kind: str, title_id: str) -> bool:
    target = {f["id"] for f in _all_fish_of_kind(kind)}
    caught = (
        await db.execute(
            select(FishRecord.fish_id).where(
                FishRecord.user_id == user_id, FishRecord.kind == kind
            )
        )
    ).scalars().all()
    if target and target.issubset(set(caught)):
        existing = (
            await db.execute(
                select(UserTitle).where(UserTitle.user_id == user_id, UserTitle.title_id == title_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(UserTitle(user_id=user_id, title_id=title_id))
            return True
    return False


def _all_fish_of_kind(kind: str) -> list[dict[str, Any]]:
    out = []
    for region in CONFIG.fish["regions"]:
        out.append(region["king" if kind == "king" else "emperor"])
    return out


async def report_fish(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    region = CONFIG.fish_region_by_id.get(int(session.region_id or 0))
    if region is None:
        raise ValueError("钓场不存在")

    progress = await _progress(db, user.id)
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    equip = dohdol_util.equipped_bonus(items)
    potion = await consumables.fish_bonus(db, user.id)
    insight_pct = equip.get("fishInsightPct", 0.0) + potion.get("fishInsightPct", 0.0)
    chance_pct = equip.get("fishChancePct", 0.0) + potion.get("fishChancePct", 0.0)

    cast_seconds = dohdol_util.fish_seconds_per_cast(equip.get("gatherSpeedPct", 0.0))
    total = float(session.credit) + window
    casts = min(int(total // cast_seconds), MAX_CASTS_PER_REPORT)
    session.credit = total - int(total // cast_seconds) * cast_seconds
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + casts

    rng = random.Random()
    session_fish = set(session.session_fish or [])
    caught: list[dict[str, Any]] = []
    gained: dict[str, int] = {}
    new_titles: list[str] = []

    for _ in range(casts):
        insight_active = (_aware(session.insight_expires_at) or now) > now
        pick: dict[str, Any]
        kind = "normal"
        if insight_active and rng.random() < float(region["king"]["chance"]) * (1.0 + chance_pct / 100.0):
            pick, kind = region["king"], "king"
        elif insight_active and rng.random() < float(region["emperor"]["chance"]) * (1.0 + chance_pct / 100.0):
            pick, kind = region["emperor"], "emperor"
        else:
            pick = _pick_normal(region, rng)

        size = rng.randint(int(pick["sizeMin"]), int(pick["sizeMax"]))
        await _record_fish(db, user.id, pick["id"], int(session.region_id), kind, size)
        await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_MATERIAL, pick["id"], 1)
        gained[pick["id"]] = gained.get(pick["id"], 0) + 1
        caught.append({"id": pick["id"], "name": pick["name"], "kind": kind, "size": size, "exp": pick["exp"]})

        if kind == "normal":
            session_fish.add(pick["id"])
            # 满足前置 → 开启/延长「捕鱼人之识」
            duration = 0.0
            if set(region["king"]["prereqFishIds"]).issubset(session_fish):
                lo, hi = region["king"]["insightSeconds"]
                duration = max(duration, rng.uniform(float(lo), float(hi)))
            if set(region["emperor"]["prereqFishIds"]).issubset(session_fish):
                lo, hi = region["emperor"]["insightSeconds"]
                duration = max(duration, rng.uniform(float(lo), float(hi)))
            if duration > 0:
                duration *= 1.0 + insight_pct / 100.0
                current = _aware(session.insight_expires_at)
                new_expiry = now + timedelta(seconds=duration)
                session.insight_expires_at = new_expiry if current is None or current < new_expiry else current

    session.session_fish = sorted(session_fish)

    xp = round(sum(int(c["exp"]) for c in caught) * (1.0 + max(0.0, equip.get("gatherXpPct", 0.0)) / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    for kind, title_id in (("king", "fish_king_all"), ("emperor", "fish_emperor_all")):
        if any(c["kind"] == kind for c in caught) and await _unlock_titles(db, user.id, kind, title_id):
            new_titles.append(title_id)

    insight_remaining = 0
    expiry = _aware(session.insight_expires_at)
    if expiry and expiry > now:
        insight_remaining = int((expiry - now).total_seconds())

    return {
        "caught": caught,
        "gained": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(gained.items())
        ],
        "casts": casts,
        "xp": xp,
        "level": level_info,
        "insightRemainingSec": insight_remaining,
        "newTitles": new_titles,
        "cycle": dohdol_util.cycle_info(cast_seconds, float(session.credit), now),
    }


async def stop_fish(db: AsyncSession, session: ActivitySession) -> None:
    session.active = False
    session.ended_at = datetime.now(timezone.utc)
