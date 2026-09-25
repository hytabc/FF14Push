"""世界BOSS WS 的共享生产者：每进程一次轮询 + 内存分发（不再每连接各查一次库）。"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.api.v1.worldboss import _worldboss_producer_factory
from app.models import User
from app.models.world_boss import WorldBoss, WorldBossContribution
from app.services.world_boss import BOSS_ID, ensure_world_boss


async def test_producer_snapshot_then_skips_unchanged(session_factory):
    """首次推送完整快照；状态未变且未到榜单周期时不推送（返回 None）。"""
    async with session_factory() as db:
        await ensure_world_boss(db)
        await db.commit()

    produce = _worldboss_producer_factory(session_factory)

    first = await produce()
    assert first is not None
    assert first["type"] == "snapshot"
    assert first["sequence"] == 1
    assert first["boss"]["maxHp"] == 2_000_000_000
    assert "leaderboardRows" in first

    # 血量未变、且距上次榜单不足 5 秒 → 不推送。
    assert await produce() is None


async def test_producer_pushes_on_hp_change(session_factory):
    async with session_factory() as db:
        await ensure_world_boss(db)
        await db.commit()

    produce = _worldboss_producer_factory(session_factory)
    await produce()

    async with session_factory() as db:
        boss = await db.get(WorldBoss, BOSS_ID)
        max_hp = int(boss.max_hp)
        boss.hp = max_hp - 12345
        await db.commit()

    payload = await produce()
    assert payload is not None
    assert payload["type"] == "update"
    assert payload["boss"]["hp"] == max_hp - 12345
    # 距上次榜单不足 5s：只推 BOSS 状态，不重复带榜单行（省带宽）。
    assert "leaderboardRows" not in payload


async def test_producer_sends_leaderboard_on_cadence(session_factory, monkeypatch):
    """到达榜单刷新周期时必须带上榜单行（否则客户端榜单不再更新）。"""
    from app.api.v1 import worldboss as wb_module

    monkeypatch.setattr(wb_module, "WORLDBOSS_LEADERBOARD_SECONDS", 0.0)

    async with session_factory() as db:
        await ensure_world_boss(db)
        await db.commit()

    produce = _worldboss_producer_factory(session_factory)
    first = await produce()
    second = await produce()
    assert first is not None and "leaderboardRows" in first
    assert second is not None and "leaderboardRows" in second
    assert second["cycle"] == first["cycle"]


async def test_producer_rows_feed_build_leaderboard(session_factory):
    """共享的榜单行 + 各连接就地拼装 me，结果与直接 leaderboard_view 一致。"""
    from app.services.world_boss import build_leaderboard, leaderboard_view

    async with session_factory() as db:
        await ensure_world_boss(db)
        user = User(username="wb_ws", password_hash="x", nickname="广播", gold=0)
        db.add(user)
        await db.flush()
        boss = await db.get(WorldBoss, BOSS_ID)
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID,
                cycle=boss.cycle,
                user_id=user.id,
                damage=12_000_000,
                party=[],
                updated_at=time.time(),
                created_at=time.time(),
            )
        )
        await db.commit()
        uid = int(user.id)
        cycle = int(boss.cycle)

    produce = _worldboss_producer_factory(session_factory)
    payload = await produce()
    assert payload is not None and "leaderboardRows" in payload

    shared = build_leaderboard(payload["leaderboardRows"], payload["cycle"], uid, 1, 50)
    async with session_factory() as db:
        direct = await leaderboard_view(db, cycle, 0, 1, 50)
    assert shared["me"] is not None and shared["me"]["userId"] == uid
    assert shared["entries"] == direct["entries"]

    # 未登录（user_id=None）时 me 为空，entries 不变。
    anon = build_leaderboard(payload["leaderboardRows"], payload["cycle"], None, 1, 50)
    assert anon["me"] is None
    assert anon["entries"] == shared["entries"]


async def test_producer_returns_none_without_boss(session_factory):
    """BOSS 单行不存在时不推送（避免广播错误 payload）。"""
    produce = _worldboss_producer_factory(session_factory)
    assert await produce() is None
    async with session_factory() as db:
        rows = (await db.execute(select(WorldBoss))).scalars().all()
    assert rows == []
