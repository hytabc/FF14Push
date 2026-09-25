"""实时榜（钓鱼 / 生活 / 远征）：短 TTL 缓存必须合并同一请求内的两次聚合，且写入可失效。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import FishRecord, Hero, User
from app.services import ranking as ranking_module
from app.services.ranking import (
    fetch_fish_board,
    fetch_fish_user_rank,
    invalidate_live_rankings,
)


async def _seed_fisher(sessions, username: str) -> int:
    async with sessions() as db:
        user = User(username=username, password_hash="x", nickname=username, gold=0)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name=username, level=100, talent="common", attr_bias="balanced")
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        db.add_all(
            [
                FishRecord(
                    user_id=user.id,
                    fish_id="f_test_1",
                    region_id=1,
                    kind="normal",
                    count=12,
                    max_size=30,
                    first_caught_at=datetime.now(timezone.utc),
                ),
                FishRecord(
                    user_id=user.id,
                    fish_id="f_test_king_1",
                    region_id=1,
                    kind="king",
                    count=1,
                    max_size=99,
                    first_caught_at=datetime.now(timezone.utc),
                ),
            ]
        )
        await db.commit()
        return int(user.id)


async def test_live_board_shares_one_aggregation_per_request(session_factory, monkeypatch):
    """榜单页 + 我的排名 原先是两遍全表聚合，现在应共用一次。"""
    uid = await _seed_fisher(session_factory, "live_cache")

    calls = {"n": 0}
    original = ranking_module._fish_rows_uncached

    async def counting(db):
        calls["n"] += 1
        return await original(db)

    monkeypatch.setattr(ranking_module, "_fish_rows_uncached", counting)
    invalidate_live_rankings()

    async with session_factory() as db:
        entries = await fetch_fish_board(db, "fish_species", 1, 50)
        mine = await fetch_fish_user_rank(db, "fish_species", uid)

    assert calls["n"] == 1, "同一请求内的两次调用应只做一次聚合"
    assert entries and entries[0]["userId"] == uid
    assert mine is not None and mine["userId"] == uid


async def test_live_board_reuses_cache_until_invalidated(session_factory, monkeypatch):
    uid = await _seed_fisher(session_factory, "live_ttl")

    calls = {"n": 0}
    original = ranking_module._fish_rows_uncached

    async def counting(db):
        calls["n"] += 1
        return await original(db)

    monkeypatch.setattr(ranking_module, "_fish_rows_uncached", counting)
    invalidate_live_rankings()

    async with session_factory() as db:
        first = await fetch_fish_board(db, "fish_count", 1, 50)
    async with session_factory() as db:
        second = await fetch_fish_board(db, "fish_count", 1, 50)
    assert calls["n"] == 1, "TTL 内应复用缓存"
    assert first == second

    # 写入侧调用失效后必须重新聚合（保证「刚钓完就能看到自己」）。
    invalidate_live_rankings()
    async with session_factory() as db:
        third = await fetch_fish_board(db, "fish_count", 1, 50)
    assert calls["n"] == 2, "失效后应重新聚合"
    assert third == first
    assert uid in {row["userId"] for row in third}


async def test_live_cache_disabled_when_ttl_zero(session_factory, monkeypatch):
    """TTL <= 0 时应完全绕过缓存（退化为改造前的行为）。"""
    await _seed_fisher(session_factory, "live_nocache")
    monkeypatch.setattr(ranking_module.get_settings(), "ranking_live_cache_seconds", 0.0)

    calls = {"n": 0}
    original = ranking_module._fish_rows_uncached

    async def counting(db):
        calls["n"] += 1
        return await original(db)

    monkeypatch.setattr(ranking_module, "_fish_rows_uncached", counting)
    invalidate_live_rankings()

    async with session_factory() as db:
        await fetch_fish_board(db, "fish_species", 1, 50)
        await fetch_fish_user_rank(db, "fish_species", 1)
    assert calls["n"] == 2, "关闭缓存后两次调用各自聚合"
