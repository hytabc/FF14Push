"""生产 / 采集公共工具：等级、配方、材料、专用装备加成、活动会话。

设计原则与战斗一致：所有产出由服务端结算，客户端只上报「发生了什么」。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivitySession, StackItem
from app.services.game_config import CONFIG

# 材料 / 半成品 / 鱼都存进 kind="material" 的堆叠；药水与食物各占一个 kind。
STACK_MATERIAL = "material"
STACK_POTION = "potion"
STACK_FOOD = "food"

# 单次上报允许结算的最大窗口（秒）：离开页面即暂停，不做离线收益。
MAX_WINDOW_SECONDS = 30.0
MIN_WINDOW_SECONDS = 0.2


# ------------------------------------------------------------------ 等级
def level_cap() -> int:
    return int(CONFIG.dohdol_levels["levelCap"])


def exp_to_next(level: int) -> int:
    cfg = CONFIG.dohdol_levels["expCurve"]
    return max(1, round(float(cfg["base"]) * float(cfg["growth"]) ** max(0, level - 1)))


def apply_level_exp(progress: Any, amount: int) -> dict[str, int]:
    if amount <= 0:
        return {"levelsGained": 0, "level": progress.level, "exp": progress.exp}
    progress.exp = int(progress.exp) + int(amount)
    gained = 0
    while progress.level < level_cap():
        need = exp_to_next(progress.level)
        if progress.exp < need:
            break
        progress.exp -= need
        progress.level += 1
        gained += 1
    if progress.level >= level_cap():
        progress.exp = 0
    return {"levelsGained": gained, "level": progress.level, "exp": progress.exp}


# ------------------------------------------------------------------ 查询
def job_def(job_id: str) -> dict[str, Any] | None:
    return CONFIG.dohdol_job_by_id.get(job_id)


def kind_of_job(job_id: str) -> str | None:
    job = job_def(job_id)
    return job["kind"] if job else None


def recipe_def(recipe_id: str) -> dict[str, Any] | None:
    return CONFIG.recipe_by_id.get(recipe_id)


def material_def(item_id: str) -> dict[str, Any] | None:
    return CONFIG.material_by_id.get(item_id)


def material_name(item_id: str) -> str:
    """材料 / 半成品 / 鱼 / 药水食物 / 装备底材 / 专用装备 的显示名。"""
    d = material_def(item_id)
    if d:
        return d["name"]
    consumable = CONFIG.consumable_by_id.get(item_id)
    if consumable:
        return consumable["name"]
    base = CONFIG.base_item_by_id.get(item_id)
    if base:
        return base.name
    dohdol = CONFIG.dohdol_item_by_id.get(item_id)
    if dohdol:
        return dohdol["name"]
    return item_id


def consumable_def(item_id: str) -> dict[str, Any] | None:
    return CONFIG.consumable_by_id.get(item_id)


def sell_price(kind: str, item_id: str) -> int:
    """堆叠物品的出售单价（金币）。材料 / 半成品 / 鱼 / 药水食物均可出售。"""
    if kind in (STACK_POTION, STACK_FOOD):
        spec = consumable_def(item_id)
        return max(0, int(spec.get("sell", 0))) if spec else 0
    material = material_def(item_id)
    return max(0, int(material.get("sell", 0))) if material else 0


def sellable_kind(item_id: str) -> str | None:
    """按物品 id 推断其堆叠种类（potion / food / material），未知返回 None。"""
    spec = consumable_def(item_id)
    if spec is not None:
        return str(spec["kind"])
    if material_def(item_id) is not None:
        return STACK_MATERIAL
    return None


# ------------------------------------------------------------------ 专用装备加成
def equipped_bonus(items: Iterable[Any]) -> dict[str, float]:
    """汇总已穿戴的生产/采集专用装备加成。"""
    out: dict[str, float] = {}
    for item in items:
        if getattr(item, "equipped_slot", None) is None:
            continue
        base = CONFIG.dohdol_item_by_id.get(item.base_id)
        if base is None:
            continue
        for stat, value in base["bonus"].items():
            out[stat] = out.get(stat, 0.0) + float(value)
    return out


# ------------------------------------------------------------------ 会话
async def end_active_sessions(db: AsyncSession, user_id: int, keep_id: int | None = None) -> None:
    """结束该账号所有进行中的活动会话（四活动互斥）。"""
    rows = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.user_id == user_id, ActivitySession.active.is_(True)
            )
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if keep_id is not None and row.id == keep_id:
            continue
        row.active = False
        row.ended_at = now


async def end_other_battle_sessions(db: AsyncSession, user_id: int) -> None:
    """启动采集/生产/钓鱼时，停止该账号进行中的战斗会话。"""
    from app.models import BattleSession  # 局部导入避免循环依赖

    rows = (
        await db.execute(
            select(BattleSession).where(BattleSession.user_id == user_id, BattleSession.active.is_(True))
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.active = False
        row.ended_at = now


def window_seconds(last_at: datetime | None, now: datetime) -> float:
    """只认服务端时钟的结算窗口（客户端时间不可信）。"""
    if last_at is None:
        return 0.0
    if last_at.tzinfo is None:  # SQLite 返回 naive datetime
        last_at = last_at.replace(tzinfo=timezone.utc)
    return max(0.0, min(MAX_WINDOW_SECONDS, (now - last_at).total_seconds()))


# ------------------------------------------------------------------ 堆叠库存
async def stack_row(db: AsyncSession, user_id: int, kind: str, item_id: str) -> StackItem | None:
    return (
        await db.execute(
            select(StackItem).where(
                StackItem.user_id == user_id, StackItem.kind == kind, StackItem.item_id == item_id
            )
        )
    ).scalar_one_or_none()


async def stack_add(db: AsyncSession, user_id: int, kind: str, item_id: str, count: int) -> None:
    if count <= 0:
        return
    row = await stack_row(db, user_id, kind, item_id)
    if row is None:
        db.add(StackItem(user_id=user_id, kind=kind, item_id=item_id, count=int(count)))
    else:
        row.count = int(row.count) + int(count)


async def stack_counts(db: AsyncSession, user_id: int, kind: str | None = None) -> dict[str, int]:
    stmt = select(StackItem).where(StackItem.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(StackItem.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    out: dict[str, int] = {}
    for row in rows:
        out[row.item_id] = int(row.count)
    return out


async def stack_consume(
    db: AsyncSession, user_id: int, kind: str, item_id: str, count: int
) -> bool:
    row = await stack_row(db, user_id, kind, item_id)
    if row is None or int(row.count) < count:
        return False
    row.count = int(row.count) - int(count)
    if row.count <= 0:
        await db.delete(row)
    return True


# ------------------------------------------------------------------ 采集产出
def roll_gather_yield(
    node: dict[str, Any], level: int, yield_bonus_pct: float, rng: random.Random
) -> list[tuple[str, int]]:
    """按采集点权重点抽一次产出，返回 [(materialId, count)]。"""
    yields = node.get("yields", [])
    if not yields:
        return []
    total = sum(max(0.0, float(y["weight"])) for y in yields)
    if total <= 0:
        return []
    roll = rng.random() * total
    cumulative = 0.0
    picked = yields[-1]
    for entry in yields:
        cumulative += max(0.0, float(entry["weight"]))
        if roll < cumulative:
            picked = entry
            break
    base = rng.randint(int(picked["min"]), int(picked["max"]))
    # 采集等级 + 专用装备/药水的产量加成
    level_bonus = min(
        float(CONFIG.gather_nodes["maxYieldLevelBonusPct"]),
        float(CONFIG.gather_nodes["yieldPerLevelPct"]) * max(0, int(level) - 1),
    )
    mult = 1.0 + level_bonus / 100.0 + max(0.0, yield_bonus_pct) / 100.0
    count = max(1, int(round(base * mult)))
    return [(picked["materialId"], count)]


def gather_seconds_per_action(base_bonus_pct: float) -> float:
    base = float(CONFIG.gather_nodes["baseSecondsPerAction"])
    speed = max(0.0, base_bonus_pct) / 100.0
    return max(0.2, base / (1.0 + speed))


def fish_seconds_per_cast(base_bonus_pct: float) -> float:
    base = float(CONFIG.fish["castSeconds"])
    speed = max(0.0, base_bonus_pct) / 100.0
    return max(0.2, base / (1.0 + speed))


def cycle_info(seconds: float, credit: float, now: datetime | None = None) -> dict[str, Any]:
    """单次动作节奏，供前端插值画进度条。

    `at` 是服务端计算 credit 的时刻（epoch 毫秒）。前端用它做半 RTT 校正，
    使进度条的「跑满」时刻与产出时刻对齐，且不依赖客户端本地时钟。
    """
    moment = now or datetime.now(timezone.utc)
    return {"seconds": float(seconds), "credit": float(credit), "at": int(moment.timestamp() * 1000)}
