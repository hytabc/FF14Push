"""世界BOSS：全局共享血量、讨伐周期结算、总伤害榜与档位奖励。

设计要点：
- 全局单行 `WorldBoss(id=1)` 持有共享血量与「讨伐周期」（cycle）；所有玩家共用同一血量。
- 每个玩家一行 `WorldBossSession`（8 英雄 state），由 `worldboss_worker` 按租约推进；
  推进期间输出伤害既写入会话累计，也累加进 `WorldBossContribution`（榜单真相，持久不重置）。
- **结算单位是「讨伐周期」**：周期内 BOSS 血量归零只是进入 respawnSeconds 的短暂休整，
  到点满血重生、cycle 不变，玩家会话不中断、可反复讨伐；只有周期到时（period_ends_at）
  才 cycle+1 并结算上一周期。奖励 = 档位（周期累计伤害）+ 名次加成，贡献 / 奖励行永久保留。
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
    WorldBossCycle,
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


def kill_reward_config() -> dict:
    """击杀奖励配置（每击杀件数 + 单周期上限）。"""
    return reward_config().get("killReward") or {}


def kill_reward_items(kills: int) -> int:
    """击杀奖励件数 = min(本周期击杀次数 × perKill, maxItems)。"""
    cfg = kill_reward_config()
    per = int(cfg.get("perKill", 0) or 0)
    cap = int(cfg.get("maxItems", 0) or 0)
    if per <= 0 or cap <= 0:
        return 0
    return min(max(0, int(kills)) * per, cap)


def period_seconds() -> int:
    """讨伐周期长度（秒）：唯一的结算单位。"""
    return int(WORLD_BOSS.get("periodSeconds", 18000))


def respawn_seconds() -> int:
    """周期内被击杀后的短暂休整（秒），到点满血重生且 cycle 不变。"""
    return int(boss_config()["respawnSeconds"])


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
    now = time.time()
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
        period_ends_at=now + period_seconds(),
        kills=0,
        last_kill_by=None,
        config=deepcopy(WORLD_BOSS),
        updated_at=now,
    )
    db.add(boss)
    await db.commit()
    return boss


async def roll_world_boss(db: AsyncSession, now: float | None = None) -> bool:
    """按服务端时钟推进全局 BOSS 的时间状态（多 worker 安全）。

    三件事，均为条件 UPDATE，同一行只会被一个 worker 生效：
    1. **周期换轮**：`period_ends_at` 到期 → 满血、status=alive、cycle+1、kills=0，
       并结束上一周期全部会话（上一周期进入「已结算可领取」）。
    2. **补周期时间**：老行 / 首次 `period_ends_at IS NULL` → 以当前时间开一轮。
    3. **周期内短休整复活**：被击杀后 respawnSeconds 到期 → 满血、status=alive，**cycle 不变**。
    """
    now = time.time() if now is None else now
    period = period_seconds()
    changed = False

    # 1) 周期换轮（无论 BOSS 存亡都强制重置）。
    #    换轮会把 kills 清零，故先把「即将结束的周期」的击杀数快照下来，供击杀奖励复算。
    period_end = await db.scalar(
        select(WorldBoss.period_ends_at).where(
            WorldBoss.id == BOSS_ID, WorldBoss.period_ends_at.isnot(None)
        )
    )
    ending_cycle: int | None = None
    ending_kills = 0
    if period_end is not None and float(period_end) <= now:
        snap = (
            await db.execute(select(WorldBoss.cycle, WorldBoss.kills).where(WorldBoss.id == BOSS_ID))
        ).first()
        if snap is not None:
            ending_cycle, ending_kills = int(snap[0]), int(snap[1] or 0)

    rolled = await db.execute(
        update(WorldBoss)
        .where(WorldBoss.period_ends_at.isnot(None), WorldBoss.period_ends_at <= now)
        .values(
            cycle=WorldBoss.cycle + 1,
            status=STATUS_ALIVE,
            hp=WorldBoss.max_hp,
            kills=0,
            killed_at=None,
            respawn_at=None,
            period_ends_at=now + period,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if rolled.rowcount:
        changed = True
        new_cycle = await db.scalar(select(WorldBoss.cycle).where(WorldBoss.id == BOSS_ID))
        if new_cycle is not None:
            if ending_cycle is not None:
                await record_cycle_kills(db, ending_cycle, ending_kills, now)
            await end_cycle_sessions(db, int(new_cycle) - 1)

    # 2) 补周期结束时间（老行 / 首次）。
    await db.execute(
        update(WorldBoss)
        .where(WorldBoss.period_ends_at.is_(None))
        .values(period_ends_at=now + period, updated_at=now)
        .execution_options(synchronize_session=False)
    )

    # 3) 周期内短休整复活（cycle 不变，可反复讨伐）。
    revived = await db.execute(
        update(WorldBoss)
        .where(
            WorldBoss.status == STATUS_DEAD,
            WorldBoss.respawn_at.isnot(None),
            WorldBoss.respawn_at <= now,
        )
        .values(
            status=STATUS_ALIVE,
            hp=WorldBoss.max_hp,
            killed_at=None,
            respawn_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return changed or bool(revived.rowcount)


async def kill_boss_if_depleted(db: AsyncSession, now: float) -> bool:
    """血量归零则由先到者记录：进入短暂休整（kills+1、cycle 不变），**不结束会话**。

    周期内玩家可继续讨伐下一个化身；只有 `roll_world_boss` 的周期换轮才结束会话。
    """
    boss = await db.get(WorldBoss, BOSS_ID)
    if boss is None or boss.status != STATUS_ALIVE or int(boss.hp) > 0:
        return False
    boss.status = STATUS_DEAD
    boss.killed_at = now
    boss.respawn_at = now + respawn_seconds()
    boss.hp = 0
    boss.kills = int(boss.kills or 0) + 1
    boss.updated_at = now
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


async def record_cycle_kills(db: AsyncSession, cycle: int, kills: int, now: float) -> None:
    """落库某周期结束时的击杀次数（幂等；只新增行，供击杀奖励按周期号复算）。"""
    existing = await db.scalar(select(WorldBossCycle).where(WorldBossCycle.cycle == int(cycle)))
    if existing is not None:
        existing.kills = max(int(existing.kills or 0), int(kills))
        return
    db.add(WorldBossCycle(cycle=int(cycle), boss_id=BOSS_ID, kills=int(kills), ended_at=now))


async def cycle_kills(db: AsyncSession, cycle: int) -> int:
    """某周期结束时的 BOSS 击杀次数（无记录返回 0）。"""
    row = await db.scalar(select(WorldBossCycle).where(WorldBossCycle.cycle == int(cycle)))
    return int(row.kills or 0) if row is not None else 0


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
    # 伤害已变化：让进程内的榜单缓存立即失效（WS 广播下一次读取即为最新）。
    invalidate_contribution_rows()
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


def reward_tiers() -> list[dict]:
    return list(reward_config().get("tiers") or [])


def rank_bonus_table() -> dict:
    return reward_config().get("rankBonus") or {}


def tier_for_damage(damage: int) -> tuple[int, int]:
    """周期累计伤害命中的最高档位：返回 (档位序号 1-based，0 表示未达任何档, 件数)。"""
    index, items = 0, 0
    for i, tier in enumerate(reward_tiers(), start=1):
        if int(damage) >= int(tier["minDamage"]):
            index, items = i, int(tier["items"])
    return index, items


def rank_bonus_items(rank: int) -> int:
    """名次加成件数（仅前 10 名，其余 0）。"""
    return int(rank_bonus_table().get(str(rank), 0))


def reward_items(rank: int, damage: int, kills: int = 0) -> int:
    """周期奖励件数 = 击杀奖励（全服同额）+ 档位（累计伤害）+ 名次加成（仅前 10 名）；未达门槛为 0。"""
    if int(damage) < int(reward_config()["minDamage"]):
        return 0
    return tier_for_damage(damage)[1] + rank_bonus_items(rank) + kill_reward_items(kills)


def _reward_view(rank: int, damage: int, kills: int = 0) -> dict:
    if int(damage) < int(reward_config()["minDamage"]):
        return {"items": 0, "tier": 0, "tierItems": 0, "rankBonus": 0, "killItems": 0}
    tier, tier_items_value = tier_for_damage(damage)
    bonus = rank_bonus_items(rank)
    kill_items = kill_reward_items(kills)
    return {
        "items": tier_items_value + bonus + kill_items,
        "tier": tier,
        "tierItems": tier_items_value,
        "rankBonus": bonus,
        "killItems": kill_items,
    }


def _qualified(rows: list[dict]) -> list[dict]:
    """只有总伤害 ≥ minDamage 才进入榜单并参与排名。"""
    threshold = int(reward_config()["minDamage"])
    return [row for row in rows if int(row["damage"]) >= threshold]


# 本进程内的贡献行缓存：同一周期内数秒复用，避免每个 WS 连接 / 请求都全表扫贡献表。
# 世界BOSS 的 WS 原实现「每连接每 5s」重算一次榜单（全表扫描 contribution + users），
# 连接数一多就成为最大热点；这里把扫描降为「每进程每 TTL 一次」。
_ROWS_CACHE: dict[int, tuple[float, list[dict]]] = {}
_ROWS_CACHE_TTL_SECONDS = 4.0


async def cached_contribution_rows(db: AsyncSession, cycle: int) -> list[dict]:
    """带短 TTL 的贡献行读取（进程内缓存，多 worker 各自缓存但结果一致）。

    仅供高频、允许数秒陈旧的读取路径使用（WS 广播的榜单）；HTTP 接口与测试请用
    `contribution_rows`，否则刚写入的贡献会被缓存挡住（见 `leaderboard_view(use_cache=)`）。
    """
    cached = _ROWS_CACHE.get(int(cycle))
    now = time.monotonic()
    if cached is not None and now - cached[0] < _ROWS_CACHE_TTL_SECONDS:
        return cached[1]
    rows = await contribution_rows(db, cycle)
    # 只保留当前周期，避免缓存无界增长（换轮后旧周期自然被淘汰）。
    _ROWS_CACHE.clear()
    _ROWS_CACHE[int(cycle)] = (now, rows)
    return rows


def invalidate_contribution_rows() -> None:
    """贡献数据变更后失效缓存（伤害结算立即反映到下一次读取）。"""
    _ROWS_CACHE.clear()


def build_leaderboard(
    rows: list[dict],
    cycle: int,
    user_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    kills: int = 0,
) -> dict:
    """把「已达标、已按伤害降序」的贡献行格式化成榜单视图（纯函数）。

    拆出来是为了让 WS 广播的共享生产者只做一次全表聚合，各连接再用本函数拼自己的
    `entries` / `me`（纯 CPU，无额外查询）。`kills` 为该周期击杀次数（击杀奖励人人同额）。
    """
    offset = max(0, (page - 1) * page_size)
    entries = [
        {
            "rank": offset + index + 1,
            "userId": row["userId"],
            "nickname": row["nickname"],
            "username": row["username"],
            "damage": row["damage"],
            **_reward_view(offset + index + 1, row["damage"], kills),
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
                    **_reward_view(index + 1, row["damage"], kills),
                    "heroes": hero_breakdown(row),
                }
                break
    return {
        "cycle": cycle,
        "minDamage": int(reward_config()["minDamage"]),
        "kills": int(kills),
        "total": len(rows),
        "page": page,
        "pageSize": page_size,
        "entries": entries,
        "me": me,
    }


async def qualified_rows(db: AsyncSession, cycle: int) -> list[dict]:
    """当前周期的「已达标」贡献行（走进程内短 TTL 缓存），供 WS 共享生产者复用。"""
    return _qualified(await cached_contribution_rows(db, cycle))


async def leaderboard_view(
    db: AsyncSession,
    cycle: int,
    user_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    *,
    use_cache: bool = False,
    kills: int = 0,
) -> dict:
    rows = (
        await cached_contribution_rows(db, cycle)
        if use_cache
        else await contribution_rows(db, cycle)
    )
    return build_leaderboard(_qualified(rows), cycle, user_id, page, page_size, kills)


async def _settled_cycles(db: AsyncSession, user_id: int, boss: WorldBoss) -> list[int]:
    """该账号已达到门槛、且已结算的周期号，升序。

    结算单位是「讨伐周期」：只有已换轮（`cycle < 当前 cycle`）的周期才可领取；
    周期内 BOSS 是否被击杀与结算无关。
    """
    contributions = (
        await db.scalars(
            select(WorldBossContribution).where(WorldBossContribution.user_id == user_id)
        )
    ).all()
    if not contributions:
        return []
    threshold = int(reward_config()["minDamage"])
    return sorted(c.cycle for c in contributions if int(c.damage) >= threshold and c.cycle < boss.cycle)


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

    ended = target_cycle < boss.cycle
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

    kills = await cycle_kills(db, target_cycle)
    count = reward_items(rank, int(contribution.damage), kills)
    generated = [generate_exclusive_item() for _ in range(max(0, count))]
    grants = await grant_generated_items(db, user, generated, f"worldBoss:{target_cycle}") if generated else {"items": [], "autoSold": [], "autoGold": 0}

    reward_view = _reward_view(rank, int(contribution.damage), kills)
    receipt = {
        "cycle": target_cycle,
        "rank": rank,
        "items": count,
        "tier": reward_view["tier"],
        "tierItems": reward_view["tierItems"],
        "rankBonus": reward_view["rankBonus"],
        "kills": kills,
        "killItems": reward_view["killItems"],
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
                "shield": float(hero.get("shield", 0.0)),
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
