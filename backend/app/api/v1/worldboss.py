"""世界BOSS：全服共享血量的 BOSS、8 英雄上阵、实时总伤害榜与周期奖励。

服务端权威：客户端只提交「上阵英雄」，伤害与英雄存亡由 `worldboss_worker` 推进。
实时同步沿用远征的「一次性 ticket + 各连接按游标轮询 DB」模式。
"""

from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.core.deps import CurrentUser, DbSession
from app.models import Hero, User
from app.models.world_boss import (
    SESSION_RUNNING,
    STATUS_ALIVE,
    WorldBoss,
    WorldBossContribution,
    WorldBossSession,
    WorldBossTicket,
)
from app.services.coop_snapshot import snapshot_hero
from app.services.roster import lock_user, require_idle_team, stop_activities
from app.services.world_boss import (
    BOSS_ID,
    WORLD_BOSS,
    boss_config,
    claim_reward,
    ensure_world_boss,
    hero_slots,
    leaderboard_view,
    level_multiplier,
    phase_for_ratio,
    phases,
    reward_config,
    rules,
    session_public,
    unclaimed_cycle,
)
from app.services.worldboss_engine import new_state

router = APIRouter(prefix="/worldboss", tags=["worldboss"])


class EnterRequest(BaseModel):
    heroIds: list[int] = Field(min_length=1, max_length=8)


def boss_public(boss: WorldBoss | None) -> dict | None:
    if boss is None:
        return None
    cfg = boss_config()
    ratio = (int(boss.hp) / int(boss.max_hp)) if int(boss.max_hp) else 0.0
    phase = phase_for_ratio(ratio)
    return {
        "key": boss.boss_key,
        "name": boss.name,
        "cycle": int(boss.cycle),
        "hp": int(boss.hp),
        "maxHp": int(boss.max_hp),
        "attack": int(boss.attack),
        "status": boss.status,
        "killedAt": boss.killed_at,
        "respawnAt": boss.respawn_at,
        "reviveSeconds": int(cfg["reviveSeconds"]),
        "skillIntervalSeconds": int(cfg["skillIntervalSeconds"]),
        # 阶段由全服剩余血量占比决定（P2/P3 防御更厚、技能威力更高）。
        "phase": int(phase["id"]),
        "phaseName": str(phase["name"]),
        "defenseMultiplier": float(phase["defenseMultiplier"]),
        "skillPotencyMultiplier": float(phase["skillPotencyMultiplier"]),
    }


async def _my_session(db, user_id: int) -> WorldBossSession | None:
    return await db.scalar(
        select(WorldBossSession)
        .where(WorldBossSession.user_id == user_id, WorldBossSession.status == SESSION_RUNNING)
        .order_by(WorldBossSession.id.desc())
    )


async def _state_view(db, user: User, boss: WorldBoss) -> dict:
    session = await _my_session(db, user.id)
    contribution = await db.scalar(
        select(WorldBossContribution).where(
            WorldBossContribution.cycle == boss.cycle, WorldBossContribution.user_id == user.id
        )
    )
    return {
        "boss": boss_public(boss),
        "rules": {
            "heroSlots": hero_slots(),
            "levelRequirement": int(rules()["levelRequirement"]),
            "fullPowerLevel": int(rules()["fullPowerLevel"]),
            "weaknessFloor": float(rules()["weaknessFloor"]),
        },
        "phases": phases(),
        "reward": reward_config(),
        "session": session_public(session.state) if session is not None else None,
        "sequence": int(session.sequence) if session is not None else 0,
        "myDamage": int(contribution.damage) if contribution is not None else 0,
        "unclaimedCycle": await unclaimed_cycle(db, user.id, boss),
        "leaderboard": await leaderboard_view(db, boss.cycle, user.id, 1, 50),
    }


@router.get("/state")
async def state(db: DbSession, user: CurrentUser) -> dict:
    boss = await db.get(WorldBoss, BOSS_ID) or await ensure_world_boss(db)
    return await _state_view(db, user, boss)


@router.get("/leaderboard")
async def leaderboard(db: DbSession, user: CurrentUser, page: int = 1) -> dict:
    boss = await db.get(WorldBoss, BOSS_ID) or await ensure_world_boss(db)
    return await leaderboard_view(db, boss.cycle, user.id, max(1, page), 50)


@router.post("/enter")
async def enter(payload: EnterRequest, db: DbSession, user: CurrentUser) -> dict:
    boss = await db.get(WorldBoss, BOSS_ID) or await ensure_world_boss(db)
    if boss.status != STATUS_ALIVE:
        raise HTTPException(409, "世界BOSS 已被击杀，等待刷新")

    await lock_user(db, user.id)
    # 世界BOSS 与远征 / 其他活跃互斥：先清掉自己旧的会话，再检查是否处于团队战斗。
    await db.execute(delete(WorldBossSession).where(WorldBossSession.user_id == user.id))
    await db.flush()
    await require_idle_team(db, user.id)

    hero_ids = list(dict.fromkeys(int(h) for h in payload.heroIds))
    if len(hero_ids) > hero_slots():
        raise HTTPException(400, f"最多上阵 {hero_slots()} 名英雄")
    heroes = (await db.scalars(select(Hero).where(Hero.user_id == user.id, Hero.id.in_(hero_ids)))).all()
    if len(heroes) != len(hero_ids):
        raise HTTPException(404, "存在不属于你的英雄")
    order = {hid: index for index, hid in enumerate(hero_ids)}
    heroes.sort(key=lambda hero: order[hero.id])

    min_level = int(rules()["levelRequirement"])
    for hero in heroes:
        if int(hero.level) < min_level:
            raise HTTPException(400, f"英雄需达到 {min_level} 级才能参战")

    snapshots = []
    for hero in heroes:
        snapshot = await snapshot_hero(db, hero)
        snapshot["levelMultiplier"] = level_multiplier(hero.level)
        snapshots.append(snapshot)

    state = new_state(WORLD_BOSS, snapshots, seed=secrets.randbits(32))
    state["bossHpRatio"] = (int(boss.hp) / int(boss.max_hp)) if int(boss.max_hp) else 0.0
    now = time.time()
    db.add(
        WorldBossSession(
            boss_id=BOSS_ID,
            cycle=boss.cycle,
            user_id=user.id,
            status=SESSION_RUNNING,
            state=state,
            sequence=1,
            damage=0,
            heartbeat_at=now,
            lease_until=0,
            updated_at=now,
            created_at=now,
        )
    )
    await stop_activities(db, user.id)
    await db.commit()
    return await _state_view(db, user, boss)


@router.post("/leave")
async def leave(db: DbSession, user: CurrentUser) -> dict:
    await db.execute(delete(WorldBossSession).where(WorldBossSession.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.post("/heartbeat")
async def heartbeat(db: DbSession, user: CurrentUser) -> dict:
    session = await _my_session(db, user.id)
    if session is not None:
        session.heartbeat_at = time.time()
        await db.commit()
    return {"ok": True}


@router.post("/claim")
async def claim(db: DbSession, user: CurrentUser, cycle: int | None = None) -> dict:
    receipt = await claim_reward(db, user.id, cycle)
    await db.commit()
    return receipt


@router.post("/ticket")
async def ticket(db: DbSession, user: CurrentUser) -> dict:
    await db.execute(delete(WorldBossTicket).where(WorldBossTicket.expires_at < time.time()))
    token = secrets.token_urlsafe(32)
    db.add(WorldBossTicket(token=token, user_id=user.id, boss_id=BOSS_ID, expires_at=time.time() + 30))
    await db.commit()
    return {"ticket": token}


def _ws_session(state: dict, since: int) -> dict:
    view = session_public(state)
    view["events"] = [e for e in state.get("events", []) if e.get("seq", 0) > since]
    return view


@router.websocket("/ws")
async def stream(ws: WebSocket) -> None:
    token = ws.query_params.get("ticket", "")
    async with SessionLocal() as db:
        row = await db.scalar(select(WorldBossTicket).where(WorldBossTicket.token == token).with_for_update())
        if not row or row.expires_at < time.time():
            await ws.close(code=4401)
            return
        uid = row.user_id
        user = await db.get(User, uid)
        if not user or user.banned:
            await ws.close(code=4403)
            return
        await db.delete(row)
        await db.commit()

    await ws.accept()
    sent = False
    last_seq = -1
    last_event = 0
    last_boss: tuple | None = None
    last_lb = 0.0
    try:
        while True:
            async with SessionLocal() as db:
                user = await db.get(User, uid)
                if not user or user.banned:
                    await ws.close(code=4403)
                    return
                boss = await db.get(WorldBoss, BOSS_ID)
                session = await _my_session(db, uid)
                boss_sig = (int(boss.hp), boss.status, int(boss.cycle)) if boss is not None else None
                now = time.time()
                changed = boss_sig != last_boss or (session is not None and int(session.sequence) != last_seq)
                due = boss is not None and now - last_lb >= 5
                if changed or due or not sent:
                    payload: dict = {
                        "type": "snapshot" if not sent else "update",
                        "sequence": int(session.sequence) if session is not None else 0,
                        "boss": boss_public(boss),
                        "session": _ws_session(session.state, last_event) if session is not None else None,
                    }
                    if session is not None:
                        last_seq = int(session.sequence)
                        last_event = int(session.state.get("eventSequence", 0))
                    last_boss = boss_sig
                    sent = True
                    if due:
                        payload["leaderboard"] = await leaderboard_view(db, boss.cycle, uid, 1, 50)
                        last_lb = now
                    await ws.send_json(payload)
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        return
