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

export const ADVENTURER_SKILL: SkillLike = {
  id: 'basicAttack',
  name: '普攻',
  cd: data.combat.basicAttackCd as number,
  mpCost: 0,
  potency: 100,
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
  let mult = 1 + (stats.termMods.skillDamagePct ?? 0) / 100
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

export function isMagical(stats: HeroStats): boolean {
  const job = data.jobById[stats.jobId]
  return Boolean(job && job.mainAttr === 'int')
}

export function powerAttack(stats: HeroStats): number {
  return isMagical(stats) ? stats.magicAttack : stats.attack
}

/** 命中率 = 基础命中 − 等级压制惩罚 + 命中属性，上限 99%。与 `damage.py:hit_chance` 一致。 */
export function hitChance(stats: HeroStats, levelPenaltyPct = 0): number {
  const base = 1 - (data.combat.baseMissChance as number)
  const chance = base + stats.hitRatePct / 100 - levelPenaltyPct / 100
  return Math.max(0.05, Math.min(0.99, chance))
}

/** 一次伤害结算：命中 → 直击 → 暴击 → 信念 → 随机浮动 → 减防。来源：PRD 三属性 2.2 / 3.3 */
export function rollDamage(
  stats: HeroStats,
  potencyPct: number,
  damageType: 'physical' | 'magical',
  targetDefense: number,
  skillMult = 1,
  penalty: LevelPenalty | null = null,
  rand: () => number = Math.random,
): DamageRoll {
  if (penalty && rand() > hitChance(stats, penalty.hitRatePenaltyPct)) {
    return { amount: 0, isCrit: false, isDirectHit: false, missed: true }
  }

  let raw = (potencyPct / 100) * (damageType === 'magical' ? stats.magicAttack : stats.attack) * skillMult
  raw *= 1 + stats.detBonusPct / 100
  if (penalty) raw *= Math.max(0, 1 - penalty.damageDealtPenaltyPct / 100)

  const isDirectHit = rand() * 100 < stats.dhRatePct
  if (isDirectHit) raw *= data.combat.directHitMultiplier as number

  const isCrit = rand() * 100 < stats.critRatePct
  if (isCrit) raw *= stats.critDamagePct / 100

  const [lo, hi] = data.combat.randomFloat as [number, number]
  raw *= lo + rand() * (hi - lo)

  const mitigated = Math.max(raw * 0.1, raw - targetDefense)
  return { amount: Math.max(1, Math.floor(mitigated)), isCrit, isDirectHit, missed: false }
}

export function rollIncoming(
  attack: number,
  potencyPct: number,
  targetDefense: number,
  tenacityPct = 0,
  damageTakenPct = 0,
): number {
  let raw = attack * (potencyPct / 100)
  raw *= 1 + damageTakenPct / 100
  raw *= 1 - Math.min(0.6, tenacityPct / 100)
  const mitigated = Math.max(raw * 0.1, raw - targetDefense)
  return Math.max(1, Math.floor(mitigated))
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
    const cd = Math.max(0.5, skillCooldown(stats, skill.cd))
    castRate += 1 / cd
    potencyPerSec += skill.potency / cd
    maxPotency = Math.max(maxPotency, skill.potency)
  }
  const gcdCap = 1 / gcd
  if (castRate > gcdCap) {
    potencyPerSec *= gcdCap / castRate
    castRate = gcdCap
  }
  potencyPerSec = Math.min(potencyPerSec, gcdCap * maxPotency)

  const attackRate = Math.max(castRate, 1 / (data.combat.basicAttackCd as number))
  const gross = powerAttack(stats) * (potencyPerSec / 100) * damageMult * mult
  const dps = Math.max(1, Math.max(gross * 0.1, gross - targetDefense * attackRate))
  if (!penalty) return dps
  return Math.max(
    0.01,
    dps *
      hitChance(stats, penalty.hitRatePenaltyPct) *
      Math.max(0, 1 - penalty.damageDealtPenaltyPct / 100),
  )
}

export function secondsToKill(
  stats: HeroStats,
  monster: MonsterStats,
  penalty: LevelPenalty | null = null,
): number {
  return Math.max(0.05, monster.hp / estimateDps(stats, monster.defense, penalty))
}
