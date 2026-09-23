"""药水与食物：使用、生效状态与各类加成读取。

药水（60s）与食物（1800s）各占一个槽位，可共存；效果不影响战力与地区/副本门槛，
只作用于对应系统的服务端结算（经验/金币、抽箱品阶、制造品质、钓鱼、采集）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActiveConsumable
from app.services import dohdol_util
from app.services.game_config import CONFIG


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _rows(db: AsyncSession, user_id: int) -> list[ActiveConsumable]:
    rows = (
        await db.execute(select(ActiveConsumable).where(ActiveConsumable.user_id == user_id))
    ).scalars().all()
    now = _now()
    alive: list[ActiveConsumable] = []
    for row in rows:
        if _aware(row.expires_at) > now:
            alive.append(row)
        else:
            await db.delete(row)
    return alive


async def active_effects(db: AsyncSession, user_id: int) -> dict[str, float]:
    """所有生效中药水/食物的效果合计（同一 stat 相加叠加）。"""
    out: dict[str, float] = {}
    for row in await _rows(db, user_id):
        for effect in row.effects or []:
            stat = effect.get("stat")
            if not stat:
                continue
            out[stat] = out.get(stat, 0.0) + float(effect.get("value", 0.0))
    return out


async def use_consumable(db: AsyncSession, user_id: int, item_id: str) -> dict[str, Any]:
    """使用一瓶药水 / 一份食物：消耗库存，并按服务端时钟更新该槽位的到期时间。

    药水 / 食物各占一个槽位（`uq_consumable_user_kind`）：**同一件**连续使用时时长叠加
    （在原有剩余时间之上再累加一份 duration）；换成同槽位的**另一种**则重置为新的一份
    时长（now + duration）。效果与名称始终取最近一次使用的那份。
    """
    spec = dohdol_util.consumable_def(item_id)
    if spec is None:
        raise ValueError("未知的消耗品")
    kind = spec["kind"]
    if not await dohdol_util.stack_consume(db, user_id, kind, item_id, 1):
        raise ValueError(f"{spec['name']}不足")

    duration = float(CONFIG.consumables["kinds"][kind]["durationSec"])
    now = _now()

    row = (
        await db.execute(
            select(ActiveConsumable).where(
                ActiveConsumable.user_id == user_id, ActiveConsumable.kind == kind
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            ActiveConsumable(
                user_id=user_id,
                kind=kind,
                item_id=item_id,
                effects=list(spec["effects"]),
                expires_at=now + timedelta(seconds=duration),
            )
        )
    else:
        # 同一件：时长叠加（已过期则从此刻算起）；换成另一种：重置为新的一份时长。
        base = max(now, _aware(row.expires_at)) if row.item_id == item_id else now
        row.item_id = item_id
        row.effects = list(spec["effects"])
        row.expires_at = base + timedelta(seconds=duration)

    return {
        "itemId": item_id,
        "name": spec["name"],
        "kind": kind,
        "durationSec": int(duration),
        "effects": spec["effects"],
    }


async def active_state(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    """生效中的药水/食物（含剩余秒数），供前端展示倒计时。"""
    now = _now()
    out: list[dict[str, Any]] = []
    for row in await _rows(db, user_id):
        spec = dohdol_util.consumable_def(row.item_id) or {}
        out.append(
            {
                "kind": row.kind,
                "itemId": row.item_id,
                "name": spec.get("name", row.item_id),
                "effects": list(row.effects or []),
                "remainingSec": max(0, int((_aware(row.expires_at) - now).total_seconds())),
                "expiresAt": _aware(row.expires_at).isoformat(),
            }
        )
    return out


async def chest_luck(db: AsyncSession, user_id: int) -> float:
    return float((await active_effects(db, user_id)).get("chestLuck", 0.0))


async def craft_quality_bonus(db: AsyncSession, user_id: int) -> float:
    """制造品质药水 → _roll_quality 的 bonus（百分比转倍率）。"""
    return float((await active_effects(db, user_id)).get("craftQualityPct", 0.0)) / 100.0


async def craft_rarity_bonus(db: AsyncSession, user_id: int) -> float:
    """制造品阶概率药食 → 生产品阶权重的 craftRarityPct 来源（与专用装备同单位）。"""
    return float((await active_effects(db, user_id)).get("craftRarityPct", 0.0))


async def exp_gold_mods(db: AsyncSession, user_id: int) -> dict[str, float]:
    """经验/金币加成，供战斗结算叠加到 term_mods。"""
    effects = await active_effects(db, user_id)
    return {
        "expGainPct": float(effects.get("expGainPct", 0.0)),
        "goldGainPct": float(effects.get("goldGainPct", 0.0)),
    }


async def exp_bonus(db: AsyncSession, user_id: int) -> float:
    """生效中的药水 / 食物提供的经验加成（生产 / 采集 / 钓鱼共用）。"""
    return float((await active_effects(db, user_id)).get("expGainPct", 0.0))


async def effect_sources(db: AsyncSession, user_id: int, stat: str) -> list[tuple[str, float]]:
    """按来源列出生效中的药水 / 食物对某 stat 的贡献（名称, 值），供展示经验加成明细。"""
    out: list[tuple[str, float]] = []
    for row in await _rows(db, user_id):
        name = (dohdol_util.consumable_def(row.item_id) or {}).get("name", row.item_id)
        for effect in row.effects or []:
            if effect.get("stat") == stat:
                out.append((name, float(effect.get("value", 0.0))))
    return out


async def gather_bonus(db: AsyncSession, user_id: int) -> dict[str, float]:
    effects = await active_effects(db, user_id)
    return {"gatherYieldPct": float(effects.get("gatherYieldPct", 0.0))}


async def fish_bonus(db: AsyncSession, user_id: int) -> dict[str, float]:
    effects = await active_effects(db, user_id)
    return {
        "fishInsightPct": float(effects.get("fishInsightPct", 0.0)),
        "fishChancePct": float(effects.get("fishChancePct", 0.0)),
    }
