"""战斗理论模型：用于服务端校验客户端上报的合理性。"""

from __future__ import annotations

from typing import Any

from app.services.damage import hit_chance
from app.services.egg_heroes import dps_uplift, normal_mob_potency100_bonus, skills_for
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
BASIC_ATTACK_POTENCY = float(CONFIG.combat["basicAttackPotency"])
MAX_ATTACK_SPEED_FACTOR = 2.0
ADVENTURER_SKILL = {"id": "attack", "name": "普攻", "cd": BASIC_ATTACK_CD, "potency": BASIC_ATTACK_POTENCY, "damageType": "physical"}


def attack_speed_factor(stats: HeroStats) -> float:
    """攻速系数 = 1 + 攻击速度% / 100，上限 2.0（与前端 combat.ts:attackSpeedFactor 一致）。"""
    return min(MAX_ATTACK_SPEED_FACTOR, 1.0 + max(0.0, stats.attack_speed_pct) / 100.0)


def resolve_job_skills(stats: HeroStats) -> list[dict[str, Any]]:
    job = CONFIG.job_by_id.get(stats.job_id)
    base = list(job["skills"]) if job else [ADVENTURER_SKILL]
    egg = skills_for(stats.egg_id, stats.job_id)
    if not egg:
        return base
    egg_skills, replace = egg
    return list(egg_skills) if replace else [*egg_skills, *base]


def damage_multiplier(stats: HeroStats) -> float:
    """期望增伤：信念 × 暴击 × 直击。"""
    det = 1.0 + stats.det_bonus_pct / 100.0
    crit = 1.0 + (stats.crit_rate_pct / 100.0) * (stats.crit_damage_pct / 100.0 - 1.0)
    dh = 1.0 + (stats.dh_rate_pct / 100.0) * (float(CONFIG.combat["directHitMultiplier"]) - 1.0)
    return max(0.0, det * crit * dh)


def proc_dps_bonus(stats: HeroStats, base_dps: float, attack_rate: float) -> float:
    """装备触发效果（proc）的期望每秒收益。

    与前端 `battle.ts` 的实际结算口径对应：
      - 灼烧 / 中毒：命中概率触发，每秒造成 `攻击力 × potencyPct%`（不吃增伤，与 tickDots 一致）。
      - 疾风：命中概率获得限时攻速，等价于按攻速加成比例提升输出。
    """
    cfg = CONFIG.combat.get("proc") or {}
    power = stats.power_attack
    extra = 0.0

    # 灼烧 / 中毒：命中概率触发，每秒造成 `攻击力 × potencyPct%`（不吃增伤，与 tickDots 一致）。
    for key, stat_key in (("burn", "burnProcPct"), ("poison", "poisonProcPct")):
        dot = cfg.get(key)
        if not dot:
            continue
        chance = max(0.0, stats.term_mods.get(stat_key, 0.0)) / 100.0
        if chance > 0:
            uptime = min(1.0, chance * attack_rate * float(dot["durationSec"]))
            extra += uptime * power * float(dot["potencyPct"]) / 100.0

    haste = cfg.get("haste")
    if haste:
        chance = max(0.0, stats.term_mods.get("hasteProcPct", 0.0)) / 100.0
        if chance > 0:
            uptime = min(1.0, chance * attack_rate * float(haste["durationSec"]))
            extra += uptime * float(haste["attackSpeedPct"]) / 100.0 * base_dps

    return extra


def theoretical_dps(
    stats: HeroStats,
    target_defense: float = 0.0,
    penalty: dict[str, float] | None = None,
    mob_kind: str = "normal",
) -> float:
    """按「CD 就绪即释放、受 GCD 约束」估算每秒伤害上限。

    penalty 为 `level_penalty()` 的结果：越级时命中与输出同步下降。
    mob_kind 用于彩蛋被动「战斗爽」：仅对战普通怪物（normal）时，威力恰为 100% 的技能
    威力翻倍；精英 / BOSS 不受影响。
    """
    skills = resolve_job_skills(stats)
    skill_mult = skill_damage_multiplier(stats, stats.job_id)
    mult = damage_multiplier(stats)
    power = stats.power_attack

    potency_bonus = normal_mob_potency100_bonus(stats.egg_id) if mob_kind == "normal" else 0.0

    potency_per_sec = 0.0
    cast_rate = 0.0
    max_potency = 0.0
    for skill in skills:
        cd = max(0.5, skill_cooldown(stats, float(skill["cd"]))) * (penalty or {}).get("cooldownMultiplier",1)
        potency = float(skill.get("potency", 0))
        if potency_bonus > 0 and potency == 100:
            potency *= 1.0 + potency_bonus
        cast_rate += 1.0 / cd
        potency_per_sec += potency / cd
        max_potency = max(max_potency, potency)

    # 技能受 GCD 约束。攻速只在客户端模拟里缩短 GCD；技能循环不随攻速放大。
    gcd_cap = 1.0 / GCD
    if cast_rate > gcd_cap:
        potency_per_sec = potency_per_sec * (gcd_cap / cast_rate)
        cast_rate = gcd_cap
    potency_per_sec = min(potency_per_sec, gcd_cap * max_potency)

    # 装备「双重施法」：概率额外释放一次，第二次不占 GCD，故在 GCD 夹取之后放大技能输出与出手频率。
    double_cast = 1.0 + max(0.0, stats.term_mods.get("doubleCastPct", 0.0)) / 100.0
    potency_per_sec *= double_cast

    # 普攻与技能完全独立：按自身冷却出手（受攻速缩短），不占用 GCD、也不受技能可用性影响。
    # 普攻为物理伤害，取「攻击力」而非 power_attack（法系职业普攻同样吃攻击力）。
    # 普攻威力低于 100%，故不享受彩蛋「战斗爽」（该被动只作用于威力恰为 100% 的技能）。
    basic_cd = max(0.2, skill_cooldown(stats, BASIC_ATTACK_CD) / attack_speed_factor(stats))
    basic_rate = 1.0 / basic_cd

    attack_rate = cast_rate * double_cast + basic_rate
    gross = power * (potency_per_sec / 100.0) * mult * skill_mult
    gross += stats.attack * (BASIC_ATTACK_POTENCY / 100.0) * basic_rate * mult * skill_mult
    mitigated = max(gross * 0.10, gross - target_defense * attack_rate)
    # 彩蛋技能增伤按平均覆盖计入，避免合法的高输出上报被击杀额度误判
    dps = max(1.0, mitigated) * dps_uplift(stats.egg_id)
    # 装备触发效果（灼烧 / 疾风）的期望收益
    dps += proc_dps_bonus(stats, dps, attack_rate)

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
    dps = theoretical_dps(stats, float(monster["defense"]), penalty, mob_kind=template_id)
    return max(0.05, float(monster["hp"]) / dps)


def theoretical_boss_seconds(
    stats: HeroStats, region_id: int, penalty: dict[str, float] | None = None
) -> float:
    boss = boss_stats(region_id)
    dps = theoretical_dps(stats, float(boss["defense"]), penalty, mob_kind="boss")
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
