"""战斗理论模型：用于服务端校验客户端上报的合理性。"""

from __future__ import annotations

from typing import Any

from app.services.damage import hit_chance
from app.services.game_config import CONFIG
from app.services.regions_util import (
    boss_stats,
    elite_chance,
    gold_bonus_from_terms,
    kills_required,
    level_penalty,
    monster_stats,
    spawn_interval,
)
from app.services.stats import HeroStats, skill_cooldown, skill_damage_multiplier

GCD = float(CONFIG.combat["gcdSeconds"])
BASIC_ATTACK_CD = float(CONFIG.combat["basicAttackCd"])
ADVENTURER_SKILL = {"id": "attack", "name": "普攻", "cd": BASIC_ATTACK_CD, "potency": 100, "damageType": "physical"}


def resolve_job_skills(stats: HeroStats) -> list[dict[str, Any]]:
    job = CONFIG.job_by_id.get(stats.job_id)
    if not job:
        return [ADVENTURER_SKILL]
    return list(job["skills"])


def damage_multiplier(stats: HeroStats) -> float:
    """期望增伤：信念 × 暴击 × 直击。"""
    det = 1.0 + stats.det_bonus_pct / 100.0
    crit = 1.0 + (stats.crit_rate_pct / 100.0) * (stats.crit_damage_pct / 100.0 - 1.0)
    dh = 1.0 + (stats.dh_rate_pct / 100.0) * (float(CONFIG.combat["directHitMultiplier"]) - 1.0)
    return max(0.0, det * crit * dh)


def theoretical_dps(
    stats: HeroStats,
    target_defense: float = 0.0,
    penalty: dict[str, float] | None = None,
) -> float:
    """按「CD 就绪即释放、受 GCD 约束」估算每秒伤害上限。

    penalty 为 `level_penalty()` 的结果：越级时命中与输出同步下降。
    """
    skills = resolve_job_skills(stats)
    skill_mult = skill_damage_multiplier(stats, stats.job_id)
    mult = damage_multiplier(stats)
    power = stats.power_attack

    potency_per_sec = 0.0
    cast_rate = 0.0
    max_potency = 0.0
    for skill in skills:
        cd = max(0.5, skill_cooldown(stats, float(skill["cd"]))) * (penalty or {}).get("cooldownMultiplier",1)
        potency = float(skill.get("potency", 0))
        cast_rate += 1.0 / cd
        potency_per_sec += potency / cd
        max_potency = max(max_potency, potency)

    # 受 GCD 约束
    gcd_cap = 1.0 / GCD
    if cast_rate > gcd_cap:
        potency_per_sec = potency_per_sec * (gcd_cap / cast_rate)
        cast_rate = gcd_cap
    potency_per_sec = min(potency_per_sec, gcd_cap * max_potency)

    attack_rate = max(cast_rate, 1.0 / BASIC_ATTACK_CD)
    gross = power * (potency_per_sec / 100.0) * mult * skill_mult
    mitigated = max(gross * 0.10, gross - target_defense * attack_rate)
    dps = max(1.0, mitigated)

    if penalty:
        dps *= hit_chance(stats, float(penalty.get("hitRatePenaltyPct", 0.0)))
        dps *= max(0.0, 1.0 - float(penalty.get("damageDealtPenaltyPct", 0.0)) / 100.0)
    return max(0.01, dps)


def effective_penalty(stats: HeroStats, region_id: int) -> dict[str, float]:
    """英雄相对地区的等级压制惩罚（越级时非零）。"""
    from app.services.balance import BALANCE, soft_penalty
    from app.services.valuation import hero_power
    return soft_penalty(hero_power(stats),BALANCE["regions"][str(region_id)]["recommendedPower"])


def theoretical_kill_seconds(
    stats: HeroStats,
    region_id: int,
    template_id: str = "normal",
    penalty: dict[str, float] | None = None,
) -> float:
    monster = monster_stats(region_id, template_id)
    dps = theoretical_dps(stats, float(monster["defense"]), penalty)
    return max(0.05, float(monster["hp"]) / dps)


def theoretical_boss_seconds(
    stats: HeroStats, region_id: int, penalty: dict[str, float] | None = None
) -> float:
    boss = boss_stats(region_id)
    dps = theoretical_dps(stats, float(boss["defense"]), penalty)
    return max(0.05, float(boss["hp"]) / dps)


def max_kills_in_seconds(
    stats: HeroStats,
    region_id: int,
    seconds: float,
    tolerance: float = 1.0,
    hero_level: int | None = None,
) -> float:
    """击杀数上限 = min(刷怪速率, 击杀速率) × 时间 × 容差。

    hero_level 用于纳入等级压制，避免越级英雄上报到等级匹配才有的击杀速率。
    """
    penalty = effective_penalty(stats,region_id)
    spawn_limited = seconds / max(0.1, spawn_interval(region_id))
    kill_limited = seconds / theoretical_kill_seconds(stats, region_id, penalty=penalty)
    return min(spawn_limited, kill_limited) * tolerance


def survival_seconds(stats: HeroStats, region_id: int, template_id: str = "normal") -> float:
    """英雄在无治疗情况下可存活时间。"""
    monster = monster_stats(region_id, template_id)
    per_hit = max(1.0, float(monster["attack"]) - stats.phys_def)
    hits_to_die = stats.max_hp / per_hit
    return hits_to_die * float(monster["attackInterval"])


def max_gold_for_kill(region_id: int, kind: str, hero_stats: HeroStats) -> float:
    """单只怪物的金币理论上限（含浮动上限与金币 Buff 上限）。"""
    region = CONFIG.region_by_id[region_id]
    multiplier = float(CONFIG.regions["goldMultipliers"].get(kind, 1.0))
    spread = float(CONFIG.regions["goldFloat"])
    bonus = gold_bonus_from_terms(hero_stats.term_mods, kind)
    bonus = min(float(CONFIG.regions["maxGoldBonus"]) * 100.0, max(0.0, bonus))
    return float(region["baseGold"]) * multiplier * (1.0 + spread) * (1.0 + bonus / 100.0) * 1.05 + 1.0


def region_requirements(region_id: int) -> dict[str, Any]:
    return {
        "killsRequired": kills_required(region_id),
        "spawnInterval": spawn_interval(region_id),
        "eliteChance": elite_chance({}),
    }
