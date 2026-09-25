"""世界BOSS：全服共享血量的 BOSS、8 英雄上阵、实时总伤害榜与周期奖励。

**运算下放客户端**：客户端本地跑 `worldboss_engine` 的同一套 100ms 模拟（`/worldboss/enter`
返回英雄快照，前端 `game/core/worldboss.ts` 复刻引擎），按窗口上报伤害增量；
服务端只做**上限夹取 + 共享部分结算**——全局血量原子递减、贡献累计、周期换轮与奖励全部服务端权威。

防作弊边界（详见 `services/worldboss_model.py`）：
- 窗口只认服务端时钟（`last_report_at`），客户端 `elapsedMs` 仅供参考；
- 伤害上限 = 理论上界 × 窗口 × 容差，超标整单拒绝并写审计；
- `reportSeq` 单调递增，重放幂等（不重复扣血 / 加贡献）。

实时同步沿用远征的「一次性 ticket + 连接按游标轮询 DB」模式；榜单读取走进程内短 TTL 缓存
（`world_boss.cached_contribution_rows`）。
"""

from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.deps import CurrentUser, DbSession, guard_rate
from app.models import AuditLog, Hero, User
from app.models.world_boss import (
    SESSION_RUNNING,
    STATUS_ALIVE,
    WorldBoss,
    WorldBossContribution,
    WorldBossSession,
    WorldBossTicket,
)
from app.services.broadcast import MEMBER_CHECK_SECONDS, hub
from app.services.coop_snapshot import snapshot_hero
from app.services.roster import lock_user, require_idle_team, stop_activities
from app.services.world_boss import (
    BOSS_ID,
    WORLD_BOSS,
    add_contribution,
    boss_config,
    build_leaderboard,
    claim_reward,
    ensure_world_boss,
    hero_slots,
    kill_boss_if_depleted,
    leaderboard_view,
    level_multiplier,
    period_seconds,
    phase_for_ratio,
    phases,
    qualified_rows,
    reward_config,
    roll_world_boss,
    rules,
    session_public,
    unclaimed_cycle,
)
from app.services.worldboss_engine import new_state
from app.services.worldboss_model import max_damage_in_seconds

router = APIRouter(prefix="/worldboss", tags=["worldboss"])


class EnterRequest(BaseModel):
    heroIds: list[int] = Field(min_length=1, max_length=8)


class HeroDamageReport(BaseModel):
    heroId: int
    damage: int = Field(ge=0)


class ReportRequest(BaseModel):
    """客户端本地模拟的伤害增量上报。`elapsedMs` 仅供参考，服务端不采信。"""

    reportSeq: int = Field(ge=1)
    damage: int = Field(ge=0)
    perHero: list[HeroDamageReport] = Field(default_factory=list)
    elapsedMs: int | None = None


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
        # 讨伐周期：结算单位是周期而非单次击杀；周期内击杀只进入短暂休整。
        "periodSeconds": period_seconds(),
        "periodEndsAt": boss.period_ends_at,
        "kills": int(boss.kills or 0),
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


def _party(session: WorldBossSession) -> list[dict]:
    """上阵英雄快照：客户端本地模拟的输入（与后端引擎 `new_state` 的 snapshots 同构）."""
    return [hero.get("snapshot") or {} for hero in (session.state.get("heroes") or [])]


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
        # 下放客户端模拟：上阵英雄的完整快照（前端据此本地构造引擎 state）。
        "party": _party(session) if session is not None else None,
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
            last_report_at=now,
            last_report_seq=0,
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


@router.post("/report")
async def report(payload: ReportRequest, db: DbSession, user: CurrentUser) -> dict:
    """客户端本地模拟的伤害增量上报。

    服务端只做上限夹取与共享部分结算：窗口取服务端时钟、上限取理论模型、
    全局血量原子递减、贡献累加；`reportSeq` 保证重放幂等。
    """
    settings = get_settings()
    await guard_rate(db, "worldboss_report", str(user.id), settings.worldboss_report_per_minute, 60)

    boss = await db.get(WorldBoss, BOSS_ID)
    if boss is None:
        raise HTTPException(409, "世界BOSS 尚未初始化")
    now = time.time()
    await roll_world_boss(db, now)  # 顺手推进周期换轮 / 短休整复活
    await db.refresh(boss)

    session = await _my_session(db, user.id)
    if session is None or session.cycle != boss.cycle:
        raise HTTPException(404, "没有进行中的世界BOSS 会话")

    # 幂等：重复上报同一序号直接返回当前状态，不重复扣血 / 加贡献。
    if int(payload.reportSeq) <= int(session.last_report_seq or 0):
        return _report_view(boss, session, accepted=0, duplicate=True)

    # BOSS 休整中：不接受伤害（推进游标，客户端据此停止本窗口的累计）。
    if boss.status != STATUS_ALIVE:
        session.last_report_at = now
        session.last_report_seq = int(payload.reportSeq)
        session.heartbeat_at = now
        await db.commit()
        return _report_view(boss, session, accepted=0, paused=True)

    # 窗口只认服务端时钟：客户端 elapsedMs 仅供参考（防加速 / 改系统时间）。
    window_ms = (now - float(session.last_report_at or session.created_at or now)) * 1000.0
    window_ms = max(
        float(settings.worldboss_report_min_ms),
        min(float(settings.worldboss_report_max_ms), window_ms),
    )
    snapshots = _party(session)
    cap = max_damage_in_seconds(snapshots, window_ms / 1000.0, settings.worldboss_report_tolerance)

    requested = int(payload.damage)
    # 超出上限 2 倍以上：整单拒绝并写审计（与地区战斗 validator 同口径）。
    if requested > cap * 2 + 1:
        db.add(
            AuditLog(
                user_id=user.id,
                reason="worldboss_damage_exceeded",
                payload={"damage": requested, "cap": round(cap), "windowMs": round(window_ms)},
                rejected=True,
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail={"rejected": [f"伤害 {requested} 远超上限 {cap:.0f}"]},
        )

    accepted = int(min(float(requested), cap))
    # 分英雄增量按同一比例缩放，保证 ΣperHero == accepted。
    scale = (accepted / requested) if requested > 0 else 0.0
    hero_meta: dict[str, dict] = {}
    for hero in session.state.get("heroes") or []:
        snap = hero.get("snapshot") or {}
        hero_id = str(snap.get("heroId", hero.get("slot", 0)))
        hero_meta[hero_id] = {
            "slot": int(hero.get("slot", 0)),
            "heroId": int(snap.get("heroId", 0)),
            "name": snap.get("name", ""),
            "jobId": snap.get("jobId", ""),
            "level": int(snap.get("level", 1)),
        }
    hero_deltas: dict[str, int] = {}
    for entry in payload.perHero:
        amount = int(entry.damage * scale)
        if amount > 0:
            key = str(entry.heroId)
            hero_deltas[key] = hero_deltas.get(key, 0) + amount

    if accepted > 0:
        # 原子递减全局血量（并发下同一行只会被正确扣减一次）。
        await db.execute(
            update(WorldBoss)
            .where(WorldBoss.id == BOSS_ID, WorldBoss.hp > 0)
            .values(
                hp=case((WorldBoss.hp - accepted < 0, 0), else_=WorldBoss.hp - accepted),
                updated_at=now,
            )
        )
        await db.refresh(boss)
        await add_contribution(db, boss.id, boss.cycle, user.id, accepted, hero_deltas, hero_meta, now)
        await kill_boss_if_depleted(db, now)

    session.damage = int(session.damage) + accepted
    session.last_report_at = now
    session.last_report_seq = int(payload.reportSeq)
    session.heartbeat_at = now
    session.updated_at = now
    await db.commit()
    return _report_view(boss, session, accepted=accepted)


def _report_view(
    boss: WorldBoss,
    session: WorldBossSession,
    *,
    accepted: int,
    duplicate: bool = False,
    paused: bool = False,
) -> dict:
    return {
        "boss": boss_public(boss),
        "damageAccepted": int(accepted),
        "myDamage": int(session.damage),
        "duplicate": duplicate,
        "paused": paused,
    }


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


# WS 推送间隔与榜单刷新间隔（秒）。
WORLDBOSS_POLL_SECONDS = 0.5
WORLDBOSS_LEADERBOARD_SECONDS = 5.0


def _worldboss_producer_factory(session_factory=SessionLocal):
    """共享生产者：每 0.5s 读一次全局 BOSS 状态，每 5s 带一次榜单行。

    原实现是「**每个连接**各自每 0.5s 查两次库」，查询量随连接数线性增长；
    这里改为「每进程一次轮询 + 内存分发」（与 chat / coop 的广播架构一致）。
    榜单行走进程内短 TTL 缓存（`cached_contribution_rows`）；`me` 由各连接用
    `build_leaderboard` 就地拼装，不需要额外查询。
    """
    state: dict = {"seq": 0, "sig": None, "last_lb": 0.0}

    async def produce() -> dict | None:
        async with session_factory() as db:
            boss = await db.get(WorldBoss, BOSS_ID)
            if boss is None:
                return None
            now = time.time()
            sig = (int(boss.hp), boss.status, int(boss.cycle))
            lb_due = now - state["last_lb"] >= WORLDBOSS_LEADERBOARD_SECONDS
            if sig == state["sig"] and not lb_due:
                return None  # 无变化：不推送（hub 会跳过 None）
            state["seq"] += 1
            state["sig"] = sig
            payload: dict = {
                "type": "snapshot" if state["seq"] == 1 else "update",
                "sequence": state["seq"],
                "boss": boss_public(boss),
            }
            if lb_due:
                payload["cycle"] = int(boss.cycle)
                payload["leaderboardRows"] = await qualified_rows(db, boss.cycle)
                state["last_lb"] = now
            return payload

    return produce


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
    queue = await hub.subscribe("worldboss", _worldboss_producer_factory, WORLDBOSS_POLL_SECONDS)
    last_member_check = 0.0
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=MEMBER_CHECK_SECONDS)
            except TimeoutError:
                # 空闲超时：借机做一次廉价的封号 / 账号有效性检查。
                async with SessionLocal() as db:
                    user = await db.get(User, uid)
                    if not user or user.banned:
                        await ws.close(code=4403)
                        return
                last_member_check = time.time()
                continue

            # 榜单行是进程级共享的；这里只做本连接自己的 entries / me 拼装（纯 CPU）。
            rows = payload.pop("leaderboardRows", None)
            if rows is not None:
                payload["leaderboard"] = build_leaderboard(rows, payload.pop("cycle"), uid, 1, 50)
            await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        await hub.unsubscribe("worldboss", queue)
