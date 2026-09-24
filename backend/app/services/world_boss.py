"""世界BOSS：全局共享血量、周期刷新、总伤害榜与击杀结算奖励。

设计要点：
- 全局单行 `WorldBoss(id=1)` 持有共享血量与周期；所有玩家共用同一血量。
- 每个玩家一行 `WorldBossSession`（8 英雄 state），由 `worldboss_worker` 按租约推进；
  推进期间输出伤害既写入会话累计，也累加进 `WorldBossContribution`（榜单真相，持久不重置）。
- 击杀按「周期」结算：BOSS 血量归零 → status=dead、respawn_at=now+respawnSeconds；
  到期由 `respawn_due_bosses` 刷新并 cycle+1，开启新周期。贡献 / 奖励行永久保留。
"""

from __future__ import annotations

import time
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.world_boss import (
    SESSION_RUNNING,
    STATUS_ALIVE,
    STATUS_DEAD,
    WorldBoss,
    WorldBossContribution,
    WorldBossReward,
    WorldBossSession,
)
from app.services.admin import is_admin
from app.services.game_config import CONFIG
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_exclusive_item
from app.services.roster import lock_user

WORLD_BOSS = CONFIG.worldboss
BOSS_ID = 1


def boss_config() -> dict:
    return WORLD_BOSS["boss"]


def rules() -> dict:
    return WORLD_BOSS["rules"]


def reward_config() -> dict:
    return WORLD_BOSS["reward"]


def phases() -> list[dict]:
    return list(WORLD_BOSS.get("phases") or [])


def phase_for_ratio(ratio: float) -> dict:
    """按剩余血量占比取阶段：满足 ratio ≥ minHpRatio 的最高阶段（血量越低阶段越高）。"""
    table = phases()
    if not table:
        return {"id": 1, "name": "第一阶段", "minHpRatio": 0.0, "defenseMultiplier": 1.0, "skillPotencyMultiplier": 1.0}
    return max(table, key=lambda p: float(p["minHpRatio"]) if float(p["minHpRatio"]) <= ratio else -1.0)


def hero_slots() -> int:
    return int(rules()["heroSlots"])


def level_multiplier(level: int) -> float:
    """等级削弱乘数：80 级 → weaknessFloor，满级（100）→ 1.0，中间线性。"""
    rule = rules()
    floor_level = int(rule["levelRequirement"])
    full_level = int(rule["fullPowerLevel"])
    floor = float(rule["weaknessFloor"])
    if full_level <= floor_level:
        return 1.0
    ratio = (int(level) - floor_level) / (full_level - floor_level)
    return floor + (1.0 - floor) * max(0.0, min(1.0, ratio))


async def ensure_world_boss(db: AsyncSession) -> WorldBoss:
    """幂等创建全局 BOSS 单行（不存在时插入 id=1）。"""
    boss = await db.get(WorldBoss, BOSS_ID)
    if boss is not None:
        return boss
    cfg = boss_config()
    boss = WorldBoss(
        id=BOSS_ID,
        boss_key=str(cfg["id"]),
        name=str(cfg["name"]),
        cycle=1,
        hp=int(cfg["maxHp"]),
        max_hp=int(cfg["maxHp"]),
        attack=int(cfg["attack"]),
        status=STATUS_ALIVE,
        killed_at=None,
        respawn_at=None,
        last_kill_by=None,
        config=deepcopy(WORLD_BOSS),
        updated_at=time.time(),
    )
    db.add(boss)
    await db.commit()
    return boss


async def respawn_due_bosses(db: AsyncSession, now: float | None = None) -> bool:
    """刷新到期的 BOSS：满血、status=alive、cycle+1（新周期）。条件 UPDATE，多 worker 安全。"""
    now = time.time() if now is None else now
    result = await db.execute(
        update(WorldBoss)
        .where(
            WorldBoss.status == STATUS_DEAD,
            WorldBoss.respawn_at.isnot(None),
            WorldBoss.respawn_at <= now,
        )
        .values(
            status=STATUS_ALIVE,
            hp=WorldBoss.max_hp,
            cycle=WorldBoss.cycle + 1,
            killed_at=None,
            respawn_at=None,
            updated_at=now,
        )
    )
    return bool(result.rowcount)


async def kill_boss_if_depleted(db: AsyncSession, now: float) -> bool:
    """血量归零则由先到者结算：标记死亡 + 刷新时间，并结束该周期全部会话。"""
    boss = await db.get(WorldBoss, BOSS_ID)
    if boss is None or boss.status != STATUS_ALIVE or int(boss.hp) > 0:
        return False
    boss.status = STATUS_DEAD
    boss.killed_at = now
    boss.respawn_at = now + int(boss_config()["respawnSeconds"])
    boss.hp = 0
    boss.updated_at = now
    await end_cycle_sessions(db, boss.cycle)
    return True


async def end_cycle_sessions(db: AsyncSession, cycle: int) -> None:
    """结束某周期全部会话（击杀后不再推进；贡献已落库）。"""
    sessions = (
        await db.scalars(select(WorldBossSession).where(WorldBossSession.cycle == cycle))
    ).all()
    for session in sessions:
        session.status = "ended"
        session.lease_until = 0
        session.lease_owner = None


def merge_party(
    existing: list[dict] | None, deltas: dict[str, int], meta: dict[str, dict]
) -> list[dict]:
    """把本 tick 的分英雄伤害增量并入累计（按 heroId 累加），供榜单展开查看。

    贡献按周期累计、且可跨多次上阵（离开后重进），因此这里必须累加增量而非覆盖快照。
    """
    by_id: dict[str, dict] = {}
    for entry in existing or []:
        by_id[str(entry.get("heroId"))] = dict(entry)
    for hero_id, amount in deltas.items():
        if amount <= 0:
            continue
        info = meta.get(hero_id, {})
        row = by_id.get(hero_id)
        if row is None:
            row = {
                "slot": int(info.get("slot", 0)),
                "heroId": int(info.get("heroId", 0)),
                "name": info.get("name", ""),
                "jobId": info.get("jobId", ""),
                "level": int(info.get("level", 1)),
                "damage": 0,
            }
            by_id[hero_id] = row
        row["damage"] = int(row.get("damage", 0)) + int(amount)
        for key in ("name", "jobId", "level", "slot"):
            if info.get(key) not in (None, ""):
                row[key] = info[key]
    return sorted(by_id.values(), key=lambda r: int(r.get("slot", 0)))


async def add_contribution(
    db: AsyncSession,
    boss_id: int,
    cycle: int,
    user_id: int,
    delta: int,
    hero_deltas: dict[str, int] | None,
    hero_meta: dict[str, dict] | None,
    now: float,
) -> WorldBossContribution:
    """累加某账号本周期总伤害与分英雄伤害；按 (cycle,user_id) 唯一，重复调用累加而非覆盖。"""
    row = await db.scalar(
        select(WorldBossContribution)
        .where(WorldBossContribution.cycle == cycle, WorldBossContribution.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        row = WorldBossContribution(
            boss_id=boss_id,
            cycle=cycle,
            user_id=user_id,
            damage=0,
            party=[],
            updated_at=now,
            created_at=now,
        )
        db.add(row)
    row.damage = int(row.damage) + max(0, int(delta))
    if hero_deltas:
        row.party = merge_party(row.party, hero_deltas, hero_meta or {})
    row.updated_at = now
    return row


async def contribution_rows(db: AsyncSession, cycle: int) -> list[dict]:
    """某周期总伤害榜（实时聚合，不缓存）。管理员 / 封禁 / 无英雄账号剔除。"""
    rows = (
        await db.scalars(
            select(WorldBossContribution).where(WorldBossContribution.cycle == cycle)
        )
    ).all()
    if not rows:
        return []
    user_ids = [r.user_id for r in rows]
    users = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
    by_id = {u.id: u for u in users}
    out: list[dict] = []
    for row in rows:
        user = by_id.get(row.user_id)
        if user is None or user.banned or is_admin(user):
            continue
        out.append(
            {
                "userId": user.id,
                "nickname": user.nickname,
                "username": user.username,
                "damage": int(row.damage),
                "party": row.party or [],
                "createdAt": float(row.created_at or 0),
            }
        )
    out.sort(key=lambda item: (-item["damage"], item["createdAt"]))
    return out


def hero_breakdown(row: dict) -> list[dict]:
    """某账号本周期各英雄的伤害与占比（按伤害降序），供榜单点击展开查看。"""
    total = max(1, int(row.get("damage", 0)))
    heroes: list[dict] = []
    for hero in row.get("party") or []:
        damage = int(hero.get("damage", 0))
        heroes.append(
            {
                "slot": int(hero.get("slot", 0)),
                "heroId": int(hero.get("heroId", 0)),
                "name": hero.get("name", ""),
                "jobId": hero.get("jobId", ""),
                "level": int(hero.get("level", 1)),
                "damage": damage,
                "pct": round(damage / total * 100, 2),
            }
        )
    heroes.sort(key=lambda item: -item["damage"])
    return heroes


def items_for_rank(rank: int) -> int:
    """名次 → 奖励件数（配置化递减曲线，未列名次取 defaultItems）。"""
    cfg = reward_config()
    table = cfg.get("rankItems") or {}
    return int(table.get(str(rank), cfg.get("defaultItems", 1)))


def _qualified(rows: list[dict]) -> list[dict]:
    """只有总伤害 ≥ minDamage 才进入榜单并参与排名。"""
    threshold = int(reward_config()["minDamage"])
    return [row for row in rows if int(row["damage"]) >= threshold]


async def leaderboard_view(
    db: AsyncSession, cycle: int, user_id: int | None = None, page: int = 1, page_size: int = 50
) -> dict:
    rows = _qualified(await contribution_rows(db, cycle))
    offset = max(0, (page - 1) * page_size)
    entries = [
        {
            "rank": offset + index + 1,
            "userId": row["userId"],
            "nickname": row["nickname"],
            "username": row["username"],
            "damage": row["damage"],
            "items": items_for_rank(offset + index + 1),
            "heroes": hero_breakdown(row),
        }
        for index, row in enumerate(rows[offset : offset + page_size])
    ]
    me = None
    if user_id is not None:
        for index, row in enumerate(rows):
            if row["userId"] == user_id:
                me = {
                    "rank": index + 1,
                    "userId": user_id,
                    "nickname": row["nickname"],
                    "username": row["username"],
                    "damage": row["damage"],
                    "items": items_for_rank(index + 1),
                    "heroes": hero_breakdown(row),
                }
                break
    return {
        "cycle": cycle,
        "minDamage": int(reward_config()["minDamage"]),
        "total": len(rows),
        "page": page,
        "pageSize": page_size,
        "entries": entries,
        "me": me,
    }


async def _settled_cycles(db: AsyncSession, user_id: int, boss: WorldBoss) -> list[int]:
    """该账号已达到门槛、且已结算（BOSS 已被击杀）的周期号，升序。"""
    contributions = (
        await db.scalars(
            select(WorldBossContribution).where(WorldBossContribution.user_id == user_id)
        )
    ).all()
    if not contributions:
        return []
    threshold = int(reward_config()["minDamage"])
    ended = boss.status == STATUS_DEAD
    return sorted(
        c.cycle
        for c in contributions
        if int(c.damage) >= threshold and (c.cycle < boss.cycle or (c.cycle == boss.cycle and ended))
    )


async def latest_settled_cycle(db: AsyncSession, user_id: int, boss: WorldBoss) -> int | None:
    """最近一个已结算周期号（供领取解析；已领取也返回，以便幂等返回回执）。"""
    cycles = await _settled_cycles(db, user_id, boss)
    return cycles[-1] if cycles else None


async def unclaimed_cycle(db: AsyncSession, user_id: int, boss: WorldBoss) -> int | None:
    """最近一个已结算且未领取的周期号（无则 None），供页面提示「可领取」。"""
    cycles = await _settled_cycles(db, user_id, boss)
    if not cycles:
        return None
    claimed = {
        c
        for c in (
            await db.scalars(
                select(WorldBossReward.cycle).where(WorldBossReward.user_id == user_id)
            )
        ).all()
    }
    remaining = [c for c in cycles if c not in claimed]
    return remaining[-1] if remaining else None


async def claim_reward(db: AsyncSession, user_id: int, cycle: int | None = None) -> dict:
    """领取某已结算周期的奖励（幂等）。未指定周期时取最近一个已结算未领取周期。"""
    boss = await db.get(WorldBoss, BOSS_ID)
    if boss is None:
        raise HTTPException(409, "世界BOSS 尚未初始化")
    user = await lock_user(db, user_id)

    target_cycle = cycle if cycle is not None else await latest_settled_cycle(db, user_id, boss)
    if target_cycle is None:
        raise HTTPException(409, "暂无可领取的世界BOSS 奖励")

    existing = await db.scalar(
        select(WorldBossReward).where(
            WorldBossReward.cycle == target_cycle, WorldBossReward.user_id == user_id
        )
    )
    if existing is not None:
        return existing.receipt

    ended = target_cycle < boss.cycle or (target_cycle == boss.cycle and boss.status == STATUS_DEAD)
    if not ended:
        raise HTTPException(409, "本轮尚未结算，无法领取")

    contribution = await db.scalar(
        select(WorldBossContribution).where(
            WorldBossContribution.cycle == target_cycle, WorldBossContribution.user_id == user_id
        )
    )
    threshold = int(reward_config()["minDamage"])
    if contribution is None or int(contribution.damage) < threshold:
        raise HTTPException(409, f"总伤害未达到 {threshold}，无法领取奖励")

    rows = _qualified(await contribution_rows(db, target_cycle))
    rank = next((index + 1 for index, row in enumerate(rows) if row["userId"] == user_id), 0)
    if rank <= 0:
        raise HTTPException(409, "本轮未进入奖励榜单")

    count = items_for_rank(rank)
    generated = [generate_exclusive_item() for _ in range(max(0, count))]
    grants = await grant_generated_items(db, user, generated, f"worldBoss:{target_cycle}") if generated else {"items": [], "autoSold": [], "autoGold": 0}

    receipt = {
        "cycle": target_cycle,
        "rank": rank,
        "items": count,
        "damage": int(contribution.damage),
        "grants": grants,
        "gold": int(user.gold),
    }
    db.add(
        WorldBossReward(
            boss_id=BOSS_ID,
            cycle=target_cycle,
            user_id=user_id,
            rank=rank,
            items=count,
            receipt=receipt,
            claimed_at=time.time(),
        )
    )
    await db.flush()
    return receipt


def session_public(state: dict) -> dict:
    """会话 state 的前端精简视图（去掉 8 英雄完整快照，只留展示字段）。"""
    heroes = []
    for hero in state.get("heroes", []):
        snap = hero.get("snapshot", {})
        heroes.append(
            {
                "slot": int(hero.get("slot", 0)),
                "heroId": int(snap.get("heroId", 0)),
                "name": snap.get("name", ""),
                "jobId": snap.get("jobId", ""),
                "level": int(snap.get("level", 1)),
                "levelMultiplier": float(snap.get("levelMultiplier", 1.0)),
                "maxHp": float(snap.get("stats", {}).get("max_hp", 0.0)),
                "hp": float(hero.get("hp", 0.0)),
                "mp": float(hero.get("mp", 0.0)),
                "maxMp": float(snap.get("stats", {}).get("max_mp", 0.0)),
                "deadUntil": int(hero.get("deadUntil", 0)),
                "damage": round(float(hero.get("damage", 0.0))),
                "deaths": int(hero.get("deaths", 0)),
            }
        )
    return {
        "status": state.get("status", SESSION_RUNNING),
        "elapsedMs": int(state.get("elapsedMs", 0)),
        "damageDealt": round(float(state.get("damageDealt", 0.0))),
        "heroes": heroes,
        "events": state.get("events", [])[-60:],
        "eventSequence": int(state.get("eventSequence", 0)),
    }
