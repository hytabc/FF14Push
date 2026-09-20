/** 小怪 / BOSS 属性推导。必须与后端 `services/regions_util.py` 保持一致。 */
import data from '@shared/schema'

import type { BossSkill, MonsterStats, RegionDef } from '../types'

const REF = data.monsters.reference as {
  heroAttack: { base: number; perLevel: number }
  heroHp: { base: number; perLevel: number }
  refPotencyPerSecond: number
  targetKillSeconds: number
  targetSurvivalSeconds: number
  defenseRatioOfAttack: number
}
const MONSTER_INTERVAL = data.monsters.monsterAttackInterval
const TEMPLATE_BY_ID = new Map(data.monsters.templates.map((t) => [t.id, t]))
const BOSS_TYPE_BY_ID = new Map(data.bosses.types.map((t) => [t.id, t]))

export function regionLevel(region: RegionDef): number {
  return region.levelMin
}

function refAttack(level: number): number {
  return REF.heroAttack.base + REF.heroAttack.perLevel * (level - 1)
}

function refHp(level: number): number {
  return REF.heroHp.base + REF.heroHp.perLevel * (level - 1)
}

function monsterBaseStats(level: number) {
  const atk = refAttack(level)
  const hp = refHp(level)
  return {
    hp: (atk * REF.refPotencyPerSecond) / 100 * REF.targetKillSeconds,
    attack: hp / (REF.targetSurvivalSeconds / MONSTER_INTERVAL),
    defense: atk * REF.defenseRatioOfAttack,
  }
}

export function monsterStats(region: RegionDef, templateId: string): MonsterStats {
  const template = TEMPLATE_BY_ID.get(templateId)!
  const base = monsterBaseStats(regionLevel(region))
  const m = template.multipliers
  return {
    id: templateId,
    regionId: region.id,
    name: `${region.name}·${template.examples[0]}`,
    templateId,
    kind: templateId === 'elite' ? 'elite' : 'normal',
    hp: round(base.hp * m.hp),
    attack: round(base.attack * m.attack),
    defense: round(base.defense * m.defense),
    attackInterval: round(MONSTER_INTERVAL / m.attackSpeed, 2),
    level: regionLevel(region),
  }
}

export function bossStats(region: RegionDef): MonsterStats {
  const base = monsterBaseStats(regionLevel(region))
  const mid = (range: [number, number]) => (range[0] + range[1]) / 2
  const bossType = BOSS_TYPE_BY_ID.get(region.bossType)
  return {
    id: `boss_r${region.id}`,
    regionId: region.id,
    name: region.bossName,
    templateId: 'boss',
    bossType: region.bossType,
    kind: 'boss',
    hp: round(base.hp * mid(data.bosses.hpMultiplierRange as [number, number])),
    attack: round(base.attack * mid(data.bosses.attackMultiplierRange as [number, number])),
    defense: round(base.defense * mid(data.bosses.defenseMultiplierRange as [number, number])),
    attackInterval: data.bosses.attackInterval,
    level: regionLevel(region),
    skills: (bossType?.skills ?? []) as unknown as BossSkill[],
  }
}

function round(value: number, digits = 1): number {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

export function getRegion(regionId: number): RegionDef {
  return data.regions.regions.find((r) => r.id === regionId)!
}

export function regionTemplates() {
  return data.monsters.templates
}

export function eliteChance(termMods: Record<string, number>): number {
  return Math.min(1, data.monsters.eliteBaseChance + (termMods.eliteChancePct ?? 0) / 100)
}

/** 金币掉落（仅用于表现层预估，真实结算在服务端）。 */
export function goldRange(regionId: number, kind: 'normal' | 'elite' | 'boss') {
  const region = getRegion(regionId)
  const multiplier = data.regions.goldMultipliers[kind] ?? 1
  const spread = data.regions.goldFloat
  const base = region.baseGold * multiplier
  return {
    min: Math.floor(base * (1 - spread)),
    max: Math.ceil(base * (1 + spread)),
  }
}
