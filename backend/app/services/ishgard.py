"""重建伊修加德：全服共享进度的生活玩法。

设计要点：
- **全服阶段进度 + 轮次（赛季）**：提交积分汇入 `IshgardState.stage_points`，达到阈值即推进阶段；
  5 个阶段全部达成后 `round+1`、阶段回到 1；个人累计积分 / 主手装备 / 称号记录跨轮次保留。
- **阶段锁定**：采集 / 钓鱼 / 生产 / 提交全部只在「当前阶段」的物资上生效，跨阶段请求一律拒绝；
  过期物资可出售给系统（避免死库存）。
- **服务端权威**：窗口只取服务端时钟（复用 `dohdol_util.window_seconds`），单次上报动作数封顶。
- **独立积分榜**：按个人累计总积分排序，不并入总排行榜。
- **周期称号**：每 6H 按累计积分结算「天穹圣人 / 天穹圣徒」，全服唯一、严格超越才转移。
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivitySession,
    DohDolProgress,
    IshgardContribution,
    IshgardMember,
    IshgardState,
    IshgardTool,
    Item,
    StackItem,
    User,
    UserTitle,
)
from app.services import consumables, dohdol_util
from app.services.admin import is_admin
from app.services.game_config import CONFIG
from app.services.item_factory import roll_dedicated_terms
from app.services.locks import release_advisory_lock, try_advisory_lock
from app.services.playtime import add_play_ms

# 专属堆叠种类：材料 / 鱼 / 产物共用，靠 id 前缀区分阶段。
ISHGARD_STACK = "ishgard"

KIND_GATHER = "ish_gather"
KIND_FISH = "ish_fish"
KIND_PRODUCE = "ish_produce"

MAX_ACTIONS_PER_REPORT = 200
TITLE_LOCK_KEY = "eorzea:ishgard_titles"
# 标题窗口与「严格超越」并列时的稳定排序依据。
_DEFAULT_ROUND = 1


# ------------------------------------------------------------------ 配置查询
def _cfg() -> dict[str, Any]:
    return CONFIG.ishgard


def title_window() -> float:
    return float(_cfg()["titleWindowSeconds"])


def saint_title_id() -> str:
    return str(_cfg()["titleIds"]["saint"])


def apostle_title_id() -> str:
    return str(_cfg()["titleIds"]["apostle"])


def stage_targets() -> list[int]:
    return [int(t) for t in _cfg()["stageTargets"]]


def stage_count() -> int:
    return len(stage_targets())


def stage_def(stage: int) -> dict[str, Any]:
    stages = _cfg()["stages"]
    index = max(0, min(int(stage) - 1, len(stages) - 1))
    return stages[index]


def target_for(stage: int) -> int:
    targets = stage_targets()
    return targets[max(0, min(int(stage) - 1, len(targets) - 1))]


def display_name(stage: int, base_name: str) -> str:
    return str(_cfg()["naming"]["template"]).format(stage=int(stage), name=base_name)


def product_def(item_id: str) -> dict[str, Any] | None:
    return CONFIG.ishgard_product_by_id.get(item_id)


def material_def(item_id: str) -> dict[str, Any] | None:
    return CONFIG.ishgard_material_by_id.get(item_id)


def fish_def(item_id: str) -> dict[str, Any] | None:
    return CONFIG.ishgard_fish_by_id.get(item_id)


def item_stage(item_id: str) -> int | None:
    spec = dohdol_util.ishgard_item_def(item_id)
    return int(spec["stage"]) if spec else None


def item_sell(item_id: str) -> int:
    spec = dohdol_util.ishgard_item_def(item_id)
    return int(spec.get("sell", 0)) if spec else 0


def tool_slot(kind: str) -> str:
    return str(_cfg()["tools"][kind]["slot"])


def tool_levels(kind: str) -> list[dict[str, Any]]:
    return list(_cfg()["tools"][kind]["levels"])


def tool_level_spec(kind: str, level: int) -> dict[str, Any] | None:
    for spec in tool_levels(kind):
        if int(spec["level"]) == int(level):
            return spec
    return None


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------ 全局状态
async def _select_state(db: AsyncSession) -> IshgardState | None:
    return await db.get(IshgardState, 1)


async def get_state(db: AsyncSession) -> IshgardState:
    """幂等取回全局单行（并发下用 savepoint 兜底）。"""
    state = await _select_state(db)
    if state is not None:
        return state
    now = _now()
    try:
        async with db.begin_nested():
            state = IshgardState(
                id=1,
                round=_DEFAULT_ROUND,
                stage=1,
                stage_points=0,
                stage_target=target_for(1),
                title_period_ends_at=now + title_window(),
                updated_at=now,
            )
            db.add(state)
    except IntegrityError:
        state = await _select_state(db)
        if state is None:
            raise
    return state


def advance_stage(state: IshgardState) -> list[int]:
    """按累计积分推进阶段（允许跨多段）；跨过最后一阶段则开启新一轮。

    返回本轮推进过程中「已完成」的阶段号列表（供前端提示）。
    """
    completed: list[int] = []
    targets = stage_targets()
    while int(state.stage) <= len(targets) and int(state.stage_points) >= targets[int(state.stage) - 1]:
        state.stage_points = int(state.stage_points) - targets[int(state.stage) - 1]
        completed.append(int(state.stage))
        state.stage = int(state.stage) + 1
        if int(state.stage) > len(targets):
            state.round = int(state.round) + 1
            state.stage = 1
            state.stage_points = 0
            break
    state.stage_target = target_for(int(state.stage))
    return completed


async def _member(db: AsyncSession, user_id: int) -> IshgardMember | None:
    return (
        await db.execute(select(IshgardMember).where(IshgardMember.user_id == user_id))
    ).scalar_one_or_none()


async def member_points(db: AsyncSession, user_id: int | None) -> int:
    if user_id is None:
        return 0
    row = await _member(db, int(user_id))
    return int(row.points) if row else 0


async def _ensure_member(db: AsyncSession, user_id: int) -> IshgardMember:
    row = await _member(db, user_id)
    if row is None:
        row = IshgardMember(user_id=user_id, points=0, updated_at=_now())
        db.add(row)
        await db.flush()
    return row


# ------------------------------------------------------------------ 提交
async def submit(db: AsyncSession, user: User, item_id: str, count: int) -> dict[str, Any]:
    product = product_def(item_id)
    if product is None:
        raise ValueError("只能提交「重建伊修加德」的产物")
    if count <= 0:
        raise ValueError("提交数量无效")

    state = await get_state(db)
    if int(product["stage"]) != int(state.stage):
        raise ValueError(
            f"只能提交当前阶段（第 {state.stage} 次重建）的产物；该产物已过期，请在背包出售"
        )

    consumed = await dohdol_util.stack_consume_many(db, user.id, ISHGARD_STACK, {item_id: int(count)})
    if not consumed:
        raise ValueError("产物数量不足")

    gained = int(product["points"]) * int(count)

    # 全服进度行锁：多 worker / 并发提交不丢分。
    locked = (
        await db.execute(select(IshgardState).where(IshgardState.id == 1).with_for_update())
    ).scalar_one_or_none()
    if locked is not None:
        state = locked
    state.stage_points = int(state.stage_points) + gained
    state.updated_at = _now()
    completed = advance_stage(state)

    member = await _ensure_member(db, user.id)
    member.points = int(member.points) + gained
    member.updated_at = _now()

    contribution = (
        await db.execute(
            select(IshgardContribution).where(
                IshgardContribution.round == int(state.round),
                IshgardContribution.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if contribution is None:
        contribution = IshgardContribution(round=int(state.round), user_id=user.id, points=gained)
        db.add(contribution)
    else:
        contribution.points = int(contribution.points) + gained
    contribution.updated_at = _now()

    invalidate_board_cache()
    return {
        "gained": gained,
        "points": int(member.points),
        "round": int(state.round),
        "stage": int(state.stage),
        "stagePoints": int(state.stage_points),
        "stageTarget": int(state.stage_target),
        "completedStages": completed,
    }


async def sell(db: AsyncSession, user: User, item_id: str, count: int) -> dict[str, Any]:
    """出售专属物资（材料 / 鱼 / 产物）换金币；过期物资也走这里清理。"""
    spec = dohdol_util.ishgard_item_def(item_id)
    if spec is None or count <= 0:
        raise ValueError("无法出售该物品")
    price = int(spec.get("sell", 0))
    if price <= 0:
        raise ValueError("该物品不可出售")
    if not await dohdol_util.stack_consume_many(db, user.id, ISHGARD_STACK, {item_id: int(count)}):
        raise ValueError("数量不足")
    gold = price * int(count)
    user.gold = int(user.gold) + gold
    return {"gold": gold, "itemId": item_id, "count": int(count)}


# ------------------------------------------------------------------ 采集 / 钓鱼 / 生产
async def _dohdol_progress(db: AsyncSession, user_id: int, kind: str) -> DohDolProgress:
    row = (
        await db.execute(
            select(DohDolProgress).where(
                DohDolProgress.user_id == user_id, DohDolProgress.kind == kind
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DohDolProgress(user_id=user_id, kind=kind, level=1, exp=0)
        db.add(row)
        await db.flush()
    return row


async def bonus_with_purple(
    db: AsyncSession, user_id: int, items: Sequence[Item]
) -> dict[str, float]:
    """专用装备加成 + 紫色附魔加成（仅在主手已装备时生效）。

    采集 / 钓鱼 / 生产的普通页面同样复用本函数，使紫色附魔与装备基础加成口径一致。
    """
    bonus = dict(dohdol_util.equipped_bonus(items))
    for stat, value in (await purple_effects(db, user_id)).items():
        bonus[stat] = bonus.get(stat, 0.0) + float(value)
    return bonus


# 食物 / 秘药中对采集 / 生产有意义的效果键（其余如经验走 `effect_sources` 单列明细）。
_CONSUMABLE_BONUS_STATS = ("gatherYieldPct", "craftQualityPct", "craftRarityPct")


async def activity_bonus(
    db: AsyncSession, user_id: int, items: Sequence[Item]
) -> dict[str, float]:
    """采集 / 生产的有效加成 = 专用装备（含紫色附魔）+ 生效中的食物 / 秘药。

    与普通采集 / 生产页面同源口径：装备经 `equipped_bonus`，食物 / 秘药经
    `consumables.active_effects`，使本页面的展示与实际结算保持一致。
    """
    bonus = await bonus_with_purple(db, user_id, items)
    effects = await consumables.active_effects(db, user_id)
    for stat in _CONSUMABLE_BONUS_STATS:
        value = float(effects.get(stat, 0.0))
        if value:
            bonus[stat] = bonus.get(stat, 0.0) + value
    return bonus


def _gather_node(stage: int, job_id: str) -> dict[str, Any] | None:
    for entry in stage_def(stage)["gather"]:
        if entry["jobId"] == job_id:
            return entry
    return None


def _stage_fish(stage: int) -> dict[str, Any]:
    return stage_def(stage)["fish"][0]


async def start_gather(
    db: AsyncSession, user: User, items: Sequence[Item], job_id: str
) -> dict[str, Any]:
    if job_id not in ("MIN", "BTN"):
        raise ValueError("重建采集仅支持采矿工 / 园艺工")
    state = await get_state(db)
    entry = _gather_node(int(state.stage), job_id)
    if entry is None:
        raise ValueError("当前阶段没有该职业的采集点")
    level = (await _dohdol_progress(db, user.id, "dol")).level
    if int(level) < int(entry["levelReq"]):
        raise ValueError(f"采集等级不足，需要采集等级 {entry['levelReq']}")

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now, user_id=user.id,
        kind=KIND_GATHER, job_id=job_id, region_id=None, active=True, credit=0.0,
    )
    db.add(session)
    await db.flush()
    bonus = await activity_bonus(db, user.id, items)
    seconds = dohdol_util.gather_seconds_per_action(bonus.get("gatherSpeedPct", 0.0))
    return {
        "sessionId": session.id,
        "jobId": job_id,
        "stage": int(state.stage),
        "cycle": dohdol_util.cycle_info(seconds, 0.0, now),
    }


async def report_gather(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    state = await get_state(db)
    entry = _gather_node(int(state.stage), session.job_id)
    if entry is None:
        raise ValueError("当前阶段没有该职业的采集点")

    progress = await _dohdol_progress(db, user.id, "dol")
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    bonus = await activity_bonus(db, user.id, items)
    yield_pct = bonus.get("gatherYieldPct", 0.0)
    seconds_per = dohdol_util.gather_seconds_per_action(bonus.get("gatherSpeedPct", 0.0))

    total = float(session.credit) + window
    actions = min(int(total // seconds_per), MAX_ACTIONS_PER_REPORT)
    session.credit = total - actions * seconds_per
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + actions

    rng = random.Random()
    node = {
        "yields": [
            {"materialId": entry["materialId"], "weight": 1,
             "min": int(entry["min"]), "max": int(entry["max"])}
        ],
        "levelReq": int(entry["levelReq"]),
    }
    extra_pct = bonus.get("gatherExtraActionPct", 0.0)
    double_pct = bonus.get("gatherDoublePct", 0.0)
    rare_pct = bonus.get("gatherRareChancePct", 0.0)

    def one_action() -> list[tuple[str, int]]:
        rolls = list(dohdol_util.roll_gather_yield(node, int(progress.level), yield_pct, rng))
        if rare_pct > 0 and rolls and rng.random() * 100 < rare_pct:
            rolls.append((rolls[0][0], 1))
        elif rare_pct < 0 and len(rolls) > 1 and rng.random() * 100 < -rare_pct:
            rolls = rolls[1:]
        if double_pct > 0 and rng.random() * 100 < double_pct:
            rolls = [(m, c * 2) for m, c in rolls]
        elif double_pct < 0 and rng.random() * 100 < -double_pct:
            rolls = [(m, max(1, c // 2)) for m, c in rolls]
        return rolls

    gained: dict[str, int] = {}
    for _ in range(actions):
        if extra_pct < 0 and rng.random() * 100 < -extra_pct:
            continue
        for material_id, count in one_action():
            gained[material_id] = gained.get(material_id, 0) + count
        if extra_pct > 0 and rng.random() * 100 < extra_pct:
            for material_id, count in one_action():
                gained[material_id] = gained.get(material_id, 0) + count
    await dohdol_util.stack_add_many(db, user.id, ISHGARD_STACK, gained)

    xp_sources, bonus_pct = dohdol_util.combine_xp_sources(
        dohdol_util.equipped_bonus_sources(items, "gatherXpPct"),
        await consumables.effect_sources(db, user.id, "expGainPct"),
    )
    base_xp = actions * int(CONFIG.dohdol_levels["actionXp"]["gather"])
    xp = round(base_xp * (1.0 + bonus_pct / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    return {
        "gained": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(gained.items())
        ],
        "actions": actions,
        "xp": xp,
        "xpBreakdown": dohdol_util.xp_breakdown(base_xp, 1.0, bonus_pct, xp, xp_sources),
        "level": level_info,
        "cycle": dohdol_util.cycle_info(seconds_per, float(session.credit), now),
    }


def _fish_cast_seconds(bonus: dict[str, float]) -> float:
    """单次抛竿耗时（受专用装备 / 紫色附魔的采集速度加成影响）。"""
    speed = bonus.get("gatherSpeedPct", 0.0)
    return max(0.2, float(_cfg()["fish"]["castSeconds"]) / (1.0 + max(0.0, speed) / 100.0))


async def start_fish(db: AsyncSession, user: User, items: Sequence[Item]) -> dict[str, Any]:
    state = await get_state(db)
    fish = _stage_fish(int(state.stage))
    level = (await _dohdol_progress(db, user.id, "dol")).level
    if int(level) < int(fish["levelReq"]):
        raise ValueError(f"采集等级不足，需要采集等级 {fish['levelReq']}")

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now, user_id=user.id,
        kind=KIND_FISH, job_id="FSH", region_id=None, active=True, credit=0.0,
    )
    db.add(session)
    await db.flush()
    bonus = await activity_bonus(db, user.id, items)
    seconds = _fish_cast_seconds(bonus)
    return {
        "sessionId": session.id,
        "stage": int(state.stage),
        "cycle": dohdol_util.cycle_info(seconds, 0.0, now),
    }


async def report_fish(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    state = await get_state(db)
    fish = _stage_fish(int(state.stage))
    progress = await _dohdol_progress(db, user.id, "dol")
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    bonus = await activity_bonus(db, user.id, items)
    per_cast = _fish_cast_seconds(bonus)
    total = float(session.credit) + window
    casts = min(int(total // per_cast), MAX_ACTIONS_PER_REPORT)
    session.credit = total - casts * per_cast
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + casts

    rng = random.Random()
    double_pct = bonus.get("fishDoubleCatchPct", 0.0)
    caught = 0
    for _ in range(casts):
        caught += 1
        if double_pct > 0 and rng.random() * 100 < double_pct:
            caught += 1
        elif double_pct < 0 and rng.random() * 100 < -double_pct:
            caught = max(0, caught - 1)
    gained = {fish["id"]: caught} if caught > 0 else {}
    await dohdol_util.stack_add_many(db, user.id, ISHGARD_STACK, gained)

    xp_sources, bonus_pct = dohdol_util.combine_xp_sources(
        dohdol_util.equipped_bonus_sources(items, "gatherXpPct"),
        await consumables.effect_sources(db, user.id, "expGainPct"),
    )
    base_xp = casts * int(CONFIG.dohdol_levels["actionXp"]["fish"])
    xp = round(base_xp * (1.0 + bonus_pct / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    return {
        "gained": [
            {"itemId": fid, "name": dohdol_util.material_name(fid), "count": c}
            for fid, c in gained.items()
        ],
        "actions": casts,
        "xp": xp,
        "xpBreakdown": dohdol_util.xp_breakdown(base_xp, 1.0, bonus_pct, xp, xp_sources),
        "level": level_info,
        "cycle": dohdol_util.cycle_info(per_cast, float(session.credit), now),
    }


def _max_by_materials(stock: dict[str, int], inputs: list[dict[str, Any]]) -> int:
    best: int | None = None
    for entry in inputs:
        have = stock.get(entry["itemId"], 0)
        need = max(1, int(entry["count"]))
        possible = have // need
        best = possible if best is None else min(best, possible)
    return 0 if best is None else max(0, best)


async def start_produce(
    db: AsyncSession, user: User, items: Sequence[Item], job_id: str, recipe_id: str,
    count: int | None = None,
) -> dict[str, Any]:
    product = product_def(recipe_id)
    if product is None:
        raise ValueError("配方不存在")
    if product["jobId"] != job_id:
        raise ValueError("该配方不属于该职业")
    state = await get_state(db)
    if int(product["stage"]) != int(state.stage):
        raise ValueError("该配方属于已过期的阶段，无法生产")
    progress = await _dohdol_progress(db, user.id, "doh")
    if int(progress.level) < int(product["requiredLevel"]):
        raise ValueError(f"生产等级不足，需要生产等级 {product['requiredLevel']}")

    stock = await dohdol_util.stack_counts(db, user.id, ISHGARD_STACK)
    max_by_materials = _max_by_materials(stock, product["inputs"])
    if max_by_materials <= 0:
        raise ValueError("材料不足，无法生产")
    target = max_by_materials if count is None else min(int(count), max_by_materials)

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now, user_id=user.id, kind=KIND_PRODUCE,
        job_id=job_id, recipe_id=recipe_id, active=True, credit=0.0, target_actions=target,
    )
    db.add(session)
    await db.flush()
    seconds = _craft_seconds(product, await activity_bonus(db, user.id, items))
    return {
        "sessionId": session.id, "jobId": job_id, "recipeId": recipe_id,
        "targetActions": target, "stage": int(state.stage),
        "cycle": dohdol_util.cycle_info(seconds, 0.0, now),
    }


def _craft_seconds(product: dict[str, Any], bonus: dict[str, float]) -> float:
    speed = bonus.get("craftSpeedPct", 0.0)
    return max(0.2, float(product["craftSeconds"]) * (1.0 - min(0.6, speed / 100.0)))


async def report_produce(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    product = product_def(session.recipe_id or "")
    if product is None:
        raise ValueError("配方不存在")
    state = await get_state(db)
    if int(product["stage"]) != int(state.stage):
        # 阶段已推进 → 该配方失效：静默结束会话，返回过期标记（前端据此停止循环）。
        session.active = False
        session.ended_at = datetime.now(timezone.utc)
        return {"expired": True, "crafts": 0, "finished": True, "recipeId": product["id"]}

    progress = await _dohdol_progress(db, user.id, "doh")
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    bonus = await activity_bonus(db, user.id, items)
    seconds = _craft_seconds(product, bonus)
    target = int(session.target_actions) if session.target_actions is not None else None
    total = float(session.credit) + window
    by_time = int(total // seconds)

    stock = await dohdol_util.stack_counts(db, user.id, ISHGARD_STACK)
    by_materials = _max_by_materials(stock, product["inputs"])
    remaining = MAX_ACTIONS_PER_REPORT if target is None else max(0, target - int(session.total_actions))
    crafts = min(by_time, by_materials, remaining, MAX_ACTIONS_PER_REPORT)

    session.credit = total - by_time * seconds
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + crafts
    produced_total = int(session.total_actions)
    finished = target is not None and produced_total >= target
    if finished:
        session.active = False
        session.ended_at = now

    rng = random.Random()
    material_save = bonus.get("craftMaterialSavePct", 0.0)
    extra_output = bonus.get("craftExtraOutputPct", 0.0)
    consume_acc: dict[str, int] = {}
    out_count = 0
    for _ in range(crafts):
        for entry in product["inputs"]:
            need = int(entry["count"])
            if material_save > 0 and rng.random() * 100 < material_save:
                continue
            if material_save < 0 and rng.random() * 100 < -material_save:
                need += 1
            consume_acc[entry["itemId"]] = consume_acc.get(entry["itemId"], 0) + need
        produced = 1
        if extra_output > 0 and rng.random() * 100 < extra_output:
            produced += 1
        elif extra_output < 0 and rng.random() * 100 < -extra_output:
            produced = 0
        out_count += produced

    if consume_acc:
        await dohdol_util.stack_consume_many(db, user.id, ISHGARD_STACK, consume_acc)
    if out_count > 0:
        await dohdol_util.stack_add_many(db, user.id, ISHGARD_STACK, {product["id"]: out_count})

    xp_sources, bonus_pct = dohdol_util.combine_xp_sources(
        dohdol_util.equipped_bonus_sources(items, "craftXpPct"),
        await consumables.effect_sources(db, user.id, "expGainPct"),
    )
    base_xp = int(product["xp"]) * crafts
    xp = round(base_xp * (1.0 + bonus_pct / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    return {
        "crafts": crafts,
        "recipeId": product["id"],
        "materials": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(consume_acc.items())
        ],
        "produced": (
            [{"itemId": product["id"], "name": dohdol_util.material_name(product["id"]), "count": out_count}]
            if out_count > 0 else []
        ),
        "xp": xp,
        "xpBreakdown": dohdol_util.xp_breakdown(base_xp, 1.0, bonus_pct, xp, xp_sources),
        "level": level_info,
        "targetActions": target,
        "producedTotal": produced_total,
        "finished": finished,
        "cycle": dohdol_util.cycle_info(seconds, float(session.credit), now),
    }


async def stop_session(db: AsyncSession, session: ActivitySession) -> None:
    session.active = False
    session.ended_at = datetime.now(timezone.utc)


# ------------------------------------------------------------------ 积分榜
_BOARD_CACHE: dict[str, Any] = {"at": 0.0, "rows": None}
_BOARD_TTL = 10.0


def invalidate_board_cache() -> None:
    _BOARD_CACHE["at"] = 0.0
    _BOARD_CACHE["rows"] = None


async def _board_rows(db: AsyncSession, fresh: bool = False) -> list[dict[str, Any]]:
    now = _now()
    if not fresh:
        cached = _BOARD_CACHE["rows"]
        if cached is not None and now - float(_BOARD_CACHE["at"]) < _BOARD_TTL:
            return list(cached)
    rows = (
        await db.execute(
            select(IshgardMember, User)
            .join(User, User.id == IshgardMember.user_id)
            .order_by(IshgardMember.points.desc(), IshgardMember.updated_at.asc())
        )
    ).all()
    out: list[dict[str, Any]] = []
    for member, user in rows:
        if int(member.points) <= 0 or is_admin(user) or user.banned:
            continue
        out.append({
            "userId": user.id,
            "nickname": user.nickname,
            "username": user.username,
            "points": int(member.points),
            "activeTitleId": user.active_title_id,
        })
    _BOARD_CACHE["rows"] = out
    _BOARD_CACHE["at"] = now
    return list(out)


async def board(db: AsyncSession, page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
    rows = await _board_rows(db)
    start = max(0, (int(page) - 1) * int(page_size))
    out = []
    for index, row in enumerate(rows[start:start + int(page_size)], start=start + 1):
        out.append({**row, "rank": index})
    return out


async def my_rank(db: AsyncSession, user_id: int) -> dict[str, Any]:
    rows = await _board_rows(db)
    for index, row in enumerate(rows, start=1):
        if int(row["userId"]) == int(user_id):
            return {"rank": index, "points": int(row["points"])}
    return {"rank": 0, "points": await member_points(db, user_id)}


# ------------------------------------------------------------------ 周期称号
async def _apply_role(
    db: AsyncSession, state: IshgardState, role: str, title_id: str,
    candidate: tuple[int, int] | None, now: float, force: bool = False,
) -> bool:
    """按「严格超越才转移、平局保留现任」的规则更新某称号持有者。返回是否发生转移。

    `force=True` 用于「同一人不得同时持有两个称号」的纠正（此时不再要求严格超越）。
    """
    attr = f"{role}_user_id"
    current = getattr(state, attr)
    if candidate is None:
        return False
    cand_id, cand_points = int(candidate[0]), int(candidate[1])
    if current is not None and int(current) == cand_id:
        return False
    if current is not None and not force:
        cur_points = await member_points(db, int(current))
        if cand_points <= cur_points:
            return False
    setattr(state, attr, cand_id)
    setattr(state, f"{role}_since", now)
    if current is not None:
        await _revoke_title(db, int(current), title_id)
    await _grant_title(db, cand_id, title_id)
    return True


async def _grant_title(db: AsyncSession, user_id: int, title_id: str) -> None:
    exists = (
        await db.execute(
            select(UserTitle).where(UserTitle.user_id == user_id, UserTitle.title_id == title_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(UserTitle(user_id=user_id, title_id=title_id))


async def _revoke_title(db: AsyncSession, user_id: int, title_id: str) -> None:
    row = (
        await db.execute(
            select(UserTitle).where(UserTitle.user_id == user_id, UserTitle.title_id == title_id)
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
    user = await db.get(User, user_id)
    if user is not None and user.active_title_id == title_id:
        user.active_title_id = None


async def settle_titles(db: AsyncSession, now: float | None = None) -> dict[str, Any]:
    """每 6H 结算一次：累计积分前二分别获得「天穹圣人 / 天穹圣徒」（全服唯一、可夺走）。"""
    now = _now() if now is None else float(now)
    state = await get_state(db)
    if float(state.title_period_ends_at or 0) > now:
        return {"settled": False}

    got = await try_advisory_lock(db, TITLE_LOCK_KEY)
    if not got:
        return {"settled": False}
    try:
        locked = (
            await db.execute(select(IshgardState).where(IshgardState.id == 1).with_for_update())
        ).scalar_one_or_none()
        if locked is not None:
            state = locked
        if float(state.title_period_ends_at or 0) > now:
            return {"settled": False}
        top = await _board_rows(db, fresh=True)  # 已按积分降序、并列按 updated_at 升序
        first = (int(top[0]["userId"]), int(top[0]["points"])) if len(top) > 0 else None
        second = (int(top[1]["userId"]), int(top[1]["points"])) if len(top) > 1 else None
        changed = await _apply_role(db, state, "saint", saint_title_id(), first, now)
        # 同一人不得同时持有两个称号：若现任圣徒与圣人重合，强制改判给第二名。
        overlap = (
            state.apostle_user_id is not None
            and state.saint_user_id is not None
            and int(state.apostle_user_id) == int(state.saint_user_id)
        )
        changed = await _apply_role(
            db, state, "apostle", apostle_title_id(), second, now, force=overlap
        ) or changed
        state.title_period_ends_at = now + title_window()
        state.updated_at = now
        await db.flush()
        return {"settled": True, "changed": changed}
    finally:
        await release_advisory_lock(db, TITLE_LOCK_KEY)


# ------------------------------------------------------------------ 可成长主手装备
async def _tool(db: AsyncSession, user_id: int, kind: str) -> IshgardTool | None:
    return (
        await db.execute(
            select(IshgardTool).where(IshgardTool.user_id == user_id, IshgardTool.kind == kind)
        )
    ).scalar_one_or_none()


def _roll_pink(kind: str, rng: random.Random) -> tuple[str, dict[str, float]]:
    pool = [p for p in _cfg()["pinkEnchants"] if p["kind"] == kind]
    pink = rng.choice(pool)
    values = {
        s["stat"]: round(rng.uniform(float(s["range"][0]), float(s["range"][1])), 2)
        for s in pink["stats"]
    }
    return str(pink["id"]), values


def _build_tool_item(kind: str, level: int, rng: random.Random) -> Item:
    spec = tool_level_spec(kind, level)
    assert spec is not None
    slot = tool_slot(kind)
    terms = roll_dedicated_terms(
        slot, "mythic", rng, 0.0, int(CONFIG.recipes["equipment"]["guaranteedAncientTerms"]), level
    )
    return Item(
        base_id=str(spec["id"]),
        name=str(spec["name"]),
        category=str(_cfg()["tools"][kind]["category"]),
        slot=slot,
        rarity="mythic",
        level_req=int(level),
        base_attrs=[{"attr": stat, "value": round(float(value), 2)} for stat, value in spec["bonus"].items()],
        sub_attrs=[],
        terms=terms,
        high_quality=True,
        source="ishgard",
    )


def _stage_done(state: IshgardState) -> int:
    """当前轮次已完成的阶段数（阶段随轮次重置，故即 stage-1）。"""
    return max(0, int(state.stage) - 1)


def _tool_status(state: IshgardState, points: int, kind: str, level: int) -> dict[str, Any]:
    done = _stage_done(state)
    levels = tool_levels(kind)
    if level <= 0:
        first = levels[0]
        return {
            "canClaim": points >= int(first["threshold"]) and done >= int(first["stage"]),
            "nextLevel": int(first["level"]),
            "nextThreshold": int(first["threshold"]),
            "nextStage": int(first["stage"]),
        }
    nxt = next((l for l in levels if int(l["level"]) > int(level)), None)
    if nxt is None:
        return {"canClaim": False, "canUpgrade": False, "maxLevel": True}
    return {
        "canUpgrade": points >= int(nxt["threshold"]) and done >= int(nxt["stage"]),
        "nextLevel": int(nxt["level"]),
        "nextThreshold": int(nxt["threshold"]),
        "nextStage": int(nxt["stage"]),
    }


async def claim_tool(db: AsyncSession, user: User, kind: str) -> dict[str, Any]:
    if kind not in ("doh", "dol"):
        raise ValueError("装备类型无效")
    state = await get_state(db)
    member = await _ensure_member(db, user.id)
    tool = await _tool(db, user.id, kind)
    if tool is not None and int(tool.level) > 0:
        return await tool_view(db, user, kind)  # 幂等：已拥有
    first = tool_levels(kind)[0]
    if int(member.points) < int(first["threshold"]):
        raise ValueError(f"个人累计积分不足，需要 {first['threshold']}")
    if _stage_done(state) < int(first["stage"]):
        raise ValueError(f"需要完成第 {first['stage']} 次重建")

    rng = random.Random()
    item = _build_tool_item(kind, int(first["level"]), rng)
    item.user_id = user.id
    db.add(item)
    await db.flush()
    pink_id, pink_values = _roll_pink(kind, rng)
    if tool is None:
        tool = IshgardTool(user_id=user.id, kind=kind)
        db.add(tool)
    tool.level = int(first["level"])
    tool.item_id = item.id
    tool.pink_id = pink_id
    tool.pink_values = pink_values
    tool.unlocked_at = _now()
    tool.updated_at = _now()
    await db.flush()
    return await tool_view(db, user, kind)


async def upgrade_tool(db: AsyncSession, user: User, kind: str) -> dict[str, Any]:
    if kind not in ("doh", "dol"):
        raise ValueError("装备类型无效")
    state = await get_state(db)
    member = await _ensure_member(db, user.id)
    tool = await _tool(db, user.id, kind)
    if tool is None or int(tool.level) <= 0:
        raise ValueError("尚未拥有该装备")
    nxt = next((l for l in tool_levels(kind) if int(l["level"]) > int(tool.level)), None)
    if nxt is None:
        raise ValueError("已达最高等级")
    if int(member.points) < int(nxt["threshold"]):
        raise ValueError(f"个人累计积分不足，需要 {nxt['threshold']}")
    if _stage_done(state) < int(nxt["stage"]):
        raise ValueError(f"需要完成第 {nxt['stage']} 次重建")

    item = await db.get(Item, int(tool.item_id)) if tool.item_id else None
    if item is None:
        item = _build_tool_item(kind, int(nxt["level"]), random.Random())
        item.user_id = user.id
        db.add(item)
        await db.flush()
        tool.item_id = item.id
    else:
        rng = random.Random()
        rebuilt = _build_tool_item(kind, int(nxt["level"]), rng)
        item.base_id = rebuilt.base_id
        item.name = rebuilt.name
        item.level_req = rebuilt.level_req
        item.base_attrs = rebuilt.base_attrs
        item.terms = rebuilt.terms
        item.high_quality = True
    tool.level = int(nxt["level"])
    tool.updated_at = _now()
    await db.flush()
    return await tool_view(db, user, kind)


async def reroll_pink(db: AsyncSession, user: User, kind: str) -> dict[str, Any]:
    """消耗 1 张「重新打造卡」重 roll 紫色附魔（种类 + 数值），不扣金币。"""
    if kind not in ("doh", "dol"):
        raise ValueError("装备类型无效")
    tool = await _tool(db, user.id, kind)
    if tool is None or int(tool.level) <= 0:
        raise ValueError("尚未拥有该装备")
    if not await dohdol_util.stack_consume(db, user.id, dohdol_util.STACK_CARD, "recraft_card", 1):
        raise ValueError("「重新打造卡」不足")
    pink_id, pink_values = _roll_pink(kind, random.Random())
    tool.pink_id = pink_id
    tool.pink_values = pink_values
    tool.updated_at = _now()
    await db.flush()
    return await tool_view(db, user, kind)


async def purple_effects(db: AsyncSession, user_id: int) -> dict[str, float]:
    """已装备的伊修加德主手所带的紫色附魔加成（未装备则不计）。"""
    tools = (
        await db.execute(select(IshgardTool).where(IshgardTool.user_id == user_id))
    ).scalars().all()
    out: dict[str, float] = {}
    for tool in tools:
        if not tool.pink_id or not tool.item_id:
            continue
        item = await db.get(Item, int(tool.item_id))
        if item is None or item.equipped_slot != tool_slot(tool.kind):
            continue
        for stat, value in (tool.pink_values or {}).items():
            out[str(stat)] = out.get(str(stat), 0.0) + float(value)
    return out


def pink_desc(pink: dict[str, Any], values: dict[str, float]) -> str:
    text = str(pink.get("desc", ""))
    stats = pink.get("stats", [])
    for index, entry in enumerate(stats):
        key = "v" if index == 0 else f"v{index + 1}"
        text = text.replace("{" + key + "}", f"{float(values.get(entry['stat'], 0.0)):g}")
    return text


async def tool_view(db: AsyncSession, user: User, kind: str) -> dict[str, Any]:
    state = await get_state(db)
    points = await member_points(db, user.id)
    tool = await _tool(db, user.id, kind)
    spec = tool_level_spec(kind, int(tool.level)) if tool and int(tool.level) > 0 else None
    pink = CONFIG.ishgard_pink_by_id.get(str(tool.pink_id)) if tool and tool.pink_id else None
    return {
        "kind": kind,
        "slot": tool_slot(kind),
        "level": int(tool.level) if tool else 0,
        "itemId": int(tool.item_id) if tool and tool.item_id else None,
        "name": str(spec["name"]) if spec else None,
        "bonus": spec["bonus"] if spec else None,
        "pink": (
            {
                "id": pink["id"], "name": pink["name"], "kind": pink["kind"],
                "values": tool.pink_values or {}, "desc": pink_desc(pink, tool.pink_values or {}),
            }
            if pink else None
        ),
        "status": _tool_status(state, points, kind, int(tool.level) if tool else 0),
    }


# ------------------------------------------------------------------ 状态视图
def _material_view(stage: int, spec: dict[str, Any], have: dict[str, int]) -> dict[str, Any]:
    return {
        "itemId": spec["id"], "name": display_name(stage, spec["name"]),
        "baseName": spec["name"], "jobId": spec["jobId"],
        "levelReq": int(spec["levelReq"]), "sell": int(spec.get("sell", 0)),
        "count": int(have.get(spec["id"], 0)),
    }


def _fish_view(stage: int, spec: dict[str, Any], have: dict[str, int]) -> dict[str, Any]:
    return {
        "itemId": spec["id"], "name": display_name(stage, spec["name"]),
        "baseName": spec["name"], "levelReq": int(spec["levelReq"]),
        "sell": int(spec.get("sell", 0)), "count": int(have.get(spec["id"], 0)),
    }


def _product_view(stage: int, spec: dict[str, Any], have: dict[str, int]) -> dict[str, Any]:
    return {
        "itemId": spec["id"], "name": display_name(stage, spec["name"]),
        "baseName": spec["name"], "jobId": spec["jobId"],
        "requiredLevel": int(spec["requiredLevel"]), "craftSeconds": float(spec["craftSeconds"]),
        "xp": int(spec["xp"]), "points": int(spec["points"]), "sell": int(spec.get("sell", 0)),
        "inputs": [
            {"itemId": e["itemId"], "name": dohdol_util.material_name(e["itemId"]),
             "count": int(e["count"]), "have": int(have.get(e["itemId"], 0))}
            for e in spec["inputs"]
        ],
        "count": int(have.get(spec["id"], 0)),
    }


def _bag_view(rows: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for item_id, count in rows.items():
        if int(count) <= 0:
            continue
        spec = dohdol_util.ishgard_item_def(item_id)
        if spec is None:
            continue
        stage = int(spec["stage"])
        if item_id in CONFIG.ishgard_material_by_id:
            kind = "material"
        elif item_id in CONFIG.ishgard_fish_by_id:
            kind = "fish"
        else:
            kind = "product"
        out.append({
            "itemId": item_id, "name": display_name(stage, spec["name"]), "stage": stage,
            "kind": kind, "count": int(count), "sell": int(spec.get("sell", 0)),
        })
    out.sort(key=lambda r: (r["stage"], r["kind"], r["itemId"]))
    return out


async def build_state(db: AsyncSession, user: User) -> dict[str, Any]:
    await settle_titles(db)
    state = await get_state(db)
    points = await member_points(db, user.id)
    stage = int(state.stage)
    sdef = stage_def(stage)
    have = await dohdol_util.stack_counts(db, user.id, ISHGARD_STACK)
    items = (await db.execute(select(Item).where(Item.user_id == user.id))).scalars().all()
    bonus = await activity_bonus(db, user.id, items)

    saint = await db.get(User, int(state.saint_user_id)) if state.saint_user_id else None
    apostle = await db.get(User, int(state.apostle_user_id)) if state.apostle_user_id else None

    return {
        "round": int(state.round),
        "stage": stage,
        "stageCount": stage_count(),
        "stagePoints": int(state.stage_points),
        "stageTarget": int(state.stage_target),
        "stageTargets": stage_targets(),
        "stageName": f"第 {stage} 次重建",
        "myPoints": points,
        "myRank": await my_rank(db, user.id),
        "bonus": {stat: round(value, 2) for stat, value in bonus.items()},
        "titlePeriodEndsAt": float(state.title_period_ends_at or 0),
        "titleWindowSeconds": title_window(),
        "saint": _holder_view(saint, state.saint_since, "天穹圣人") if saint else None,
        "apostle": _holder_view(apostle, state.apostle_since, "天穹圣徒") if apostle else None,
        "current": {
            "materials": [_material_view(stage, m, have) for m in sdef["materials"]],
            "gather": sdef["gather"],
            "fish": [_fish_view(stage, f, have) for f in sdef["fish"]],
            "products": [_product_view(stage, p, have) for p in sdef["products"]],
        },
        "stages": [
            {"stage": int(s["stage"]), "name": f"第 {int(s['stage'])} 次重建",
             "target": target_for(int(s["stage"])),
             "materials": [display_name(int(s["stage"]), m["name"]) for m in s["materials"]],
             "products": [display_name(int(s["stage"]), p["name"]) for p in s["products"]]}
            for s in _cfg()["stages"]
        ],
        "tools": {
            "doh": await tool_view(db, user, "doh"),
            "dol": await tool_view(db, user, "dol"),
        },
        "pinkEnchants": _cfg()["pinkEnchants"],
        "bag": _bag_view(have),
    }


def _holder_view(user: User, since: float, label: str) -> dict[str, Any]:
    if is_admin(user):
        return {"label": label, "nickname": "管理员", "username": None, "since": float(since or 0)}
    return {"label": label, "nickname": user.nickname, "username": user.username, "since": float(since or 0)}
