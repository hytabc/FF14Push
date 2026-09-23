"""品阶概率的「幸运来源」：远征 / 高难通关（难度加权·仅首通）与通用归一化。

抽箱品阶概率与生产品阶概率共用同一套来源机制：

    p = Σ weight × min(值 / ref, 1)      权重合计 = 1，仅全部来源拉满时 p = 1

生产直接把 p 当作进度 t；抽箱用 luck = luckMax × p。各 ref 为对应来源的真实
最大值（含太古词条），因此「上限」只有所有来源全满才能达到。
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoopProgress, RaidProgress
from app.services.game_config import CONFIG
from app.services.multiplayer_config import DUNGEONS, MULTIPLAYER


def _difficulty_weights(cfg: Mapping[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in (cfg.get("difficultyWeights") or {}).items()}


def coop_clear_ref() -> float:
    """远征通关积分上限 = 全部副本难度权重之和（12 本全通）。"""
    weights = _difficulty_weights(MULTIPLAYER)
    return sum(weights.get(str(d.get("difficulty")), 0.0) for d in DUNGEONS.values())


def raid_clear_ref() -> float:
    """高难通关积分上限 = 全部副本难度权重之和（6 本全通）。"""
    weights = _difficulty_weights(CONFIG.raids)
    return sum(weights.get(str(r.get("difficulty")), 0.0) for r in CONFIG.raids["raids"])


async def coop_clear_score(db: AsyncSession, user_id: int) -> float:
    """远征通关积分：仅计首通（clears>0），按副本难度加权求和；重复刷不叠加。"""
    cleared = set(
        (
            await db.scalars(
                select(CoopProgress.dungeon_id).where(
                    CoopProgress.user_id == user_id, CoopProgress.clears > 0
                )
            )
        ).all()
    )
    weights = _difficulty_weights(MULTIPLAYER)
    return sum(
        weights.get(str(DUNGEONS[did].get("difficulty")), 0.0)
        for did in cleared
        if did in DUNGEONS
    )


async def raid_clear_score(db: AsyncSession, user_id: int) -> float:
    """高难通关积分：仅计首通（cleared），按副本难度加权求和；重复刷不叠加。"""
    cleared = set(
        (
            await db.scalars(
                select(RaidProgress.raid_id).where(
                    RaidProgress.user_id == user_id, RaidProgress.cleared.is_(True)
                )
            )
        ).all()
    )
    weights = _difficulty_weights(CONFIG.raids)
    return sum(
        weights.get(str(CONFIG.raid_by_id[rid].get("difficulty")), 0.0)
        for rid in cleared
        if rid in CONFIG.raid_by_id
    )


def luck_progress(
    sources: Mapping[str, Any], values: Mapping[str, float]
) -> tuple[float, list[dict[str, Any]]]:
    """通用归一化：返回 (p, 来源明细)。

    p = Σ weight × min(值 / ref, 1)，夹在 [0, 1]；明细供前端展示「当前值 / 参考值 / 权重」。
    """
    factors: list[dict[str, Any]] = []
    total = 0.0
    for key, spec in sources.items():
        weight = float(spec.get("weight", 0.0))
        ref = float(spec.get("ref", 1.0)) or 1.0
        value = max(0.0, float(values.get(key, 0.0)))
        norm = min(1.0, value / ref)
        total += weight * norm
        factors.append(
            {"key": key, "value": value, "ref": ref, "norm": norm, "weight": weight}
        )
    return min(1.0, max(0.0, total)), factors
