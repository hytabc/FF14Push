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
from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import (
    AuditLog,
    BattleSession,
    Hero,
    HeroSkillStat,
    Item,
    RegionProgress,
    User,
)
from app.schemas.game import BattleReportRequest, BattleStartRequest, BattleStopRequest
from app.services.codex import unlock_monster
from app.services.combat_model import effective_penalty, boss_stats, max_kills_in_seconds, resolve_job_skills
from app.services.drop_luck import rarity_luck, user_drop_rate
from app.services.game_config import CONFIG
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item
from app.services.loot import boss_box_for_region, chest_by_id
from app.services.progression import apply_exp
from app.services.regions_util import apply_exp_bonus, kills_required, roll_gold, spawn_interval
from app.services.stats import compute_stats
from app.services.validator import MAX_ELAPSED_MS, MIN_ELAPSED_MS, validate_report

from app.services.qualification import require_region, region_access
from app.services.balance import BALANCE, soft_penalty
from app.services.valuation import hero_power

router = APIRouter(prefix="/battle", tags=["battle"])
settings = get_settings()


async def _progress(db: DbSession, user_id: int, region_id: int) -> RegionProgress | None:
    return (
        await db.execute(
            select(RegionProgress).where(
                RegionProgress.user_id == user_id, RegionProgress.region_id == region_id
            )
        )
    ).scalar_one_or_none()


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
    payload: BattleStartRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    if payload.regionId not in CONFIG.region_by_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地区不存在")

    progress = await _progress(db, user.id, payload.regionId)
    await require_region(db,user.id,hero,items,payload.regionId)
    if progress is not None:
        progress.unlocked = True

    await _end_active_sessions(db, user.id)

    hero.current_region_id = payload.regionId
    hero.region_kill_count = 0  # PRD 地区 6.2：切换地区后计数从 0 开始

    session = BattleSession(user_id=user.id, region_id=payload.regionId, active=True, kill_credit=0.0)
    db.add(session)
    await db.commit()

    region = CONFIG.region_by_id[payload.regionId]
    return {
        "sessionId": session.id,
        "penalty": effective_penalty(compute_stats(hero,items),payload.regionId),
        "regionId": payload.regionId,
        "killsRequired": kills_required(payload.regionId),
        "spawnInterval": spawn_interval(payload.regionId),
        "boss": boss_stats(payload.regionId),
        "region": region,
    }


@router.post("/session/report")
async def report(
    payload: BattleReportRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
) -> dict:
    session = (
        await db.execute(
            select(BattleSession).where(
                BattleSession.id == payload.sessionId,
                BattleSession.user_id == user.id,
                BattleSession.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="战斗会话不存在或已结束")
    if session.region_id != payload.regionId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="地区与会话不一致")

    await require_region(db,user.id,hero,items,payload.regionId)
    stats = compute_stats(hero, items)

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
        stats, payload.regionId, window_ms / 1000.0, settings.report_tolerance, hero.level
    )

    result = validate_report(
        stats=stats,
        region_id=payload.regionId,
        elapsed_ms=window_ms,
        kills=[k.model_dump() for k in payload.kills],
        allowance=allowance,
        tolerance=settings.report_tolerance,
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

    session.kill_credit = max(0.0, allowance - result.consumed_credit)

    rng = random.Random()

    # 金币与经验（服务端重新结算）
    reward_multiplier = effective_penalty(stats,payload.regionId)["rewardMultiplier"]
    result.total_gold = int(result.total_gold * reward_multiplier)
    result.total_exp = int(result.total_exp * reward_multiplier)
    user.gold = int(user.gold) + result.total_gold
    gained_exp = apply_exp_bonus(result.total_exp, stats.term_mods)  # 经验获取效率 Buff
    level_info = apply_exp(hero, gained_exp)

    # 装备：怪物不掉落，仅能通过抽箱获取（BOSS 宝箱见 _settle_boss）
    for kill in result.kills:
        await unlock_monster(db, user.id, kill.monster_id)

    # 技能使用统计
    valid_skills = {s["id"] for s in resolve_job_skills(stats)}
    for cast in payload.skillCasts:
        if cast.skillId not in valid_skills or cast.count <= 0:
            continue
        row = (
            await db.execute(
                select(HeroSkillStat).where(
                    HeroSkillStat.hero_id == hero.id, HeroSkillStat.skill_id == cast.skillId
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = HeroSkillStat(hero_id=hero.id, job_id=stats.job_id, skill_id=cast.skillId, cast_count=0)
            db.add(row)
            await db.flush()
        row.cast_count = int(row.cast_count) + min(cast.count, 10000)

    # 击杀计数（服务端权威）
    required = kills_required(payload.regionId)
    hero.region_kill_count = min(required, int(hero.region_kill_count) + len(result.kills))

    if payload.died:
        hero.region_kill_count = 0  # PRD 地区 3.2：阵亡后小怪击杀计数归零

    boss_result = None
    if payload.bossKilled:
        boss_result = await _settle_boss(db, user, hero, items, payload, rng, stats.term_mods, window_ms)

    session.last_report_at = now
    session.total_kills = int(session.total_kills) + len(result.kills)
    session.total_gold = int(session.total_gold) + result.total_gold
    session.total_exp = int(session.total_exp) + result.total_exp

    await db.commit()

    return {
        "gold": int(user.gold),
        "goldGained": result.total_gold,
        "expGained": gained_exp,
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
) -> dict | None:
    required = kills_required(payload.regionId)
    if int(hero.region_kill_count) < required:
        return None

    progress = await _progress(db, user.id, payload.regionId)
    if progress is None:
        return None

    region = CONFIG.region_by_id[payload.regionId]
    boss_gold = int(roll_gold(payload.regionId, "boss", 0.0, rng) * effective_penalty(compute_stats(hero,items),payload.regionId)["rewardMultiplier"])
    boss_exp = apply_exp_bonus(max(1, int(boss_gold * float(CONFIG.monsters["xpPerGold"]))), term_mods or {})

    user.gold = int(user.gold) + boss_gold
    level_info = apply_exp(hero, boss_exp)
    await unlock_monster(db, user.id, f"boss_r{payload.regionId}")

    box_id = boss_box_for_region(payload.regionId)
    box = chest_by_id(box_id)
    generated = []
    if box:
        luck = rarity_luck(await user_drop_rate(db, user.id))
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
            nxt = await _progress(db, user.id, next_region)
            if nxt and not nxt.unlocked:
                access = await region_access(db,user.id,hero,items)
                nxt.unlocked = not access[next_region]

    hero.region_kill_count = 0

    return {
        "gold": boss_gold,
        "exp": boss_exp,
        "level": level_info,
        "firstClear": first_clear,
        "nextRegionId": payload.regionId + 1 if payload.regionId + 1 in CONFIG.region_by_id else None,
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
