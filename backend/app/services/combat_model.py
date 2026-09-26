"""战斗理论模型：用于服务端校验客户端上报的合理性。"""

from __future__ import annotations

from typing import Any

from app.services.damage import hit_chance
from app.services.difficulty import monster_gold_multiplier, scale_player_stats
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


def signature_skill(stats: HeroStats) -> dict[str, Any] | None:
    """当前职业的绝技（招牌技能）；冒险者等无绝技职业返回 None。"""
    job = CONFIG.job_by_id.get(stats.job_id)
    return (job or {}).get("signature")


def signature_potency_per_sec(stats: HeroStats) -> float:
    """绝技对期望 DPS 的贡献（威力 / 有效充能秒数）。

    绝技为独立充能槽（不占 GCD、不耗魔力），只有伤害型（potency>0）需要计入模型。
    这里按「纯时间充能」取有效冷却：客户端另有「每次击杀 +chargePerKill」的加速，
    会让实际释放更快、模型略偏保守；该偏差由校验容差（2x）覆盖，不会误拒合法上报，
    也不会过分放宽击杀额度。
    """
    sig = signature_skill(stats)
    if not sig:
        return 0.0
    potency = float(sig.get("potency", 0) or 0)
    if potency <= 0:
        return 0.0
    charge_seconds = max(1.0, float(sig.get("chargeSeconds", 120) or 120))
    return potency / charge_seconds


def damage_multiplier(stats: HeroStats) -> float:
    """期望增伤：信念 × 暴击 × 直击。"""
    det = 1.0 + stats.det_bonus_pct / 100.0
    crit = 1.0 + (stats.crit_rate_pct / 100.0) * (stats.crit_damage_pct / 100.0 - 1.0)
    dh = 1.0 + (stats.dh_rate_pct / 100.0) * (float(CONFIG.combat["directHitMultiplier"]) - 1.0)
    return max(0.0, det * crit * dh)


def proc_dps_bonus(stats: HeroStats, base_dps: float, proc_rate: float) -> float:
    """装备触发效果（proc）的期望每秒收益。

    与前端 `battle.ts` 的实际结算口径对应：
      - 灼烧 / 中毒 / 裂伤：技能命中概率触发，每 3 秒结算一次攻击力 × potencyPct% 的持续伤害
        （不吃增伤，与 tickDots 一致；结算间隔变化不影响每秒量，故期望与逐秒结算相同）。
      - 疾风：技能命中概率获得限时攻速，等价于按攻速加成比例提升输出。

    `proc_rate` 为**技能出手率**（每秒技能命中次数）：onAttack proc 只由直接伤害技能触发，
    普通攻击不计入（与 battle.ts:resolveDamage 的 `isSkill` 门控一致）。

    仅镜像影响期望 DPS 的部分；凋零 / 失明 / 缓速 / 眩晕 / 反震 / 复仇 / 庇护 / 坚毅等只影响
    生存与资源，不进入模型（见 docs/enchant-terms-expansion-design.md 的镜像清单）。
    """
    cfg = CONFIG.combat.get("proc") or {}
    equip_proc = (CONFIG.combat.get("equipEffects") or {}).get("proc") or {}
    power = stats.power_attack
    extra = 0.0

    # 灼烧 / 中毒 / 裂伤：技能命中概率触发，每秒造成 `攻击力 × potencyPct%`（与 tickDots 同口径）。
    for key, stat_key, dot_cfg in (
        ("burn", "burnProcPct", cfg.get("burn")),
        ("poison", "poisonProcPct", cfg.get("poison")),
        ("bleed", "bleedProcPct", equip_proc.get("bleed")),
    ):
        if not dot_cfg:
            continue
        chance = max(0.0, stats.term_mods.get(stat_key, 0.0)) / 100.0
        if chance > 0:
            uptime = min(1.0, chance * proc_rate * float(dot_cfg["durationSec"]))
            extra += uptime * power * float(dot_cfg["potencyPct"]) / 100.0

    haste = cfg.get("haste")
    if haste:
        chance = max(0.0, stats.term_mods.get("hasteProcPct", 0.0)) / 100.0
        if chance > 0:
            uptime = min(1.0, chance * proc_rate * float(haste["durationSec"]))
            extra += uptime * float(haste["attackSpeedPct"]) / 100.0 * base_dps

    return extra


def equip_dps_multiplier(stats: HeroStats, mob_kind: str) -> float:
    """装备词条扩展机制的期望增伤系数（条件 / 资源转换 / 累计触发 / 动态成长）。

    与前端 `battle.ts` 口径对应，为避免合法上报被击杀额度拒绝，估算偏保守偏增益。
    生存 / 资源类机制（受击触发、格挡、护盾等）不在此处：护盾类词条（庇护 / 护盾强化 /
    受创蓄力 / 魔法盾 / 吸血盾）仅吸收伤害或消耗多余魔力，不提高期望 DPS，故不建模；
    护盾总量上限见 `combat.json:equipEffects.shield.capPctOfMaxHp`（前端与引擎同源读取）。
    """
    mods = stats.term_mods
    equip = CONFIG.combat.get("equipEffects") or {}
    cond = equip.get("conditional") or {}
    growth = equip.get("growth") or {}
    m = 1.0
    # 背水：生命低于阈值时生效，按约一半时间覆盖估算
    low_hp = max(0.0, mods.get("lowHpAttackPct", 0.0))
    if low_hp:
        m *= 1.0 + (low_hp / 100.0) * 0.5
    # 讨伐：仅对精英 / BOSS 生效
    boss_bonus = max(0.0, mods.get("bossDamagePct", 0.0))
    boss_kinds = (cond.get("boss") or {}).get("kinds") or ["elite", "boss"]
    if boss_bonus and mob_kind in boss_kinds:
        m *= 1.0 + boss_bonus / 100.0
    # 魔力灌注：按平均 50% 魔力估算
    surge = max(0.0, mods.get("mpSurgeDamagePct", 0.0))
    if surge:
        m *= 1.0 + (surge / 100.0) * 0.5
    # 处决：目标残血阶段按 20% 覆盖估算
    execute = max(0.0, mods.get("executePct", 0.0))
    if execute:
        m *= 1.0 + (execute / 100.0) * 0.2
    # 蓄势：累计触发的额外爆发，按 20% 增伤估算
    charge = max(0.0, mods.get("chargeBlastPct", 0.0))
    if charge:
        m *= 1.0 + (charge / 100.0) * 0.2
    # 动态成长：按层数上限的一半作为战斗内平均层数
    kill = max(0.0, mods.get("killStackAttackPct", 0.0))
    if kill:
        stacks = float((growth.get("killStackAttackPct") or {}).get("maxStacks", 10)) * 0.5
        m *= 1.0 + (kill * stacks) / 100.0
    skill = max(0.0, mods.get("skillStackDamagePct", 0.0))
    if skill:
        stacks = float((growth.get("skillStackDamagePct") or {}).get("maxStacks", 8)) * 0.5
        m *= 1.0 + (skill * stacks) / 100.0
    # 锐意（攻速成长）：攻速对 DPS 的放大按折半估算
    speed = max(0.0, mods.get("hitStackSpeedPct", 0.0))
    if speed:
        stacks = float((growth.get("hitStackSpeedPct") or {}).get("maxStacks", 10)) * 0.5
        m *= 1.0 + ((speed * stacks) / 100.0) * 0.5
    return m


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

    # 绝技（招牌技能）：独立充能槽、不占 GCD，伤害型绝技按有效充能时间折算期望 DPS。
    potency_per_sec += signature_potency_per_sec(stats)

    # 普攻与技能完全独立：按自身冷却出手（受攻速缩短），不占用 GCD、也不受技能可用性影响。
    # 普攻为物理伤害，取「攻击力」而非 power_attack（法系职业普攻同样吃攻击力）。
    # 普攻威力低于 100%，故不享受彩蛋「战斗爽」（该被动只作用于威力恰为 100% 的技能）。
    basic_cd = max(0.2, skill_cooldown(stats, BASIC_ATTACK_CD) / attack_speed_factor(stats))
    basic_rate = 1.0 / basic_cd

    # 「连击」：概率追加一次普攻（额外普攻按同一普攻威力结算）
    double_attack = max(0.0, stats.term_mods.get("doubleAttackPct", 0.0)) / 100.0
    extra_basic_rate = double_attack * basic_rate

    attack_rate = cast_rate * double_cast + basic_rate + extra_basic_rate
    # onAttack proc 只由技能命中触发：期望按「技能出手率」估算（不含普攻 / 连击）。
    proc_rate = cast_rate * double_cast
    gross = power * (potency_per_sec / 100.0) * mult * skill_mult
    gross += stats.attack * (BASIC_ATTACK_POTENCY / 100.0) * (basic_rate + extra_basic_rate) * mult * skill_mult
    mitigated = max(gross * 0.10, gross - target_defense * attack_rate)
    # 「破防」：降低目标防御，等效于减少减防项（按技能触发的期望覆盖率计入）
    equip_proc = (CONFIG.combat.get("equipEffects") or {}).get("proc") or {}
    def_break = equip_proc.get("defBreak")
    db_chance = max(0.0, stats.term_mods.get("defBreakProcPct", 0.0)) / 100.0
    if def_break and db_chance > 0:
        uptime = min(1.0, db_chance * proc_rate * float(def_break["durationSec"]))
        mitigated += uptime * float(def_break["defenseDownPct"]) / 100.0 * target_defense * attack_rate
    # 彩蛋技能增伤按平均覆盖计入，避免合法的高输出上报被击杀额度误判
    dps = max(1.0, mitigated) * dps_uplift(stats.egg_id)
    # 装备词条扩展机制的期望增伤（条件 / 资源转换 / 累计触发 / 动态成长），与前端 battle.ts 同源
    dps *= equip_dps_multiplier(stats, mob_kind)
    # 装备触发效果（灼烧 / 中毒 / 裂伤 / 疾风）的期望收益
    dps += proc_dps_bonus(stats, dps, proc_rate)

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
    difficulty: int = 0,
) -> float:
    monster = monster_stats(region_id, template_id, difficulty)
    dps = theoretical_dps(stats, float(monster["defense"]), penalty, mob_kind=template_id)
    return max(0.05, float(monster["hp"]) / dps)


def theoretical_boss_seconds(
    stats: HeroStats, region_id: int, penalty: dict[str, float] | None = None, difficulty: int = 0
) -> float:
    boss = boss_stats(region_id, difficulty)
    dps = theoretical_dps(stats, float(boss["defense"]), penalty, mob_kind="boss")
    return max(0.05, float(boss["hp"]) / dps)


def max_kills_in_seconds(
    stats: HeroStats,
    region_id: int,
    seconds: float,
    tolerance: float = 1.0,
    hero_level: int | None = None,
    difficulty: int = 0,
) -> float:
    """击杀数上限 = min(刷怪速率, 击杀速率) × 时间 × 容差。

    hero_level 用于纳入等级压制，避免越级英雄上报到等级匹配才有的击杀速率。
    difficulty 用于地区战斗的难度等级：怪物血量按难度放大、玩家攻击按难度缩小。
    """
    penalty = effective_penalty(stats, region_id)
    # 难度只缩小玩家的战斗输出；战力口径（effective_penalty）仍用未缩放的 stats。
    scaled = scale_player_stats(stats, difficulty)
    spawn_limited = seconds / max(0.1, spawn_interval(region_id))
    kill_limited = seconds / theoretical_kill_seconds(
        scaled, region_id, penalty=penalty, difficulty=difficulty
    )
    return min(spawn_limited, kill_limited) * tolerance


def survival_seconds(stats: HeroStats, region_id: int, template_id: str = "normal") -> float:
    """英雄在无治疗情况下可存活时间。"""
    monster = monster_stats(region_id, template_id)
    per_hit = max(1.0, float(monster["attack"]) - stats.phys_def)
    hits_to_die = stats.max_hp / per_hit
    return hits_to_die * float(monster["attackInterval"])


def max_gold_for_kill(
    region_id: int, kind: str, hero_stats: HeroStats, difficulty: int = 0
) -> float:
    """单只怪物的金币理论上限（含浮动上限、金币 Buff 上限与难度加成）。"""
    region = CONFIG.region_by_id[region_id]
    multiplier = float(CONFIG.regions["goldMultipliers"].get(kind, 1.0))
    spread = float(CONFIG.regions["goldFloat"])
    bonus = gold_bonus_from_terms(hero_stats.term_mods, kind)
    bonus = min(float(CONFIG.regions["maxGoldBonus"]) * 100.0, max(0.0, bonus))
    base = float(region["baseGold"]) * multiplier * (1.0 + spread) * (1.0 + bonus / 100.0) * 1.05 + 1.0
    return base * monster_gold_multiplier(difficulty)


def region_requirements(region_id: int) -> dict[str, Any]:
    return {
        "killsRequired": kills_required(region_id),
        "spawnInterval": spawn_interval(region_id),
        "eliteChance": elite_chance({}),
    }
