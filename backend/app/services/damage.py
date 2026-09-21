"""伤害计算。对应前端 `src/game/core/damage.ts`。

判定顺序：命中 → 直击 → 暴击 → 信念（恒定乘算）→ 随机浮动 → 减防。
来源：PRD 三属性 2.2 / 3.3
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.services.game_config import CONFIG
from app.services.stats import HeroStats


@dataclass
class DamageResult:
    amount: int
    is_crit: bool
    is_direct_hit: bool
    missed: bool = False


def hit_chance(stats: HeroStats, level_penalty_pct: float = 0.0) -> float:
    """命中率 = 基础命中 − 等级压制惩罚 + 命中属性，上限 99%。"""
    c = CONFIG.combat
    base = 1.0 - float(c["baseMissChance"])
    from app.services.balance import BALANCE
    chance = min(.99, base + stats.hit_rate_pct / 100.0)
    return max(BALANCE["normal"]["hitFloor"], chance * (1 - min(10.,max(0.,level_penalty_pct))/100))


def roll_damage(
    stats: HeroStats,
    potency_pct: float,
    damage_type: str,
    target_defense: float,
    skill_mult: float = 1.0,
    rng: random.Random | None = None,
) -> DamageResult:
    rng = rng or random
    c = CONFIG.combat

    power = stats.magic_attack if damage_type == "magical" else stats.attack
    raw = (potency_pct / 100.0) * power * skill_mult

    # 信念：恒定乘算
    raw *= 1.0 + stats.det_bonus_pct / 100.0

    # 直击
    is_dh = rng.random() * 100.0 < stats.dh_rate_pct
    if is_dh:
        raw *= float(c["directHitMultiplier"])

    # 暴击
    is_crit = rng.random() * 100.0 < stats.crit_rate_pct
    if is_crit:
        raw *= stats.crit_damage_pct / 100.0

    # 随机浮动
    lo, hi = c["randomFloat"]
    raw *= rng.uniform(float(lo), float(hi))

    # 减防（至少造成 10% 伤害）
    mitigated = max(raw * 0.10, raw - target_defense)
    return DamageResult(amount=max(1, int(mitigated)), is_crit=is_crit, is_direct_hit=is_dh)


def roll_incoming_damage(
    attacker_attack: float,
    potency_pct: float,
    target_defense: float,
    target_tenacity_pct: float = 0.0,
    damage_taken_pct: float = 0.0,
    level_taken_pct: float = 0.0,
    rng: random.Random | None = None,
) -> int:
    """怪物 → 英雄的伤害。

    `level_taken_pct` 为等级压制的「受伤增加」，在减防之后乘算（否则会被高防御吃掉）。
    """
    rng = rng or random
    raw = attacker_attack * (potency_pct / 100.0)
    raw *= 1.0 + damage_taken_pct / 100.0
    raw *= 1.0 - min(0.6, target_tenacity_pct / 100.0)
    mitigated = max(raw * 0.10, raw - target_defense)
    return max(1, int(mitigated * (1.0 + level_taken_pct / 100.0)))


def dodge_check(stats: HeroStats, rng: random.Random | None = None) -> bool:
    rng = rng or random
    return rng.random() * 100.0 < min(60.0, stats.dodge_pct)


def heal_amount(stats: HeroStats, pct: float) -> int:
    """治疗量 = 最大生命 × 百分比 × (1 + 信念增伤)。"""
    return int(stats.max_hp * pct * (1.0 + stats.det_bonus_pct / 100.0))
