"""数据保留清理：只删「终态 + 超期」，绝不碰榜单真相与反多开依据。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import (
    ActivitySession,
    AuditLog,
    BattleSession,
    Hero,
    RaidSession,
    SecurityEvent,
    TreasureRun,
    User,
    UserDevice,
)
from app.models.multiplayer import PvpBattle
from app.models.world_boss import WorldBossContribution
from app.services.retention import purge_expired
from app.services.world_boss import BOSS_ID, ensure_world_boss

OLD = datetime.now(timezone.utc) - timedelta(days=30)
NOW = datetime.now(timezone.utc)
OLD_EPOCH = time.time() - 30 * 86400
NOW_EPOCH = time.time()


async def _seed(sessions) -> int:
    async with sessions() as db:
        user = User(username="retention", password_hash="x", nickname="保留", gold=0)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name="英雄", level=100, talent="common", attr_bias="balanced")
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        uid = int(user.id)

        db.add_all(
            [
                # 地区战斗：已结束 + 超期 → 应清；已结束 + 近期 → 留；进行中 + 超期 → 留
                BattleSession(user_id=uid, region_id=1, active=False, last_report_at=OLD),
                BattleSession(user_id=uid, region_id=1, active=False, last_report_at=NOW),
                BattleSession(user_id=uid, region_id=1, active=True, last_report_at=OLD),
                # 生活职业会话
                ActivitySession(user_id=uid, kind="gather", job_id="miner", active=False, last_report_at=OLD),
                ActivitySession(user_id=uid, kind="gather", job_id="miner", active=True, last_report_at=OLD),
                # 副本
                RaidSession(user_id=uid, raid_id="normal_1", active=False, started_at=OLD),
                RaidSession(user_id=uid, raid_id="normal_1", active=True, started_at=OLD),
                # 挖宝：已终止 + 超期 → 清；未终止 → 留
                TreasureRun(user_id=uid, status="ended", ended_reason="completed", created_at=OLD),
                TreasureRun(user_id=uid, status="fighting", ended_reason=None, created_at=OLD),
                # PvP 战报
                PvpBattle(attacker_id=uid, defender_id=uid, key="k1", report={}, created_at=OLD_EPOCH),
                PvpBattle(attacker_id=uid, defender_id=uid, key="k2", report={}, created_at=NOW_EPOCH),
                # 审计日志
                AuditLog(user_id=uid, reason="old", payload={}, rejected=True, created_at=OLD),
                AuditLog(user_id=uid, reason="new", payload={}, rejected=True, created_at=NOW),
                # 限流事件
                SecurityEvent(scope="login_ip", key="1.2.3.4", occurred_at=OLD_EPOCH),
                SecurityEvent(scope="login_ip", key="1.2.3.4", occurred_at=NOW_EPOCH),
                # 反多开依据：**永不清理**（即便很旧）
                UserDevice(user_id=uid, device_id="dev-old", last_seen_at=OLD),
            ]
        )
        await db.commit()
        return uid


async def test_purge_removes_only_terminal_and_expired(session_factory):
    uid = await _seed(session_factory)
    async with session_factory() as db:
        await ensure_world_boss(db)
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID, cycle=1, user_id=uid, damage=9_000_000, party=[], updated_at=0, created_at=0
            )
        )
        await db.commit()

    async with session_factory() as db:
        counts = await purge_expired(db)

    assert counts.get("battle_sessions") == 1
    assert counts.get("activity_sessions") == 1
    assert counts.get("raid_sessions") == 1
    assert counts.get("treasure_runs") == 1
    assert counts.get("pvp_battles") == 1
    assert counts.get("audit_logs") == 1
    assert counts.get("security_events") == 1

    async with session_factory() as db:
        battles = (await db.execute(select(BattleSession))).scalars().all()
        # 保留：近期已结束 + 进行中（即便超期）
        assert len(battles) == 2
        assert any(s.active for s in battles), "进行中的会话不得被清理"

        sessions = (await db.execute(select(ActivitySession))).scalars().all()
        assert len(sessions) == 1 and sessions[0].active

        raids = (await db.execute(select(RaidSession))).scalars().all()
        assert len(raids) == 1 and raids[0].active

        runs = (await db.execute(select(TreasureRun))).scalars().all()
        assert len(runs) == 1 and runs[0].ended_reason is None

        pvp = (await db.execute(select(PvpBattle))).scalars().all()
        assert len(pvp) == 1 and pvp[0].key == "k2"

        audits = (await db.execute(select(AuditLog))).scalars().all()
        assert len(audits) == 1 and audits[0].reason == "new"

        events = (await db.execute(select(SecurityEvent))).scalars().all()
        assert len(events) == 1


async def test_purge_never_touches_truth_and_anti_alt(session_factory):
    """榜单真相（世界BOSS 贡献）与反多开依据（user_devices）必须原样保留。"""
    uid = await _seed(session_factory)
    async with session_factory() as db:
        await ensure_world_boss(db)
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID, cycle=1, user_id=uid, damage=9_000_000, party=[], updated_at=0, created_at=0
            )
        )
        await db.commit()

    async with session_factory() as db:
        await purge_expired(db)

    async with session_factory() as db:
        contributions = (await db.execute(select(WorldBossContribution))).scalars().all()
        devices = (await db.execute(select(UserDevice))).scalars().all()
    assert len(contributions) == 1, "世界BOSS 贡献是榜单真相，不得清理"
    assert len(devices) == 1 and devices[0].device_id == "dev-old", "反多开设备依据不得清理"


async def test_retention_disabled_by_config(session_factory, monkeypatch):
    """`retention_enabled=false` 时整体关闭（不删除任何行）。"""
    from app.core.config import get_settings
    from app.services.retention import run_retention

    await _seed(session_factory)
    monkeypatch.setattr(get_settings(), "retention_enabled", False)

    async with session_factory() as db:
        counts = await run_retention(db)
        battles = (await db.execute(select(BattleSession))).scalars().all()
    assert counts == {}
    assert len(battles) == 3, "关闭后不应删除任何行"
