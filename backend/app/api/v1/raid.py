"""高难副本：列表、挑战会话与通关结算。来源：需求「高难副本」

与地区战斗一致的分工：客户端只上报「打完了 / 阵亡了」，奖励与时间下限由服务端裁定。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import RaidProgress, RaidSession
from app.schemas.game import (
    RaidChestClaimRequest,
    RaidReportRequest,
    RaidStartRequest,
    RaidStopRequest,
)
from app.services.drop_luck import chest_rarity_luck
from app.services import consumables
from app.services.egg_heroes import exp_bonus_pct
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item, generate_item_for_slot
from app.services.loot import chest_by_id
from app.services.playtime import MAX_RAID_PLAY_MS, add_play_ms
from app.services.progression import apply_exp, combat_exp, exp_calculation
from app.services.raid_util import (
    all_raids,
    boss_stats_for_raid,
    challenge_level,
    daily_reward_clears,
    eligibility,
    raid_by_id,
    top_rarity_required,
)
from app.services.regions_util import apply_exp_bonus
from app.services.slots_util import selectable_base_slots
from app.services.stats import compute_stats
from app.services.valuation import hero_power

from app.services.balance import BALANCE as RULES
from app.services.raid_balance import snapshot, clear_failures, calibration

router = APIRouter(prefix="/raid", tags=["raid"])

EMPTY_GRANT = {"items": [], "autoSold": [], "autoGold": 0}
# 高难宝箱可自选的装备种类（底材 slot）
CHEST_SLOTS = selectable_base_slots()


async def _pending_chest_count(db: DbSession, user_id: int) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(RaidSession.pending_chest), 0)).where(
            RaidSession.user_id == user_id
        )
    )
    return int(total or 0)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _progress(db: DbSession, user_id: int, raid_id: str) -> RaidProgress | None:
    return (
        await db.execute(
            select(RaidProgress)
            .where(RaidProgress.user_id == user_id, RaidProgress.raid_id == raid_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _end_active_sessions(db: DbSession, user_id: int) -> None:
    rows = (
        await db.execute(
            select(RaidSession).where(RaidSession.user_id == user_id, RaidSession.active.is_(True))
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.active = False
        row.ended_at = now


@router.get("")
async def raid_list(db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    stats = compute_stats(hero, items)
    power = hero_power(stats)
    today = datetime.now(timezone.utc).date()
    rows = (
        await db.execute(select(RaidProgress).where(RaidProgress.user_id == user.id))
    ).scalars().all()
    progress = {row.raid_id: row for row in rows}

    def rewarded_today(row: RaidProgress | None) -> int:
        """当日已获得奖励的通关次数（跨天未重置的旧计数按 0 计）。"""
        if row is None or row.reward_day != today:
            return 0
        return int(row.rewarded_today or 0)

    entries = []
    for raid in all_raids():
        raid = {**raid, **RULES["raids"][raid["id"]]}
        ok, reason = eligibility(raid, hero.level, stats, items)
        row = progress.get(raid["id"])
        entries.append(
            {
                "id": raid["id"],
                "order": raid["order"],
                "difficulty": raid.get("difficulty", "normal"),
                "name": raid["name"],
                "requiredLevel": raid["requiredLevel"],
                "challengeLevel": challenge_level(raid, hero.level),
                "requiredPower": RULES["raids"][raid["id"]]["power"],
                "requiresAllSlots": raid["requiresAllSlots"],
                "minEquipRarity": raid.get("minEquipRarity", "common"),
                "topRarity": raid.get("topRarity"),
                "topRarityCount": top_rarity_required(raid) if raid.get("topRarity") else 0,
                "minAncientTermsPerItem": int(raid.get("minAncientTermsPerItem", 0) or 0),
                "bossNames": [b["name"] for b in raid["bosses"]],
                "dualBoss": len(raid["bosses"]) > 1,
                "reward": raid["reward"],
                "dailyRewardClears": daily_reward_clears(raid),
                "rewardedToday": rewarded_today(row),
                "eligible": ok,
                "blockedReason": reason,
                "cleared": bool(row.cleared) if row else False,
                "clearCount": int(row.clear_count) if row else 0,
                "bestClearMs": row.best_clear_ms if row else None,
            }
        )
    return {
        "raids": entries,
        "level": hero.level,
        "power": power,
        # 待开启的高难宝箱（自选装备种类）
        "chest": {"count": await _pending_chest_count(db, user.id), "slots": CHEST_SLOTS},
    }


@router.post("/session/start")
async def start_session(
    payload: RaidStartRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    raid = raid_by_id(payload.raidId)
    if raid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="副本不存在")

    stats = compute_stats(hero, items)
    ok, reason = eligibility(raid, hero.level, stats, items)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    await _end_active_sessions(db, user.id)
    # 四活动互斥：进入副本即停止进行中的采集/生产/钓鱼
    from app.services.dohdol_util import end_active_sessions as _end_activity

    await _end_activity(db, user.id)
    session = RaidSession(user_id=user.id, hero_id=hero.id, raid_id=raid["id"], active=True, cleared=False)
    session.balance_snapshot = snapshot(raid,hero.level,stats,items)
    previous = await db.scalar(select(func.count(RaidSession.id)).where(RaidSession.user_id==user.id,RaidSession.raid_id==raid['id']))
    session.balance_snapshot = dict(session.balance_snapshot,firstEntry=not previous)
    db.add(session)
    await db.commit()

    return {
        "sessionId": session.id,
        "raidId": raid["id"],
        "name": raid["name"],
        "difficulty": raid.get("difficulty", "normal"),
        "bosses": boss_stats_for_raid(raid, hero.level, stats),
        "penalty": session.balance_snapshot["penalty"],
        "enrage": raid["enrage"],
        "reward": raid["reward"],
    }


@router.post("/session/report")
async def report_session(
    payload: RaidReportRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    raid = raid_by_id(payload.raidId)
    if raid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="副本不存在")

    session = (
        await db.execute(
            select(RaidSession).where(
                RaidSession.id == payload.sessionId,
                RaidSession.hero_id == hero.id,
                RaidSession.user_id == user.id,
                RaidSession.active.is_(True),
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="挑战会话不存在或已结束")
    if session.raid_id != payload.raidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="副本与会话不一致")

    now = datetime.now(timezone.utc)
    server_elapsed_ms = int(max(0.0, (now - _as_utc(session.started_at)).total_seconds() * 1000))
    # 累计在线时长：副本会话可能被长时间挂着，单次计入按上限封顶。
    add_play_ms(user, min(server_elapsed_ms, MAX_RAID_PLAY_MS))

    session.active = False
    session.ended_at = now

    stats = compute_stats(hero, items)
    current = snapshot(raid,hero.level,stats,items)
    fight_ms = int(payload.fightMs if payload.fightMs is not None else server_elapsed_ms)
    failures = clear_failures(session.balance_snapshot,current,server_elapsed_ms,fight_ms) if payload.cleared else []
    if not payload.cleared and current["hard"]:
        failures = [reason for key,reason in [("outputPassed","output"),("defensePassed","defense")] if not current[key]]
    if payload.died: failures.append('defense')
    valid_mechanisms = {s["id"] for b in boss_stats_for_raid(raid,hero.level,stats) for s in b["skills"]}
    reported_mechanisms = sorted(set(payload.mechanismFailures) & valid_mechanisms) if payload.died else []
    session.outcome = dict(mechanismFailures=reported_mechanisms,failures=failures,fightMs=max(0,min(fight_ms,server_elapsed_ms)),firstClear=False)
    if not payload.cleared or failures:
        await db.commit()
        return {
            "cleared": False, "firstClear": False, "gold": int(user.gold), "goldGained": 0,
            "expGained": 0, "items": [], "autoSold": [], "autoGold": 0, "fightMs": fight_ms,
            "failures": failures,
            "message": "练习结束，未满足正式通关条件：" + '、'.join({'entry':'进入门槛','output':'输出检查','defense':'防御检查','invalid_duration':'战斗时长校验','missing_snapshot':'会话版本已失效'}.get(f,f) for f in failures) if failures else "挑战结束，未获得奖励",
        }

    row = await _progress(db, user.id, raid["id"])
    if row is None:
        row = RaidProgress(user_id=user.id, raid_id=raid["id"], cleared=False, clear_count=0)
        db.add(row)
        await db.flush()

    first_clear = not bool(row.cleared)
    reward = raid["reward"]

    # 每日奖励次数：首通计入当天配额；超出后仍记录通关与最快用时，但不再产出奖励（防刷）。
    today = now.date()
    if row.reward_day != today:
        row.reward_day = today
        row.rewarded_today = 0
    daily_limit = daily_reward_clears(raid)
    reward_allowed = first_clear or int(row.rewarded_today or 0) < daily_limit

    gold = 0
    raw_exp = 0
    after_bonus_exp = 0
    exp_gained = 0
    level_info = None
    grant = EMPTY_GRANT
    pending_chest = 0
    if reward_allowed:
        row.rewarded_today = int(row.rewarded_today or 0) + 1

        # 经验/金币加成：与地区结算同源（装备词条 + 药水/食物 + 彩蛋被动）。
        potion_mods = await consumables.exp_gold_mods(db, user.id)
        merged_mods = dict(stats.term_mods)
        for key, value in potion_mods.items():
            merged_mods[key] = merged_mods.get(key, 0.0) + float(value)
        egg_exp = exp_bonus_pct(stats.egg_id)
        if egg_exp:
            merged_mods["expGainPct"] = merged_mods.get("expGainPct", 0.0) + egg_exp

        reward_multiplier = min(
            session.balance_snapshot["penalty"]["rewardMultiplier"],
            current["penalty"]["rewardMultiplier"],
        )
        gold = int(reward["firstGold"]) if first_clear else int(reward["repeatGold"])
        gold = int(gold * reward_multiplier * (1.0 + potion_mods.get("goldGainPct", 0.0) / 100.0))
        user.gold = int(user.gold) + gold

        # 通关经验：首通用 firstExp，重刷用 repeatExp（高难副本的 repeatExp 更高）
        raw_exp = int(reward["firstExp"]) if first_clear else int(reward.get("repeatExp", 0))
        raw_exp = int(raw_exp * reward_multiplier)
        exp_gained = apply_exp_bonus(raw_exp, merged_mods) if raw_exp > 0 else 0
        after_bonus_exp = exp_gained
        exp_gained = await combat_exp(db, hero, exp_gained)
        level_info = apply_exp(hero, exp_gained)

        box_amount = int(reward["boxCount"]) * reward_multiplier
        box_count = int(box_amount) + int(random.random() < box_amount % 1)
        if bool(reward.get("slotChoice")):
            # 高难宝箱：每次通关都掉落，由玩家自选装备种类后在结算界面开启
            session.pending_chest = int(session.pending_chest or 0) + box_count
            pending_chest = int(session.pending_chest)
        elif first_clear:
            chest = chest_by_id(str(reward["chestId"]))
            generated = []
            if chest is not None:
                rng = random.Random()
                luck, _ = await chest_rarity_luck(db, user.id, hero, items)
                for _ in range(box_count):
                    item, _ = generate_item(
                        chest["category"], hero.level, box_tier=chest["tier"], rng=rng, luck=luck
                    )
                    generated.append(item)
            if generated:
                grant = await grant_generated_items(db, user, generated, source=f"raid:{raid['id']}")

    row.cleared = True
    row.cleared_at = row.cleared_at or now
    row.clear_count = int(row.clear_count) + 1
    row.best_clear_ms = fight_ms if row.best_clear_ms is None else min(int(row.best_clear_ms), fight_ms)
    session.cleared = True
    session.outcome = dict(session.outcome, firstClear=first_clear)
    await db.commit()

    remaining_today = max(0, daily_limit - int(row.rewarded_today or 0))
    return {
        "cleared": True,
        "firstClear": first_clear,
        "rewardLimited": not reward_allowed,
        "remainingToday": remaining_today,
        "gold": int(user.gold),
        "goldGained": gold,
        "expGained": exp_gained,
        "expCalculation": exp_calculation(raw_exp, after_bonus_exp, exp_gained),
        "level": level_info,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "fightMs": fight_ms,
        "pendingChest": {"count": pending_chest, "slots": CHEST_SLOTS} if pending_chest else None,
        "message": (
            f"今日奖励次数已用尽（{daily_limit}/{daily_limit}），仍可挑战但不再产出奖励"
            if not reward_allowed
            else "首次通关！" if first_clear else "再次通关"
        ),
    }


@router.post("/chest/claim")
async def claim_chest(
    payload: RaidChestClaimRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
) -> dict:
    """开启高难宝箱：自选装备种类后一次性开出所有待开启的宝箱。"""
    if payload.slot not in CHEST_SLOTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的装备种类")

    sessions = (
        await db.execute(
            select(RaidSession).where(
                RaidSession.user_id == user.id, RaidSession.pending_chest > 0
            )
        )
    ).scalars().all()
    total = sum(int(row.pending_chest or 0) for row in sessions)
    if total <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有待开启的高难宝箱")

    raid = raid_by_id(sessions[0].raid_id)
    box_tier = str((raid or {}).get("reward", {}).get("boxTier", "boss"))
    luck, _ = await chest_rarity_luck(db, user.id, hero, items)
    rng = random.Random()
    generated = [
        generate_item_for_slot(hero.level, payload.slot, box_tier=box_tier, rng=rng, luck=luck)
        for _ in range(total)
    ]
    for row in sessions:
        row.pending_chest = 0

    grant = await grant_generated_items(db, user, generated, source="raid-chest", rng=rng)
    await db.commit()

    return {
        "gold": int(user.gold),
        "count": total,
        "slot": payload.slot,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "pendingChest": await _pending_chest_count(db, user.id),
    }


@router.post("/session/stop")
async def stop_session(payload: RaidStopRequest, db: DbSession, user: CurrentUser) -> dict:
    session = (
        await db.execute(
            select(RaidSession).where(RaidSession.id == payload.sessionId,
                RaidSession.user_id == user.id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="挑战会话不存在")
    session.active = False
    session.ended_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "message": "已退出副本"}


@router.get('/telemetry')
async def raid_telemetry(db: DbSession, user: CurrentUser):
    from app.services.admin import is_admin
    if not is_admin(user):
        raise HTTPException(403,'需要管理员权限')
    rows=(await db.execute(select(RaidSession))).scalars().all()
    return {r['id']: calibration([s for s in rows if s.raid_id == r['id']]) for r in all_raids() if r.get('difficulty') == 'hard'}
