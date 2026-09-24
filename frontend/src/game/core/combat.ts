/** 伤害与技能。必须与后端 `services/damage.py` / `stats.py` 保持一致。 */
import data from '@shared/schema'

import type { HeroStats, MonsterStats } from '../types'
import type { LevelPenalty } from './regions'

export interface DamageRoll {
  amount: number
  isCrit: boolean
  isDirectHit: boolean
  missed: boolean
}

export interface SkillLike {
  id: string
  name: string
  cd: number
  mpCost: number
  potency: number
  damageType: 'physical' | 'magical'
  target: 'single' | 'aoe' | 'self'
  priority: 1 | 2 | 3
  effects: Array<Record<string, unknown>>
}

/** 普攻威力（% 攻击力）：刻意低于技能威力，见 `combat.json:basicAttackPotency`。 */
export const BASIC_ATTACK_POTENCY = data.combat.basicAttackPotency as number

export const ADVENTURER_SKILL: SkillLike = {
  id: 'basicAttack',
  name: '普攻',
  cd: data.combat.basicAttackCd as number,
  mpCost: 0,
  potency: BASIC_ATTACK_POTENCY,
  damageType: 'physical',
  target: 'single',
  priority: 3,
  effects: [],
}

export function jobSkills(jobId: string): SkillLike[] {
  const job = data.jobById[jobId]
  if (!job) return [ADVENTURER_SKILL]
  return job.skills as unknown as SkillLike[]
}

export function skillDamageMultiplier(stats: HeroStats, jobId: string): number {
  let mult = 1 + ((stats.termMods.skillDamagePct ?? 0) + (stats.termMods.recklessPct ?? 0)) / 100
  const job = data.jobById[jobId]
  if (job && job.mainAttr === stats.mainAttr && jobId !== 'adventurer') {
    mult *= 1 + data.heroes.jobMatchBonus.skillDamagePct
  }
  return mult
}

export function skillCooldown(stats: HeroStats, baseCd: number): number {
  const reduce = Math.min(0.7, (stats.termMods.cdReducePct ?? 0) / 100 + stats.hastePct / 100)
  return Math.max(0.5, baseCd * (1 - reduce))
}

/** 治疗 / 护盾类技能的效果类型（用于判定治疗职业技能的额外耗蓝）。 */
export const HEAL_SKILL_EFFECT_TYPES = ['heal', 'healOverTime', 'fullHeal', 'healingBuff', 'shield']

export function isHealingSkill(skill: SkillLike): boolean {
  return (skill.effects ?? []).some((e) => HEAL_SKILL_EFFECT_TYPES.includes(String(e.type)))
}

/**
 * 技能实际耗蓝：`mpCost × 伤害类型系数`；治疗职业（role === 'healer'）的治疗 / 护盾类技能
 * 额外收取「最大魔力 × `heroes.json:mp.healSkillCostMaxMpPct`」，避免固定耗蓝被膨胀的蓝条与
 * 回蓝掩盖、形成无限自愈。与 `battle.ts` 的结算同源，供技能面板展示。
 */
export function skillMpCost(stats: HeroStats, skill: SkillLike): number {
  const scale =
    skill.damageType === 'magical'
      ? data.heroes.mp.magicalSkillCostScale
      : data.heroes.mp.physicalSkillCostScale
  let cost = skill.mpCost * scale
  const pct = Number(data.heroes.mp.healSkillCostMaxMpPct ?? 0)
  if (pct > 0 && data.jobById[stats.jobId]?.role === 'healer' && isHealingSkill(skill)) {
    cost += stats.maxMp * pct
  }
  return Math.floor(cost)
}

/** 攻速系数 = 1 + 攻击速度% / 100，上限 2.0。用于缩短 GCD 与普攻间隔（服务端不建模出手频率）。 */
export const MAX_ATTACK_SPEED_FACTOR = 2

export function attackSpeedFactor(stats: HeroStats): number {
  return Math.min(MAX_ATTACK_SPEED_FACTOR, 1 + Math.max(0, stats.attackSpeedPct) / 100)
}

export function isMagical(stats: HeroStats): boolean {
  const job = data.jobById[stats.jobId]
  return Boolean(job && job.mainAttr === 'int')
}

export function powerAttack(stats: HeroStats): number {
  return isMagical(stats) ? stats.magicAttack : stats.attack
}

/** 命中率 = 基础命中 − 等级压制惩罚 + 命中属性，上限 99%。与 `damage.py:hit_chance` 一致。 */
export function hitChance(stats: HeroStats, levelPenaltyPct = 0, floor = .8): number {
  const base = 1 - (data.combat.baseMissChance as number)
  const chance = Math.min(0.99, base + stats.hitRatePct / 100)
  return Math.max(floor, chance * (1 - Math.min(10, Math.max(0, levelPenaltyPct)) / 100))
}

/** 一次伤害结算：命中 → 直击 → 暴击 → 信念 → 随机浮动 → BOSS 抗性 → 减防。来源：PRD 三属性 2.2 / 3.3 */
export function rollDamage(
  stats: HeroStats,
  potencyPct: number,
  damageType: 'physical' | 'magical',
  targetDefense: number,
  skillMult = 1,
  penalty: LevelPenalty | null = null,
  resistancePct = 0,
  rand: () => number = Math.random,
): DamageRoll {
  if (penalty && rand() > hitChance(stats, penalty.hitRatePenaltyPct, penalty.hitFloor)) {
    return { amount: 0, isCrit: false, isDirectHit: false, missed: true }
  }

  let raw = (potencyPct / 100) * (damageType === 'magical' ? stats.magicAttack : stats.attack) * skillMult
  raw *= 1 + stats.detBonusPct / 100

  const isDirectHit = rand() * 100 < stats.dhRatePct
  if (isDirectHit) raw *= data.combat.directHitMultiplier as number

  const isCrit = rand() * 100 < stats.critRatePct
  if (isCrit) raw *= stats.critDamagePct / 100

  const [lo, hi] = data.combat.randomFloat as [number, number]
  raw *= lo + rand() * (hi - lo)

  // BOSS 抗性：直接削减最终伤害（高难副本 BOSS 自带抗性）
  raw *= Math.max(0, 1 - Math.min(90, resistancePct) / 100)

  const mitigated = Math.max(raw * 0.1, raw - targetDefense) * (1 - (penalty?.damageDealtPenaltyPct ?? 0) / 100)
  return { amount: Math.max(1, Math.floor(mitigated)), isCrit, isDirectHit, missed: false }
}

export function rollIncoming(
  attack: number,
  potencyPct: number,
  targetDefense: number,
  tenacityPct = 0,
  damageTakenPct = 0,
  levelTakenPct = 0,
): number {
  let raw = attack * (potencyPct / 100)
  raw *= 1 + damageTakenPct / 100
  raw *= 1 - Math.min(0.6, tenacityPct / 100)
  const mitigated = Math.max(raw * 0.1, raw - targetDefense)
  // 等级压制的「受伤增加」在减防之后乘算，否则会被高防御吃掉、越级仍然能磨过去
  return Math.max(1, Math.floor(mitigated * (1 + levelTakenPct / 100)))
}

export function monsterHitChance(dodgePct: number): number {
  return Math.max(0, 1 - Math.min(60, dodgePct) / 100)
}

/** 期望每秒伤害（用于展示 DPS，与后端 combat_model 同源）。 */
export function estimateDps(
  stats: HeroStats,
  targetDefense: number,
  penalty: LevelPenalty | null = null,
): number {
  const skills = jobSkills(stats.jobId)
  const gcd = data.combat.gcdSeconds as number
  const mult = skillDamageMultiplier(stats, stats.jobId)
  const damageMult =
    (1 + stats.detBonusPct / 100) *
    (1 + (stats.critRatePct / 100) * (stats.critDamagePct / 100 - 1)) *
    (1 + (stats.dhRatePct / 100) * ((data.combat.directHitMultiplier as number) - 1))

  let potencyPerSec = 0
  let castRate = 0
  let maxPotency = 0
  for (const skill of skills) {
    // 普攻单独建模（与技能完全独立），避免冒险者职业重复计入。
    if (skill.id === ADVENTURER_SKILL.id) continue
    const cd = Math.max(0.5, skillCooldown(stats, skill.cd))
    castRate += 1 / cd
    potencyPerSec += skill.potency / cd
    maxPotency = Math.max(maxPotency, skill.potency)
  }
  // 与后端 combat_model 一致：模型只计技能循环，不随攻速放大技能 DPS（攻速在 battle.ts 中缩短 GCD）
  const gcdCap = 1 / gcd
  if (castRate > gcdCap) {
    potencyPerSec *= gcdCap / castRate
    castRate = gcdCap
  }
  potencyPerSec = Math.min(potencyPerSec, gcdCap * maxPotency)

  // 装备「双重施法」：概率额外释放一次，第二次不占 GCD，故在 GCD 夹取之后放大技能输出与出手频率。
  const doubleCast = 1 + Math.max(0, stats.termMods.doubleCastPct ?? 0) / 100
  potencyPerSec *= doubleCast

  // 绝技（招牌技能）：独立充能槽、不占 GCD，伤害型绝技按有效充能时间折算期望 DPS（与后端 combat_model 同源）。
  const sig = data.jobById[stats.jobId]?.signature
  if (sig && sig.potency > 0) {
    potencyPerSec += sig.potency / Math.max(1, sig.chargeSeconds)
  }

  // 普攻与技能完全独立：按自身冷却出手（受攻速缩短），不占用 GCD / 不受技能可用性影响。
  const basicCd = Math.max(
    0.2,
    skillCooldown(stats, data.combat.basicAttackCd as number) / attackSpeedFactor(stats),
  )
  const basicRate = 1 / basicCd

  const attackRate = castRate * doubleCast + basicRate
  // 连击：概率追加一次普攻（普攻与技能独立，附加普攻按同一普攻威力结算）
  const doubleAttack = Math.max(0, stats.termMods.doubleAttackPct ?? 0) / 100
  const extraBasicRate = doubleAttack * basicRate
  const gross =
    powerAttack(stats) * (potencyPerSec / 100) * damageMult * mult +
    stats.attack * (BASIC_ATTACK_POTENCY / 100) * (basicRate + extraBasicRate) * damageMult * mult
  let dps = Math.max(1, Math.max(gross * 0.1, gross - targetDefense * (attackRate + extraBasicRate)))
  dps += procDpsBonus(stats, dps, attackRate)
  if (!penalty) return dps
  return Math.max(
    0.01,
    dps *
      hitChance(stats, penalty.hitRatePenaltyPct, penalty.hitFloor) *
      Math.max(0, 1 - penalty.damageDealtPenaltyPct / 100),
  )
}

/** 装备触发效果（proc）的期望每秒收益。与后端 `combat_model.py:proc_dps_bonus` 同源。 */
export function procDpsBonus(stats: HeroStats, baseDps: number, attackRate: number): number {
  const proc = (data.combat.proc ?? {}) as {
    burn?: { potencyPct: number; durationSec: number; tickSec: number }
    poison?: { potencyPct: number; durationSec: number; tickSec: number }
    haste?: { attackSpeedPct: number; durationSec: number }
  }
  const equip = ((data.combat as Record<string, any>).equipEffects?.proc ?? {}) as {
    bleed?: { potencyPct: number; durationSec: number }
  }
  const power = powerAttack(stats)
  let extra = 0
  // 灼烧 / 中毒 / 裂伤：命中概率触发，每秒造成 攻击力 × potencyPct%（不吃增伤，与 battle.ts:tickDots 一致）。
  const dotProcs: Array<[{ potencyPct: number; durationSec: number } | undefined, number]> = [
    [proc.burn, Math.max(0, stats.termMods.burnProcPct ?? 0)],
    [proc.poison, Math.max(0, stats.termMods.poisonProcPct ?? 0)],
    [equip.bleed, Math.max(0, stats.termMods.bleedProcPct ?? 0)],
  ]
  for (const [dot, chancePct] of dotProcs) {
    if (!dot || chancePct <= 0) continue
    const uptime = Math.min(1, (chancePct / 100) * attackRate * dot.durationSec)
    extra += uptime * power * (dot.potencyPct / 100)
  }
  const haste = proc.haste
  if (haste) {
    const chance = Math.max(0, stats.termMods.hasteProcPct ?? 0) / 100
    if (chance > 0) {
      const uptime = Math.min(1, chance * attackRate * haste.durationSec)
      extra += (uptime * haste.attackSpeedPct) / 100 * baseDps
    }
  }
  return extra
}

export function secondsToKill(
  stats: HeroStats,
  monster: MonsterStats,
  penalty: LevelPenalty | null = null,
): number {
  return Math.max(0.05, monster.hp / estimateDps(stats, monster.defense, penalty))
}
