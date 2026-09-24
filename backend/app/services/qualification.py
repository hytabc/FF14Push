"""Recompute access without modifying historical rewards or clears."""
from sqlalchemy import select
from fastapi import HTTPException
from app.models import RegionProgress
from app.services.balance import BALANCE, region_gate
from app.services.stats import compute_stats


async def region_access(db, user_id, hero, items, difficulty: int | None = None):
    """返回 {region_id: 缺失条件列表}（空列表 = 可进入）。

    传 difficulty 时只统计该难度的解锁/通关（战斗按难度隔离）；
    传 None 时跨全部难度统计（生活职业 / 采集钓鱼按历史最高进度解锁）。
    """
    query = select(RegionProgress).where(RegionProgress.user_id == user_id)
    if difficulty is not None:
        query = query.where(RegionProgress.difficulty == difficulty)
    rows = (await db.execute(query)).scalars().all()
    cleared = {r.region_id for r in rows if r.cleared}
    old = {r.region_id for r in rows if r.unlocked}
    from app.services.stats import hero_items
    from app.services.materia import socket_mods as materia_socket_mods
    items = hero_items(items, hero.id)
    stats = compute_stats(hero, items, await materia_socket_mods(db, user_id))
    return {int(r): region_gate(int(r), stats, items, cleared, int(r) in old) for r in BALANCE['regions']}


async def require_region(db, user_id, hero, items, region_id, difficulty: int = 0):
    missing = (await region_access(db, user_id, hero, items, difficulty))[region_id]
    if missing:
        raise HTTPException(403, detail='；'.join(missing))


async def ensure_region_progress(db, user_id, difficulty: int, region_id: int) -> RegionProgress:
    """取该难度下某地区的进度行；不存在则创建（unlocked=True）。

    新难度首次进入地区时按需补行，否则 BOSS 结算会因为拿不到进度行而跳过。
    """
    row = (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user_id,
                RegionProgress.difficulty == difficulty,
                RegionProgress.region_id == region_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = RegionProgress(
            user_id=user_id, difficulty=difficulty, region_id=region_id, unlocked=True, cleared=False
        )
        db.add(row)
        await db.flush()
    return row
