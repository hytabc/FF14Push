"""世界BOSS 推进进程：`python -m app.worldboss_worker`。

多个 worker 通过 PostgreSQL 行租约（FOR UPDATE SKIP LOCKED）安全共享推进。
每次 tick 在单个事务内：刷新到期 BOSS → 逐会话按服务端时钟推进 → 汇总伤害原子递减
全局血量 → 累加各账号贡献 → 血量归零则结算死亡并结束本周期会话。
"""

import asyncio
import logging
import time
import uuid
from copy import deepcopy

from sqlalchemy import case, or_, select, update

from app.core.database import SessionLocal
from app.models.world_boss import (
    SESSION_RUNNING,
    STATUS_ALIVE,
    WorldBoss,
    WorldBossSession,
)
from app.services.world_boss import (
    BOSS_ID,
    WORLD_BOSS,
    add_contribution,
    ensure_world_boss,
    kill_boss_if_depleted,
    respawn_due_bosses,
)
from app.services.worldboss_engine import advance

log = logging.getLogger("worldboss-worker")

MAX_SESSIONS_PER_TICK = 32
MAX_TICKS_PER_STEP = 10


def hero_deltas(state: dict) -> tuple[dict[str, int], dict[str, dict]]:
    """本 tick 各英雄的伤害增量与展示信息（用于把分英雄伤害累加进贡献榜）。

    英雄累计伤害按 heroId 记录在 `state['reportedHeroDamage']`，故增量 = 当前 − 上次上报；
    跨会话（离开后重进）也能正确累加，不会重复计入。
    """
    reported: dict[str, int] = state.setdefault("reportedHeroDamage", {})
    deltas: dict[str, int] = {}
    meta: dict[str, dict] = {}
    for hero in state.get("heroes", []):
        snap = hero.get("snapshot", {})
        hero_id = str(snap.get("heroId", hero.get("slot", 0)))
        current = int(hero.get("damage", 0.0))
        if current - int(reported.get(hero_id, 0)) > 0:
            deltas[hero_id] = current - int(reported.get(hero_id, 0))
        reported[hero_id] = current
        meta[hero_id] = {
            "slot": int(hero.get("slot", 0)),
            "heroId": int(snap.get("heroId", 0)),
            "name": snap.get("name", ""),
            "jobId": snap.get("jobId", ""),
            "level": int(snap.get("level", 1)),
        }
    return deltas, meta


async def tick_worldboss(session_factory=SessionLocal, worker_id: str = "worker", now: float | None = None) -> int:
    now = time.time() if now is None else now
    async with session_factory() as db:
        await respawn_due_bosses(db, now)
        boss = await db.get(WorldBoss, BOSS_ID)
        if boss is None:
            boss = await ensure_world_boss(db)

        advanced = 0
        if boss.status == STATUS_ALIVE:
            # 使用实时配置（而非 seed 时冻结的副本），方便调整技能/数值后无需重建行。
            config = WORLD_BOSS
            sessions = (
                await db.scalars(
                    select(WorldBossSession)
                    .where(
                        WorldBossSession.status == SESSION_RUNNING,
                        or_(WorldBossSession.lease_until < now, WorldBossSession.lease_owner == worker_id),
                    )
                    .order_by(WorldBossSession.updated_at, WorldBossSession.id)
                    .limit(MAX_SESSIONS_PER_TICK)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            total_damage = 0
            for session in sessions:
                if session.cycle != boss.cycle or now - session.heartbeat_at > int(config["disconnectSeconds"]):
                    session.status = "ended"
                    session.lease_until = 0
                    session.lease_owner = None
                    continue
                old_owner = session.lease_owner
                session.lease_owner = worker_id
                session.lease_until = now + int(config.get("leaseSeconds", 2))
                state = deepcopy(session.state)
                # 阶段由全服剩余血量决定：推进前写入当前占比（P2/P3 防御更厚、技能威力更高）。
                state["bossHpRatio"] = (int(boss.hp) / int(boss.max_hp)) if int(boss.max_hp) else 0.0
                # 无离线补算：换手或长间隔时只推进 0.1s，避免时间跳跃刷伤害。
                elapsed = max(0.0, now - session.updated_at)
                if old_owner not in (None, worker_id) or elapsed > 2:
                    elapsed = 0.1
                ticks = min(MAX_TICKS_PER_STEP, int((elapsed + 1e-7) * 10))
                if ticks:
                    advance(state, config, ticks * 100)
                deltas, meta = hero_deltas(state)
                session.state = state
                session.sequence += 1
                state_total = int(state.get("damageDealt", 0))
                delta = max(0, state_total - int(session.damage))
                session.damage = state_total
                session.updated_at = now if elapsed == 0.1 else session.updated_at + ticks * 0.1
                advanced += 1
                if delta > 0 or deltas:
                    total_damage += delta
                    await add_contribution(
                        db, boss.id, boss.cycle, session.user_id, delta, deltas, meta, now
                    )

            if total_damage > 0:
                await db.execute(
                    update(WorldBoss)
                    .where(WorldBoss.id == BOSS_ID, WorldBoss.hp > 0)
                    .values(
                        hp=case((WorldBoss.hp - total_damage < 0, 0), else_=WorldBoss.hp - total_damage),
                        updated_at=now,
                    )
                )
                await db.refresh(boss)

        await kill_boss_if_depleted(db, now)
        await db.commit()
    return advanced


async def main() -> None:
    worker_id = str(uuid.uuid4())
    while True:
        started = time.monotonic()
        try:
            await tick_worldboss(worker_id=worker_id)
        except Exception:  # noqa: BLE001
            log.exception("世界BOSS 推进失败，事务已回滚")
        await asyncio.sleep(max(0.01, 0.1 - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
