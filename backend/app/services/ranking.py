"""排行榜：等级榜 / 关卡榜 / 战力榜 / 金币榜。来源：PRD 排行榜 2.2 / 2.3 / 2.4

每 5 分钟由后台任务刷新一次到 `rankings` 缓存表，查询时直接读缓存。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Hero, RankingEntry, RegionProgress, User
from app.services.stats import compute_stats
from app.services.valuation import hero_power

BOARDS = ("level", "stage", "power", "gold")


async def refresh_all_rankings(db: AsyncSession) -> dict[str, int]:
    users = (
        await db.execute(select(User).options(selectinload(User.hero), selectinload(User.items)))
    ).scalars().all()

    progress_rows = (await db.execute(select(RegionProgress))).scalars().all()
    cleared: dict[int, list[RegionProgress]] = {}
    for row in progress_rows:
        if row.cleared:
            cleared.setdefault(row.user_id, []).append(row)

    await db.execute(delete(RankingEntry))

    counts = {board: 0 for board in BOARDS}
    for user in users:
        hero = user.hero
        if hero is None:
            continue

        stats = compute_stats(hero, user.items)
        cleared_list = cleared.get(user.id, [])
        max_region = max((r.region_id for r in cleared_list), default=0)
        cleared_at = max((r.cleared_at for r in cleared_list if r.cleared_at), default=None)

        entries = [
            _entry(user, hero, "level", hero.level, hero.exp),
            _entry(user, hero, "stage", max_region, -int((cleared_at or datetime.now(timezone.utc)).timestamp())),
            _entry(user, hero, "power", hero_power(stats), 0, stats.to_dict()),
            _entry(user, hero, "gold", int(user.gold), 0),
        ]
        for entry in entries:
            db.add(entry)
            counts[entry.board] += 1

    await db.flush()
    return counts


def _entry(
    user: User,
    hero: Hero,
    board: str,
    value: int,
    secondary: int,
    extra: dict[str, Any] | None = None,
) -> RankingEntry:
    payload = {
        "nickname": user.nickname,
        "level": hero.level,
        "maxRegion": None,
        "jobId": None,
    }
    if extra:
        payload.update({"jobId": extra.get("jobId")})
    return RankingEntry(
        user_id=user.id,
        board=board,
        value=int(value),
        secondary=int(secondary),
        nickname=user.nickname,
        payload=payload,
    )


async def fetch_board(db: AsyncSession, board: str, page: int = 1, page_size: int = 100) -> list[dict[str, Any]]:
    offset = max(0, (page - 1) * page_size)
    rows = (
        await db.execute(
            select(RankingEntry)
            .where(RankingEntry.board == board)
            .order_by(RankingEntry.value.desc(), RankingEntry.secondary.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()
    return [
        {
            "rank": offset + index + 1,
            "userId": row.user_id,
            "nickname": row.nickname,
            "value": row.value,
            "payload": row.payload,
        }
        for index, row in enumerate(rows)
    ]


async def fetch_user_rank(db: AsyncSession, board: str, user_id: int) -> dict[str, Any] | None:
    rows = (
        await db.execute(
            select(RankingEntry)
            .where(RankingEntry.board == board)
            .order_by(RankingEntry.value.desc(), RankingEntry.secondary.desc())
        )
    ).scalars().all()
    for index, row in enumerate(rows):
        if row.user_id == user_id:
            return {"rank": index + 1, "value": row.value, "nickname": row.nickname, "userId": user_id}
    return None
