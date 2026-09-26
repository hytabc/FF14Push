"""死者宫殿：run 生命周期 + 局外成长 / 兑换 / 称号。

- 副本内的一切数据（英雄 / 装备 / BUFF / 金币 / 路径）都存 `PalaceRun` 快照，与账号隔离。
- 服务端权威：路径合法性、节点结算、奖励、成长点、代币、兑换全部服务端决定。
- 每账号至多一份 run（`palace_runs.user_id` 唯一）；结束时就地重置为新 run。
"""

from __future__ import annotations

import copy
import random
import time
from typing import Any

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.palace import (
    ENDED,
    STATUS_CHOOSING_HERO,
    STATUS_CHOOSING_WEAPON,
    STATUS_RUNNING,
    PalaceProfile,
    PalaceRun,
)
from app.services import dohdol_util, palace_balance, palace_data, palace_map, palace_stats, titles
from app.services.game_config import CONFIG
from app.services.roster import stop_activities

MAX_NODE_PLAY_MS = 30 * 60 * 1000


def _cfg() -> dict[str, Any]:
    return CONFIG.palace


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------ profile / run
async def get_profile(db: AsyncSession, user_id: int) -> PalaceProfile | None:
    return await db.scalar(select(PalaceProfile).where(PalaceProfile.user_id == user_id))


async def lock_profile(db: AsyncSession, user_id: int) -> PalaceProfile:
    row = await db.scalar(
        select(PalaceProfile)
        .where(PalaceProfile.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        row = PalaceProfile(
            user_id=user_id, growth_points=0, total_growth_earned=0,
            flame_crest=0, glass_pumpkin=0, floor10_clears=0, unlocked=[],
            created_at=_now(), updated_at=_now(),
        )
        db.add(row)
        await db.flush()
    return row


async def active_run(db: AsyncSession, user_id: int) -> PalaceRun | None:
    return await db.scalar(
        select(PalaceRun).where(PalaceRun.user_id == user_id, PalaceRun.status != ENDED)
    )


async def lock_run(db: AsyncSession, user_id: int) -> PalaceRun:
    row = await db.scalar(
        select(PalaceRun)
        .where(PalaceRun.user_id == user_id, PalaceRun.status != ENDED)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="没有进行中的死者宫殿")
    return row


def profile_view(profile: PalaceProfile | None) -> dict[str, Any]:
    if profile is None:
        return {
            "growthPoints": 0, "totalGrowthEarned": 0,
            "flameCrest": 0, "glassPumpkin": 0, "floor10Clears": 0,
        }
    return {
        "growthPoints": int(profile.growth_points or 0),
        "totalGrowthEarned": int(profile.total_growth_earned or 0),
        "flameCrest": int(profile.flame_crest or 0),
        "glassPumpkin": int(profile.glass_pumpkin or 0),
        "floor10Clears": int(profile.floor10_clears or 0),
    }


def config_view() -> dict[str, Any]:
    cfg = _cfg()
    return {
        "floors": int(cfg["floors"]),
        "stepsPerFloor": int(cfg["stepsPerFloor"]),
        "levelCap": int(cfg["levelCap"]),
        "revives": int(cfg["revives"]),
        "heroCandidates": int(cfg["heroCandidates"]),
        "weaponCandidates": int(cfg["weaponCandidates"]),
        "rewardChoices": int(cfg["rewardChoices"]),
        "bossReward": cfg["bossReward"],
    }


def _current_stats(run: PalaceRun, profile: PalaceProfile):
    if not run.hero:
        return None
    return palace_stats.compute_run_stats(
        run.hero, run.items, run.equipped, profile.unlocked, run.buffs
    )


def _available_nodes(run: PalaceRun) -> list[str]:
    if run.status != STATUS_RUNNING or not run.map:
        return []
    if run.pending_reward:
        return []
    pending = run.pending_node or {}
    if pending.get("type") in ("battle", "elite", "boss", "event"):
        return []
    return palace_map.next_ids(run.map, run.current_node)


def run_view(run: PalaceRun | None, profile: PalaceProfile | None) -> dict[str, Any] | None:
    if run is None:
        return None
    stats = _current_stats(run, profile) if profile is not None else None
    hero = run.hero
    next_level_exp = None
    if hero:
        next_level_exp = palace_data.exp_to_next(int(hero.get("level", 1)))
    return {
        "runId": int(run.id),
        "status": run.status,
        "endedReason": run.ended_reason,
        "floor": int(run.floor),
        "step": int(run.step),
        "floors": palace_data.floors(),
        "stepsPerFloor": palace_map.steps_per_floor(),
        "levelCap": palace_data.level_cap(),
        "gold": int(run.run_gold or 0),
        "reviveLeft": int(run.revive_left or 0),
        "hero": hero,
        "heroCandidates": run.hero_candidates,
        "weaponCandidates": run.weapon_candidates,
        "items": list(run.items or []),
        "equipped": dict(run.equipped or {}),
        "buffs": list(run.buffs or []),
        "stats": stats.to_dict() if stats is not None else None,
        "map": run.map,
        "currentNode": run.current_node,
        "availableNodes": _available_nodes(run),
        "pendingReward": run.pending_reward,
        "pendingNode": run.pending_node,
        "nextLevelExp": next_level_exp,
    }


# ------------------------------------------------------------------ 入口 / 开局
async def state(db: AsyncSession, user: User) -> dict[str, Any]:
    profile = await get_profile(db, user.id)
    run = await active_run(db, user.id)
    return {
        "config": config_view(),
        "profile": profile_view(profile),
        "run": run_view(run, profile),
    }


async def start(db: AsyncSession, user: User) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    existing = await active_run(db, user.id)
    if existing is not None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="已有进行中的死者宫殿")

    await stop_activities(db, user.id)
    await dohdol_util.end_active_sessions(db, user.id)

    _, add = palace_stats.growth_mods(profile.unlocked)
    rng = random.Random()
    candidates = palace_data.hero_candidates(
        add.get("heroTalentWeight", 0.0), int(_cfg()["heroCandidates"]), rng
    )

    run = await db.scalar(select(PalaceRun).where(PalaceRun.user_id == user.id))
    if run is None:
        run = PalaceRun(user_id=user.id, created_at=_now())
        db.add(run)
    run.status = STATUS_CHOOSING_HERO
    run.ended_reason = None
    run.floor = 1
    run.step = 1
    run.hero = None
    run.hero_candidates = candidates
    run.weapon_candidates = None
    run.map = None
    run.current_node = None
    run.items = []
    run.equipped = {}
    run.buffs = []
    run.run_gold = int(add.get("startGold", 0.0))
    run.pending_reward = None
    run.pending_node = None
    run.revive_left = palace_data.revives() + int(round(add.get("reviveCount", 0.0)))
    run.snapshot = None
    run.node_started_at = None
    run.updated_at = _now()
    await db.flush()
    return {"profile": profile_view(profile), "run": run_view(run, profile)}


async def choose_hero(db: AsyncSession, user: User, index: int) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    if run.status != STATUS_CHOOSING_HERO:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="当前状态无法选择英雄")
    candidates = run.hero_candidates or []
    if not 0 <= index < len(candidates):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="候选不存在")

    _, add = palace_stats.growth_mods(profile.unlocked)
    start_level = 1 + int(round(add.get("startLevel", 0.0)))
    run.hero = palace_data.hero_snapshot(candidates[index], start_level)

    rng = random.Random()
    equip_level_bonus = int(round(add.get("equipLevel", 0.0)))
    luck = float(add.get("equipQualityWeight", 0.0))
    quality = min(0.5, float(add.get("dropQualityWeight", 0.0)))
    weapon_level = palace_data.item_level(1, equip_level_bonus)
    run.weapon_candidates = [
        palace_data.generate_item("weapon", weapon_level, rng, luck=luck, quality_bonus=quality)
        for _ in range(int(_cfg()["weaponCandidates"]))
    ]
    run.status = STATUS_CHOOSING_WEAPON
    run.updated_at = _now()
    await db.flush()
    return {"run": run_view(run, profile)}


async def choose_weapon(db: AsyncSession, user: User, index: int) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    if run.status != STATUS_CHOOSING_WEAPON:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="当前状态无法选择武器")
    candidates = run.weapon_candidates or []
    if not 0 <= index < len(candidates):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="候选不存在")

    weapon = candidates[index]
    run.items = [weapon]
    run.equipped = {weapon["slot"]: 0}

    _, add = palace_stats.growth_mods(profile.unlocked)
    start_buffs = int(round(add.get("startBuffCount", 0.0)))
    rng = random.Random()
    if start_buffs > 0:
        run.buffs = [
            {"id": b["id"], "name": b["name"], "stat": b["stat"], "value": b["value"], "desc": b["desc"]}
            for b in (palace_data.pick_buff(rng) for _ in range(start_buffs))
        ]

    run.map = palace_map.generate_map(1, rng)
    run.current_node = None
    run.step = 1
    run.status = STATUS_RUNNING
    run.weapon_candidates = None
    run.hero_candidates = None
    run.updated_at = _now()
    await db.flush()
    return {"run": run_view(run, profile)}


# ------------------------------------------------------------------ 节点
def _resolve_node(run: PalaceRun, node_id: str) -> None:
    run.current_node = node_id
    step = palace_map.node_step(run.map, node_id)
    if step is not None:
        run.step = step
    run.pending_node = None
    run.snapshot = None
    run.node_started_at = None


def _pick_event(floor: int, rng: random.Random) -> dict[str, Any]:
    pool = [
        e for e in CONFIG.palace_events["events"]
        if int(e["floorRange"][0]) <= floor <= int(e["floorRange"][1])
    ] or list(CONFIG.palace_events["events"])
    weights = [max(0.0, float(e.get("weight", 1))) for e in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


async def enter_node(db: AsyncSession, user: User, node_id: str) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    if run.status != STATUS_RUNNING:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="当前状态无法进入节点")
    if run.pending_reward:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="请先领取战斗奖励")

    allowed = palace_map.next_ids(run.map, run.current_node)
    if node_id not in allowed:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="非法路径")
    node = palace_map.find_node(run.map, node_id)
    if node is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="节点不存在")

    ntype = str(node["type"])
    step = palace_map.node_step(run.map, node_id)
    rng = random.Random()
    context: dict[str, Any] = {"nodeId": node_id, "type": ntype, "step": step}
    run.pending_node = None  # 进入新节点即离开上一个非战斗节点（商店等）

    if ntype in palace_map.BATTLE_TYPES:
        enemy = palace_data.enemy_stats(run.floor, ntype, rng)
        stats = palace_stats.compute_run_stats(
            run.hero, run.items, run.equipped, profile.unlocked, run.buffs
        )
        run.snapshot = palace_balance.snapshot(stats, enemy)
        run.node_started_at = _now()
        run.pending_node = {"nodeId": node_id, "type": ntype, "enemy": enemy}
        context["enemy"] = enemy
    elif ntype == "event":
        event = _pick_event(run.floor, rng)
        run.current_node = node_id
        if step is not None:
            run.step = step
        run.pending_node = {"nodeId": node_id, "type": "event", "eventId": event["id"]}
        context["event"] = {
            "id": event["id"], "name": event["name"], "desc": event["desc"],
            "choices": [{"label": c["label"]} for c in event["choices"]],
        }
    elif ntype == "shop":
        _, add = palace_stats.growth_mods(profile.unlocked)
        offers = palace_data.shop_offers(run.floor, rng, add.get("shopDiscount", 0.0))
        run.current_node = node_id
        if step is not None:
            run.step = step
        run.pending_node = {"nodeId": node_id, "type": "shop", "offers": offers}
        context["shop"] = {"offers": offers}
    elif ntype == "chest":
        result = _grant_chest(run, profile, rng)
        _resolve_node(run, node_id)
        context["result"] = result
    elif ntype == "rest":
        result = _rest(run, rng)
        _resolve_node(run, node_id)
        context["result"] = result

    run.updated_at = _now()
    await db.flush()
    return {"run": run_view(run, profile), "context": context}


def _grant_chest(run: PalaceRun, profile: PalaceProfile, rng: random.Random) -> dict[str, Any]:
    _, add = palace_stats.growth_mods(profile.unlocked)
    gold_gain = 1.0 + float(add.get("goldGainPct", 0.0)) / 100.0
    row = palace_data.floor_row(run.floor)
    gold = int(float(row["gold"]) * rng.uniform(1.0, 2.5) * gold_gain)
    run.run_gold = int(run.run_gold or 0) + gold
    equip = palace_data.random_equip(
        rng, run.floor, int(round(add.get("equipLevel", 0.0))),
        float(add.get("equipQualityWeight", 0.0)), min(0.5, float(add.get("dropQualityWeight", 0.0))),
    )
    run.items = [*(run.items or []), equip]
    return {"kind": "chest", "gold": gold, "equip": equip}


def _rest(run: PalaceRun, rng: random.Random) -> dict[str, Any]:
    return {"kind": "rest", "healed": 1.0, "desc": "休整完毕，恢复全部状态"}


async def clear_node(
    db: AsyncSession, user: User, node_id: str, elapsed_ms: int, result: str
) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    pending = run.pending_node or {}
    if pending.get("nodeId") != node_id or pending.get("type") not in palace_map.BATTLE_TYPES:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="没有待结算的战斗节点")

    if result != "win":
        return await _handle_death(run, profile, db, user)

    started = run.node_started_at or _now()
    server_ms = int(max(0.0, (_now() - started) * 1000))
    failures = palace_balance.clear_failures(run.snapshot, server_ms, int(elapsed_ms or 0))
    if "invalid_duration" in failures:
        # 客户端据此等待重试（不结束 run）。
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="战斗时长异常")

    ntype = str(pending["type"])
    _, add = palace_stats.growth_mods(profile.unlocked)
    rng = random.Random()

    options = palace_data.reward_options(
        run.floor, ntype, rng,
        equip_level_bonus=int(round(add.get("equipLevel", 0.0))),
        quality_bonus=min(0.5, float(add.get("dropQualityWeight", 0.0))),
        rarity_luck=float(add.get("equipQualityWeight", 0.0)),
        drop_count_pct=float(add.get("dropCountPct", 0.0)),
    )
    run.pending_reward = options

    xp, gold = palace_data.enemy_rewards(run.floor, ntype)
    gold = int(gold * (1.0 + float(add.get("goldGainPct", 0.0)) / 100.0))
    run.run_gold = int(run.run_gold or 0) + gold
    hero = dict(run.hero or {})
    level_info = _gain_exp(hero, xp)
    run.hero = hero
    _resolve_node(run, node_id)

    boss_reward = None
    if ntype == "boss":
        boss_reward = await _settle_boss(db, user, run, profile)

    run.updated_at = _now()
    await db.flush()
    return {
        "run": run_view(run, profile),
        "profile": profile_view(profile),
        "gold": gold,
        "exp": xp,
        "level": level_info,
        "bossReward": boss_reward,
    }


def _gain_exp(hero: dict[str, Any] | None, amount: int) -> dict[str, int] | None:
    if not hero:
        return None
    cap = palace_data.level_cap()
    hero["exp"] = int(hero.get("exp", 0)) + max(0, int(amount))
    gained = 0
    while int(hero["level"]) < cap:
        need = palace_data.exp_to_next(int(hero["level"]))
        if int(hero["exp"]) < need:
            break
        hero["exp"] = int(hero["exp"]) - need
        hero["level"] = int(hero["level"]) + 1
        gained += 1
    if int(hero["level"]) >= cap:
        hero["exp"] = 0
    return {"levelsGained": gained, "level": int(hero["level"]), "exp": int(hero["exp"])}


async def _settle_boss(
    db: AsyncSession, user: User, run: PalaceRun, profile: PalaceProfile
) -> dict[str, Any]:
    floor = int(run.floor)
    cfg = _cfg()["bossReward"]
    index = min(len(cfg["growthPoints"]), max(1, floor)) - 1
    _, add = palace_stats.growth_mods(profile.unlocked)
    growth_mult = (1.0 + float(add.get("bossGrowthPct", 0.0))) * (
        1.0 + float(add.get("growthGainPct", 0.0))
    )
    points = int(round(float(cfg["growthPoints"][index]) * growth_mult))
    clear_bonus = 0
    if floor >= palace_data.floors():
        clear_bonus = int(round(float(cfg["clearBonusGrowthPoints"]) * growth_mult))
    total_points = points + clear_bonus
    flame = int(cfg["flameCrest"][index])
    pumpkin = int(cfg["glassPumpkin"][index])

    profile.growth_points = int(profile.growth_points or 0) + total_points
    profile.total_growth_earned = int(profile.total_growth_earned or 0) + total_points
    profile.flame_crest = int(profile.flame_crest or 0) + flame
    profile.glass_pumpkin = int(profile.glass_pumpkin or 0) + pumpkin

    new_titles: list[str] = []
    completed = floor >= palace_data.floors()
    if completed:
        profile.floor10_clears = int(profile.floor10_clears or 0) + 1
        new_titles = await titles.evaluate_palace_titles(db, user.id)

    if completed:
        run.status = ENDED
        run.ended_reason = "completed"
    else:
        rng = random.Random()
        run.floor = floor + 1
        run.step = 1
        run.map = palace_map.generate_map(run.floor, rng)
        run.current_node = None
    profile.updated_at = _now()

    return {
        "floor": floor,
        "growthPoints": total_points,
        "flameCrest": flame,
        "glassPumpkin": pumpkin,
        "completed": completed,
        "newTitles": new_titles,
    }


async def _handle_death(
    db: AsyncSession, user: User, run: PalaceRun, profile: PalaceProfile
) -> dict[str, Any]:
    if int(run.revive_left or 0) > 0:
        run.revive_left = int(run.revive_left) - 1
        run.snapshot = None
        run.node_started_at = None
        run.updated_at = _now()
        await db.flush()
        return {"revived": True, "run": run_view(run, profile)}
    run.status = ENDED
    run.ended_reason = "death"
    run.pending_node = None
    run.pending_reward = None
    run.snapshot = None
    run.node_started_at = None
    run.updated_at = _now()
    await db.flush()
    return {"revived": False, "run": run_view(run, profile)}


async def claim_reward(db: AsyncSession, user: User, index: int) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    options = run.pending_reward or []
    if not options:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="没有待领奖励")
    if not 0 <= index < len(options):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="奖励不存在")

    option = options[index]
    granted: dict[str, Any] = {"kind": option.get("kind")}
    if option.get("equip"):
        run.items = [*(run.items or []), option["equip"]]
        granted["equip"] = option["equip"]
    if option.get("buff"):
        buff = option["buff"]
        run.buffs = [
            *(run.buffs or []),
            {"id": buff["id"], "name": buff["name"], "stat": buff["stat"],
             "value": buff["value"], "desc": buff["desc"]},
        ]
        granted["buff"] = buff
    run.pending_reward = None
    run.updated_at = _now()
    await db.flush()
    return {"granted": granted, "run": run_view(run, profile)}


async def event_choose(db: AsyncSession, user: User, node_id: str, choice_index: int) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    pending = run.pending_node or {}
    if pending.get("nodeId") != node_id or pending.get("type") != "event":
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="没有待处理的事件")
    event = CONFIG.palace_event_by_id.get(str(pending.get("eventId")))
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="事件不存在")
    choices = event["choices"]
    if not 0 <= choice_index < len(choices):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="选项不存在")

    rng = random.Random()
    results = _apply_effects(run, profile, choices[choice_index].get("effects") or [], rng)
    _resolve_node(run, node_id)
    run.updated_at = _now()
    await db.flush()
    return {"results": results, "run": run_view(run, profile), "profile": profile_view(profile)}


def _apply_effects(
    run: PalaceRun, profile: PalaceProfile, effects: list[dict[str, Any]], rng: random.Random
) -> list[dict[str, Any]]:
    _, add = palace_stats.growth_mods(profile.unlocked)
    results: list[dict[str, Any]] = []
    for effect in effects:
        kind = str(effect.get("kind"))
        value = float(effect.get("value", 0.0))
        if kind == "grant_gold":
            amount = int(value * (1.0 + float(add.get("goldGainPct", 0.0)) / 100.0))
            run.run_gold = int(run.run_gold or 0) + amount
            results.append({"kind": "gold", "amount": amount})
        elif kind == "lose_gold":
            run.run_gold = max(0, int(run.run_gold or 0) - int(value))
            results.append({"kind": "loseGold"})
        elif kind == "lose_hp":
            results.append({"kind": "loseHp", "value": value})
        elif kind == "heal":
            results.append({"kind": "heal", "value": value})
        elif kind == "grant_equip":
            equip = palace_data.random_equip(
                rng, run.floor, int(round(add.get("equipLevel", 0.0))),
                float(add.get("equipQualityWeight", 0.0)), min(0.5, float(add.get("dropQualityWeight", 0.0))),
            )
            run.items = [*(run.items or []), equip]
            results.append({"kind": "equip", "equip": equip})
        elif kind == "grant_buff":
            buff = palace_data.pick_buff(rng)
            run.buffs = [
                *(run.buffs or []),
                {"id": buff["id"], "name": buff["name"], "stat": buff["stat"],
                 "value": buff["value"], "desc": buff["desc"]},
            ]
            results.append({"kind": "buff", "buff": buff})
        elif kind == "hero_attr_up":
            attr = str(effect.get("attr", ""))
            key = {"str": "strength", "dex": "agility", "int": "intellect"}.get(attr)
            if run.hero and key:
                hero = dict(run.hero)
                hero[key] = int(hero.get(key, 1)) + int(value)
                run.hero = hero
                results.append({"kind": "attr", "attr": attr, "value": int(value)})
        elif kind == "equip_rarity_up":
            upgraded = _upgrade_rarity(run, str(effect.get("target", "random")))
            results.append({"kind": "rarityUp", "upgraded": upgraded})
        elif kind == "equip_level_up":
            upgraded = _upgrade_level(run, str(effect.get("target", "random")))
            results.append({"kind": "levelUp", "upgraded": upgraded})
        elif kind == "skill_effect_up":
            # 技能效果提升：折算为一条通用伤害加成 BUFF，随 run 持久生效。
            from app.services.palace_data import cfg as _pcfg
            buff = {"id": "pb_skill_up", "name": "技艺精进", "stat": "attackPct",
                    "value": round(value * 100, 2), "desc": f"攻击力 +{round(value * 100, 1)}%"}
            run.buffs = [*(run.buffs or []), buff]
            results.append({"kind": "skillUp", "buff": buff})
        elif kind == "grant_exp":
            if run.hero:
                hero = dict(run.hero)
                amount = int(palace_data.exp_to_next(int(hero["level"])) * value)
                info = _gain_exp(hero, amount)
                run.hero = hero
                results.append({"kind": "exp", "level": info})
        elif kind == "grant_revive":
            run.revive_left = int(run.revive_left or 0) + int(value)
            results.append({"kind": "revive", "value": int(value)})
        elif kind == "gain_growth":
            points = int(value)
            profile.growth_points = int(profile.growth_points or 0) + points
            profile.total_growth_earned = int(profile.total_growth_earned or 0) + points
            results.append({"kind": "growth", "points": points})
        elif kind == "curse":
            stat = str(effect.get("stat", "attackPct"))
            run.buffs = [
                *(run.buffs or []),
                {"id": f"curse_{stat}", "name": "诅咒", "stat": stat, "value": value, "desc": "被诅咒"},
            ]
            results.append({"kind": "curse", "stat": stat, "value": value})
        elif kind == "chance":
            won = rng.random() < float(effect.get("p", 0.5))
            branch = effect.get("onWin") if won else effect.get("onLose")
            results.append({"kind": "chance", "won": won,
                            "results": _apply_effects(run, profile, branch or [], rng)})
    return results


_RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary", "mythic")


def _upgrade_rarity(run: PalaceRun, target: str) -> dict[str, Any] | None:
    items = copy.deepcopy(run.items or [])
    pool = [(i, it) for i, it in enumerate(items) if target == "random" or it["category"] == target]
    if not pool:
        return None
    idx, item = pool[len(pool) // 2]
    rank = _RARITY_ORDER.index(item["rarity"]) if item["rarity"] in _RARITY_ORDER else 0
    if rank >= len(_RARITY_ORDER) - 1:
        return None
    item["rarity"] = _RARITY_ORDER[rank + 1]
    run.items = items
    return {"name": item["name"], "rarity": item["rarity"]}


def _upgrade_level(run: PalaceRun, target: str) -> dict[str, Any] | None:
    items = copy.deepcopy(run.items or [])
    pool = [(i, it) for i, it in enumerate(items) if target == "random" or it["category"] == target]
    if not pool:
        return None
    idx, item = pool[len(pool) // 2]
    item["levelReq"] = min(100, int(item["levelReq"]) + 10)
    run.items = items
    return {"name": item["name"], "levelReq": item["levelReq"]}


async def shop_buy(db: AsyncSession, user: User, node_id: str, offer_index: int) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    pending = run.pending_node or {}
    if pending.get("nodeId") != node_id or pending.get("type") != "shop":
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="没有进行中的商店")
    offers = copy.deepcopy(pending.get("offers") or [])
    if not 0 <= offer_index < len(offers):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="商品不存在")
    offer = offers[offer_index]
    if offer.get("sold"):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="商品已售出")
    price = int(offer["price"])
    if int(run.run_gold or 0) < price:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="副本金币不足")

    run.run_gold = int(run.run_gold or 0) - price
    kind = str(offer["kind"])
    granted: dict[str, Any] = {"kind": kind}
    rng = random.Random()
    if kind == "grant_buff" and offer.get("buffId"):
        buff = CONFIG.palace_buff_by_id.get(offer["buffId"])
        if buff:
            run.buffs = [
                *(run.buffs or []),
                {"id": buff["id"], "name": buff["name"], "stat": buff["stat"],
                 "value": buff["value"], "desc": buff["desc"]},
            ]
            granted["buff"] = buff
    elif kind == "heal":
        granted["heal"] = float(offer.get("value", 0.4))
    elif kind == "grant_equip":
        _, add = palace_stats.growth_mods(profile.unlocked)
        equip = palace_data.random_equip(
            rng, run.floor, int(round(add.get("equipLevel", 0.0))),
            float(add.get("equipQualityWeight", 0.0)), min(0.5, float(add.get("dropQualityWeight", 0.0))),
        )
        run.items = [*(run.items or []), equip]
        granted["equip"] = equip

    offer["sold"] = True
    run.pending_node = {**pending, "offers": offers}
    run.updated_at = _now()
    await db.flush()
    return {"granted": granted, "run": run_view(run, profile)}


async def equip_item(db: AsyncSession, user: User, index: int) -> dict[str, Any]:
    """穿戴副本背包里的某件装备（按栏位覆盖）。"""
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    items = run.items or []
    if not 0 <= index < len(items):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="装备不存在")
    item = items[index]
    equipped = dict(run.equipped or {})
    equipped[item["slot"]] = index
    run.equipped = equipped
    run.updated_at = _now()
    await db.flush()
    return {"run": run_view(run, profile)}


async def abandon(db: AsyncSession, user: User) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    run = await lock_run(db, user.id)
    run.status = ENDED
    run.ended_reason = "abandoned"
    run.pending_node = None
    run.pending_reward = None
    run.updated_at = _now()
    await db.flush()
    return {"run": run_view(run, profile)}


# ------------------------------------------------------------------ 局外成长
def growth_view(profile: PalaceProfile | None) -> dict[str, Any]:
    points = int(profile.growth_points or 0) if profile else 0
    unlocked = set(profile.unlocked or []) if profile else set()
    categories = []
    for category in CONFIG.palace_growth["categories"]:
        nodes = []
        for node in category["nodes"]:
            req = node.get("requires")
            prereq_ok = req is None or req in unlocked
            is_unlocked = node["id"] in unlocked
            nodes.append({
                **node,
                "unlocked": is_unlocked,
                "available": prereq_ok and not is_unlocked,
                "affordable": prereq_ok and int(node["cost"]) <= points,
            })
        categories.append({"id": category["id"], "name": category["name"],
                           "desc": category["desc"], "nodes": nodes})
    return {"points": points, "totalEarned": int(profile.total_growth_earned or 0) if profile else 0,
            "categories": categories}


async def unlock_growth(db: AsyncSession, user: User, node_id: str) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    node = CONFIG.palace_growth_by_id.get(node_id)
    if node is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="成长节点不存在")
    unlocked = set(profile.unlocked or [])
    if node_id in unlocked:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="该成长已解锁")
    req = node.get("requires")
    if req and req not in unlocked:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="需先解锁前置成长")
    cost = int(node["cost"])
    if int(profile.growth_points or 0) < cost:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=f"成长点不足，需要 {cost}")
    profile.growth_points = int(profile.growth_points or 0) - cost
    profile.unlocked = sorted(unlocked | {node_id})
    profile.updated_at = _now()
    await db.flush()
    return {"unlocked": node_id, "view": growth_view(profile)}


# ------------------------------------------------------------------ 兑换
def exchange_view(profile: PalaceProfile | None) -> dict[str, Any]:
    flame = int(profile.flame_crest or 0) if profile else 0
    pumpkin = int(profile.glass_pumpkin or 0) if profile else 0
    entries = []
    for entry in _cfg()["exchange"]:
        cost = entry["cost"]
        entries.append({
            "id": entry["id"],
            "name": entry["name"],
            "cost": cost,
            "affordable": flame >= int(cost["flameCrest"]) and pumpkin >= int(cost["glassPumpkin"]),
        })
    return {"flameCrest": flame, "glassPumpkin": pumpkin, "entries": entries}


def _consumable_tier(item_id: str) -> int:
    return int(item_id[-1]) if item_id and item_id[-1].isdigit() else 1


async def _grant_exchange(
    db: AsyncSession, user_id: int, grant: dict[str, Any], multiplier: int, rng: random.Random
) -> list[dict[str, Any]]:
    kind = str(grant.get("kind"))
    count = max(1, int(grant.get("count", 1))) * multiplier
    results: list[dict[str, Any]] = []
    if kind == "stack":
        item_id = str(grant["itemId"])
        if item_id in CONFIG.seed_by_id:
            stack_kind = dohdol_util.STACK_SEED
        elif item_id == "recraft_card":
            stack_kind = dohdol_util.STACK_CARD
        else:
            stack_kind = dohdol_util.STACK_MATERIAL
        await dohdol_util.stack_add(db, user_id, stack_kind, item_id, count)
        results.append({"kind": "stack", "itemId": item_id, "count": count,
                        "name": dohdol_util.material_name(item_id)})
    elif kind == "materia":
        level = int(grant.get("level", 5))
        pool = [m for m in CONFIG.materia_by_id.values() if int(m["level"]) == level]
        for _ in range(count):
            materia = rng.choice(pool)
            await dohdol_util.stack_add(db, user_id, dohdol_util.STACK_MATERIA, materia["id"], 1)
            results.append({"kind": "materia", "itemId": materia["id"], "count": 1,
                            "name": materia["name"]})
    elif kind == "random_consumable":
        consumable_kind = str(grant.get("consumableKind", "potion"))
        tier = int(grant.get("tier", 1))
        pool = [
            c for c in CONFIG.consumables["items"]
            if c["kind"] == consumable_kind and _consumable_tier(c["id"]) == tier
        ]
        for _ in range(count):
            item = rng.choice(pool)
            stack_kind = dohdol_util.STACK_POTION if consumable_kind == "potion" else dohdol_util.STACK_FOOD
            await dohdol_util.stack_add(db, user_id, stack_kind, item["id"], 1)
            results.append({"kind": "consumable", "itemId": item["id"], "count": 1, "name": item["name"]})
    return results


async def exchange(
    db: AsyncSession, user: User, exchange_id: str, count: int
) -> dict[str, Any]:
    profile = await lock_profile(db, user.id)
    entry = CONFIG.palace_exchange_by_id.get(exchange_id)
    if entry is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="兑换项不存在")
    multiplier = max(1, min(999, int(count or 1)))
    cost = entry["cost"]
    need_flame = int(cost["flameCrest"]) * multiplier
    need_pumpkin = int(cost["glassPumpkin"]) * multiplier
    if int(profile.flame_crest or 0) < need_flame or int(profile.glass_pumpkin or 0) < need_pumpkin:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="代币不足")
    profile.flame_crest = int(profile.flame_crest or 0) - need_flame
    profile.glass_pumpkin = int(profile.glass_pumpkin or 0) - need_pumpkin
    profile.updated_at = _now()
    rng = random.Random()
    granted = await _grant_exchange(db, user.id, entry["grant"], multiplier, rng)
    await db.flush()
    return {"granted": granted, "view": exchange_view(profile)}
