"""自动战斗：会话管理、上报校验与结算。来源：PRD 战斗 2.7、地区关卡、防作弊 2.5

权威边界：客户端只上报「发生了什么」，金币/经验一律由服务端重新结算。
装备只能通过抽箱获取（BOSS 宝箱见 _settle_boss），小怪与精英不掉落装备。
不做离线收益：会话结束时战斗即停止。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Sequence

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentHero, CurrentItems, CurrentSockets, CurrentUser, DbSession
from app.models import (
    AuditLog,
    BattleSession,
    Hero,
    HeroSkillStat,
    Item,
    RegionProgress,
    User,
)
from app.schemas.game import BattleReportRequest, BattleStartRequest, BattleStopRequest, DifficultyRequest
from app.services.codex import unlock_monster, unlock_monsters
from app.services.combat_model import effective_penalty, boss_stats, max_kills_in_seconds, resolve_job_skills
from app.services import consumables
from app.services.difficulty import (
    MAX_LEVEL,
    active_difficulty,
    clamp_level,
    monster_exp_multiplier,
    monster_gold_multiplier,
)
from app.services.drop_luck import chest_rarity_luck
from app.services.egg_heroes import charge_grants, exp_bonus_pct
from app.services.game_config import CONFIG
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item
from app.services.loot import boss_box_for_region, chest_by_id
from app.services.progression import apply_exp, combat_exp, exp_calculation, gold_calculation
from app.services.playtime import add_play_ms
from app.services.regions_util import apply_exp_bonus, kills_required, roll_gold, spawn_interval
from app.services.stats import compute_stats
from app.services.validator import MAX_ELAPSED_MS, MIN_ELAPSED_MS, validate_report

from app.services.qualification import ensure_region_progress, require_region, region_access
from app.services.roster import end_treasure_runs
from app.services.balance import BALANCE, soft_penalty
from app.services.valuation import hero_power

router = APIRouter(prefix="/battle", tags=["battle"])
settings = get_settings()


async def _progress(
    db: DbSession, user_id: int, difficulty: int, region_id: int
) -> RegionProgress | None:
    return (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user_id,
                RegionProgress.difficulty == difficulty,
                RegionProgress.region_id == region_id,
            )
        )
    ).scalar_one_or_none()


def _max_region_id() -> int:
    return max(CONFIG.region_by_id)


async def _end_active_sessions(db: DbSession, user_id: int) -> None:
    rows = (
        await db.execute(
            select(BattleSession).where(BattleSession.user_id == user_id, BattleSession.active.is_(True))
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.active = False
        row.ended_at = now


@router.post("/session/start")
async def start_session(
    payload: BattleStartRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems, sockets: CurrentSockets
) -> dict:
    if payload.regionId not in CONFIG.region_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地区不存在")

    difficulty = active_difficulty(user)
    await require_region(db,user.id,hero,items,payload.regionId,difficulty)
    progress = await ensure_region_progress(db, user.id, difficulty, payload.regionId)
    progress.unlocked = True

    await _end_active_sessions(db, user.id)
    # 四活动互斥：开始战斗即停止进行中的采集/生产/钓鱼
    from app.services.dohdol_util import end_active_sessions as _end_activity

    await _end_activity(db, user.id)
    # 挖宝同为战斗类活动：开始地区战斗即结束进行中的副本（已入账奖励保留）。
    await end_treasure_runs(db, user.id)

    hero.current_region_id = payload.regionId
    hero.region_kill_count = 0  # PRD 地区 6.2：切换地区后计数从 0 开始

    session = BattleSession(
        user_id=user.id,
        hero_id=hero.id,
        region_id=payload.regionId,
        difficulty=difficulty,
        active=True,
        kill_credit=0.0,
    )
    db.add(session)
    await db.commit()

    region = CONFIG.region_by_id[payload.regionId]
    return {
        "sessionId": session.id,
        "penalty": effective_penalty(compute_stats(hero,items,sockets),payload.regionId),
        "regionId": payload.regionId,
        "difficulty": difficulty,
        "killsRequired": kills_required(payload.regionId),
        "spawnInterval": spawn_interval(payload.regionId),
        "boss": boss_stats(payload.regionId, difficulty),
        "region": region,
    }


@router.post("/session/report")
async def report(
    payload: BattleReportRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
    sockets: CurrentSockets,
) -> dict:
    session = (
        await db.execute(
            select(BattleSession).where(
                BattleSession.id == payload.sessionId,
                BattleSession.user_id == user.id,
                BattleSession.active.is_(True),
                BattleSession.hero_id == hero.id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="战斗会话不存在或已结束")
    if session.region_id != payload.regionId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="地区与会话不一致")

    difficulty = int(session.difficulty or 0)
    await require_region(db,user.id,hero,items,payload.regionId,difficulty)
    stats = compute_stats(hero, items, sockets)

    # 彩蛋技能「拔豆芽」：本次上报释放的充能技能 → 累加奖励翻倍怪物数（上限 20，可跨上报保留）。
    # 先在本地计算，等上报通过校验后再写回，避免被拒绝的上报也能累积充能。
    grants = charge_grants(stats.egg_id, stats.job_id)
    granted = 0
    if grants:
        for cast in payload.skillCasts:
            if cast.skillId in grants and cast.count > 0:
                granted += grants[cast.skillId] * min(cast.count, 10000)
    double_charges = min(20, int(hero.double_reward_charges or 0) + granted)

    # 客户端只在有事件时才上报，上报间隔并不固定：窗口必须以服务端时钟为准，
    # 否则额度永远只能按固定短窗口核算，合法单杀会被判超速。
    #
    # 但「以服务端时钟为准」必须是**只认服务端时钟**：客户端上报的 elapsedMs 可被
    # 篡改（改系统时间 / 浏览器加速插件），一旦采信它就能凭空放大击杀额度——
    # 等于允许把游戏加速。这里只使用服务端记录的真实间隔。
    now = datetime.now(timezone.utc)
    last_at = session.last_report_at or session.started_at
    if last_at.tzinfo is None:  # SQLite 会返回 naive datetime
        last_at = last_at.replace(tzinfo=timezone.utc)
    server_elapsed_ms = int(max(0.0, (now - last_at).total_seconds() * 1000))
    window_ms = max(MIN_ELAPSED_MS, min(MAX_ELAPSED_MS, server_elapsed_ms))

    # 击杀额度：按理论上限随上报累积，跨上报保留余额，避免短上报把合法击杀全部截断。
    # 传入英雄等级，使越级英雄的额度同步受等级压制收紧。
    allowance = float(session.kill_credit) + max_kills_in_seconds(
        stats, payload.regionId, window_ms / 1000.0, settings.report_tolerance, hero.level, difficulty
    )

    result = validate_report(
        stats=stats,
        region_id=payload.regionId,
        elapsed_ms=window_ms,
        kills=[k.model_dump() for k in payload.kills],
        allowance=allowance,
        tolerance=settings.report_tolerance,
        double_charges=double_charges,
        difficulty=difficulty,
    )

    if not result.accepted:
        db.add(
            AuditLog(
                user_id=user.id,
                reason=result.reject_reason or "invalid_report",
                payload={"regionId": payload.regionId, "kills": len(payload.kills), "issues": result.issues},
                rejected=True,
            )
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"rejected": result.issues})

    # 彩蛋「拔豆芽」：上报通过后写回充能，并扣除本次实际翻倍的怪物数
    hero.double_reward_charges = max(0, double_charges - result.doubled_kills)

    session.kill_credit = max(0.0, allowance - result.consumed_credit)
    # 累计在线时长：只计入通过校验的上报窗口（服务端时钟，已按上限封顶）。
    add_play_ms(user, window_ms)

    rng = random.Random()

    # 药水/食物加成（只影响结算，不影响战力与门槛）
    potion_mods = await consumables.exp_gold_mods(db, user.id)
    merged_mods = dict(stats.term_mods)
    for key, value in potion_mods.items():
        merged_mods[key] = merged_mods.get(key, 0.0) + float(value)
    # 彩蛋被动「豆芽精」：经验获取倍率提升（与小怪/BOSS 结算同源）
    egg_exp = exp_bonus_pct(stats.egg_id)
    if egg_exp:
        merged_mods["expGainPct"] = merged_mods.get("expGainPct", 0.0) + egg_exp

    # 金币与经验（服务端重新结算）
    reward_multiplier = effective_penalty(stats,payload.regionId)["rewardMultiplier"]
    gold_base = int(result.total_gold)
    gold_after_penalty = int(gold_base * reward_multiplier)
    result.total_gold = int(gold_after_penalty * (1.0 + potion_mods.get("goldGainPct", 0.0) / 100.0))
    result.total_exp = int(result.total_exp * reward_multiplier)
    user.gold = int(user.gold) + result.total_gold
    gained_exp = apply_exp_bonus(result.total_exp, merged_mods)  # 经验获取效率 Buff
    after_bonus_exp = gained_exp
    gained_exp = await combat_exp(db, hero, gained_exp)
    level_info = apply_exp(hero, gained_exp)

    # 装备：怪物不掉落，仅能通过抽箱获取（BOSS 宝箱见 _settle_boss）
    # 图鉴按击杀聚合后批量解锁：原实现每只怪一次 select，上报高频时会形成 N+1。
    kill_counts: dict[str, int] = {}
    for kill in result.kills:
        kill_counts[kill.monster_id] = kill_counts.get(kill.monster_id, 0) + 1
    await unlock_monsters(db, user.id, kill_counts)

    # 技能使用统计：一次取回本英雄已有的统计行，循环内内存累加（原实现每个技能一次 select）。
    valid_skills = {s["id"] for s in resolve_job_skills(stats)}
    skill_casts = [
        (cast.skillId, min(cast.count, 10000))
        for cast in payload.skillCasts
        if cast.skillId in valid_skills and cast.count > 0
    ]
    if skill_casts:
        stat_rows = {
            str(row.skill_id): row
            for row in (
                await db.execute(
                    select(HeroSkillStat).where(HeroSkillStat.hero_id == hero.id)
                )
            ).scalars().all()
        }
        for skill_id, count in skill_casts:
            row = stat_rows.get(skill_id)
            if row is None:
                row = HeroSkillStat(
                    hero_id=hero.id, job_id=stats.job_id, skill_id=skill_id, cast_count=0
                )
                db.add(row)
                stat_rows[skill_id] = row
            row.cast_count = int(row.cast_count) + count

    # 击杀计数（服务端权威）
    required = kills_required(payload.regionId)
    credited = len(result.kills)
    if payload.bossKilled:
        # 客户端本地计数达到 required 才会刷出 BOSS，而服务端按窗口额度取整入账：
        # 遇到爆发式击杀（暴击/技能/多目标）时本批会被截断，服务端计数便滞后于客户端。
        # 客户端计数 = 服务端计数 + 本批在途击杀，故缺口恰好不超过本批上报的击杀数。
        # 若仍按截断后的计数判定，_settle_boss 会静默丢弃 BOSS 结算，客户端会停在
        # cleared 阶段不再产生事件，从而永远无法进入下一地区。
        # 这里仅对 BOSS 上报按客户端本批实际击杀补齐；凭空虚报的击杀仍受 validate_report
        # 的「超过额度 2 倍即整单拒绝」约束，因此无法借此加速刷 BOSS。
        credited = len(payload.kills)
    hero.region_kill_count = min(required, int(hero.region_kill_count) + credited)

    if payload.died:
        hero.region_kill_count = 0  # PRD 地区 3.2：阵亡后小怪击杀计数归零

    boss_result = None
    if payload.bossKilled:
        boss_result = await _settle_boss(
            db, user, hero, items, payload, rng, merged_mods, window_ms, difficulty, sockets
        )

    session.last_report_at = now
    session.total_kills = int(session.total_kills) + len(result.kills)
    session.total_gold = int(session.total_gold) + result.total_gold
    session.total_exp = int(session.total_exp) + result.total_exp

    await db.commit()

    return {
        "gold": int(user.gold),
        "goldGained": result.total_gold,
        "goldCalculation": gold_calculation(gold_base, gold_after_penalty, result.total_gold),
        "expGained": gained_exp,
        "expCalculation": exp_calculation(result.total_exp, after_bonus_exp, gained_exp),
        "level": level_info,
        "killCount": int(hero.region_kill_count),
        "killsRequired": required,
        "items": [],
        "autoSold": [],
        "autoGold": 0,
        "boss": boss_result,
        "warnings": result.issues,
    }


async def _settle_boss(
    db: DbSession,
    user: User,
    hero: Hero,
    items: Sequence[Item],
    payload: BattleReportRequest,
    rng: random.Random,
    term_mods: dict[str, float] | None = None,
    window_ms: int = 0,
    difficulty: int = 0,
    socket_mods: dict[str, float] | None = None,
) -> dict | None:
    required = kills_required(payload.regionId)
    if int(hero.region_kill_count) < required:
        return None

    progress = await _progress(db, user.id, difficulty, payload.regionId)
    if progress is None:
        progress = await ensure_region_progress(db, user.id, difficulty, payload.regionId)

    region = CONFIG.region_by_id[payload.regionId]
    gold_potion = float((term_mods or {}).get("goldGainPct", 0.0)) / 100.0
    gold_raw = roll_gold(payload.regionId, "boss", 0.0, rng)
    gold_diff_mult = monster_gold_multiplier(difficulty)
    gold_reward_mult = effective_penalty(compute_stats(hero,items,socket_mods),payload.regionId)["rewardMultiplier"]
    boss_gold = int(gold_raw * gold_reward_mult * (1.0 + gold_potion) * gold_diff_mult)
    # 金币明细：难度计入「结算基础」（与地区小怪上报口径一致），末项吸收四舍五入残差。
    gold_base = int(gold_raw * gold_diff_mult)
    gold_after_penalty = int(gold_base * gold_reward_mult)
    base_boss_exp = max(
        1, int(boss_gold * float(CONFIG.monsters["xpPerGold"]) * monster_exp_multiplier(difficulty))
    )
    boss_exp = apply_exp_bonus(base_boss_exp, term_mods or {})
    after_bonus_exp = boss_exp

    user.gold = int(user.gold) + boss_gold
    boss_exp = await combat_exp(db, hero, boss_exp)
    level_info = apply_exp(hero, boss_exp)
    await unlock_monster(db, user.id, f"boss_r{payload.regionId}")

    box_id = boss_box_for_region(payload.regionId)
    box = chest_by_id(box_id)
    generated = []
    if box:
        luck, _ = await chest_rarity_luck(db, user.id, hero, items)
        item, _ = generate_item(box["category"], hero.level, box_tier=box["tier"], rng=rng, luck=luck)
        generated.append(item)
    grant = await grant_generated_items(db, user, generated, source="boss", rng=rng)

    first_clear = not progress.cleared
    if first_clear:
        progress.cleared = True
        progress.cleared_at = datetime.now(timezone.utc)
        # 通关耗时同样以服务端窗口为上限：客户端可以少报，但不能谎报超短耗时刷榜
        if payload.bossFightMs is not None:
            progress.best_clear_ms = max(0, min(int(payload.bossFightMs), window_ms))
        next_region = payload.regionId + 1
        if next_region in CONFIG.region_by_id:
            nxt = await _progress(db, user.id, difficulty, next_region)
            if nxt is None:
                nxt = await ensure_region_progress(db, user.id, difficulty, next_region)
            if not nxt.unlocked:
                access = await region_access(db,user.id,hero,items,difficulty)
                nxt.unlocked = not access[next_region]

    # 周目制：每次击败当前难度最后一个地区的关底 BOSS 都可解锁下一难度。
    # 刻意不要求 first_clear：旧存档在功能上线前已通关最后一个地区（cleared 已为 True），
    # 若要求首通则永远无法解锁。
    unlocked_difficulty = None
    if (
        payload.regionId == _max_region_id()
        and difficulty < MAX_LEVEL
        and int(user.battle_difficulty_max) < difficulty + 1
    ):
        user.battle_difficulty_max = difficulty + 1
        unlocked_difficulty = difficulty + 1

    hero.region_kill_count = 0

    return {
        "gold": boss_gold,
        "goldCalculation": gold_calculation(gold_base, gold_after_penalty, boss_gold),
        "exp": boss_exp,
        "expCalculation": exp_calculation(base_boss_exp, after_bonus_exp, boss_exp),
        "level": level_info,
        "firstClear": first_clear,
        "nextRegionId": payload.regionId + 1 if payload.regionId + 1 in CONFIG.region_by_id else None,
        "unlockedDifficulty": unlocked_difficulty,
        "box": box["name"] if box else None,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "bossName": region["bossName"],
    }


@router.post("/session/stop")
async def stop_session(payload: BattleStopRequest, db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    session = (
        await db.execute(
            select(BattleSession).where(BattleSession.id == payload.sessionId, BattleSession.user_id == user.id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="战斗会话不存在")
    session.active = False
    session.ended_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "message": "会话已结束，战斗暂停（本作不回放离线收益）"}


@router.post("/death")
async def report_death(db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    """阵亡：小怪阶段进度重置。来源：PRD 地区 3.2"""
    hero.region_kill_count = 0
    await db.commit()
    return {"ok": True, "killCount": 0, "message": "英雄阵亡，小怪阶段进度已重置"}


@router.post("/difficulty")
async def set_difficulty(
    payload: DifficultyRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    """切换地区战斗难度（仅限已解锁范围）。周目制：切换后落回该难度下「已通关最高地区 +1」。

    难度 0 = 当前各地区数值。解锁下一难度需在当前难度通关最后一个地区（见 `_settle_boss`）。
    """
    level = int(payload.level)
    unlocked = clamp_level(user.battle_difficulty_max)
    if level < 0 or level > MAX_LEVEL or level > unlocked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该难度尚未解锁")

    await _end_active_sessions(db, user.id)
    user.battle_difficulty = level

    cleared_rows = (
        await db.execute(
            select(RegionProgress.region_id).where(
                RegionProgress.user_id == user.id,
                RegionProgress.difficulty == level,
                RegionProgress.cleared.is_(True),
            )
        )
    ).scalars().all()
    cleared_max = max([int(r) for r in cleared_rows], default=0)
    target = min(cleared_max + 1, _max_region_id())
    await ensure_region_progress(db, user.id, level, target)
    hero.current_region_id = target
    hero.region_kill_count = 0
    await db.commit()

    return {
        "difficulty": level,
        "unlocked": int(user.battle_difficulty_max),
        "maxLevel": MAX_LEVEL,
        "currentRegionId": target,
    }
