import { describe, expect, it } from 'vitest'

import data from '@shared/schema'

import { chestLuckExplain, craftRarityExplain, equipEffectExplain, statExplain, type StatKey } from './explanations'
import type { ChestRarityLuck, CraftOdds, HeroStats, RarityId, StatBreakdown } from './types'

function fakeCraft(): CraftOdds {
  const odds = Object.fromEntries(data.rarities.order.map((r) => [r, 0])) as Record<RarityId, number>
  odds.common = 0.28
  odds.mythic = 0.5
  return {
    odds,
    luck: 0.5,
    mythicCap: 0.2,
    sources: [
      { key: 'heroLevel', value: 50, ref: 100, norm: 0.5, weight: 0.15 },
      { key: 'clearedRegions', value: 20, ref: 40, norm: 0.5, weight: 0.1 },
      { key: 'prodLevel', value: 25, ref: 50, norm: 0.5, weight: 0.15 },
      { key: 'gearPct', value: 30, ref: 186.1, norm: 0.16, weight: 0.25 },
      { key: 'consumablePct', value: 21, ref: 21, norm: 1, weight: 0.1 },
      { key: 'coopClears', value: 12, ref: 33, norm: 0.36, weight: 0.15 },
      { key: 'raidClears', value: 4, ref: 10, norm: 0.4, weight: 0.1 },
    ],
  }
}

function fakeChestLuck(): ChestRarityLuck {
  return {
    luck: 0.42,
    luckMax: 1,
    sources: [
      { key: 'clearedRegions', value: 20, ref: 40, norm: 0.5, weight: 0.3 },
      { key: 'gearPct', value: 30, ref: 137.5, norm: 0.218, weight: 0.25 },
      { key: 'consumablePct', value: 0.21, ref: 0.21, norm: 1, weight: 0.15 },
      { key: 'coopClears', value: 12, ref: 33, norm: 0.36, weight: 0.15 },
      { key: 'raidClears', value: 0, ref: 10, norm: 0, weight: 0.1 },
      { key: 'egg', value: 0, ref: 0.1, norm: 0, weight: 0.05 },
    ],
  }
}

describe('craftRarityExplain', () => {
  it('explains the scaling formula from shared config without player context', () => {
    const text = craftRarityExplain().lines.join('\n')
    expect(text).toContain('rarityScaling')
    expect(text).toContain('20%')
  })

  it('lists every source and the resolved odds with player context', () => {
    const text = craftRarityExplain(fakeCraft()).lines.join('\n')
    expect(text).toContain('英雄等级')
    expect(text).toContain('通关地区数')
    expect(text).toContain('生产等级')
    expect(text).toContain('专用装备品阶幸运')
    expect(text).toContain('制造品阶概率料理 / 秘药')
    expect(text).toContain('远征通关')
    expect(text).toContain('高难通关')
    expect(text).toContain('50.0%')
    expect(text).toContain('硬上限 20%')
  })
})

describe('chestLuckExplain', () => {
  it('falls back to the config source table without player context', () => {
    const text = chestLuckExplain().lines.join('\n')
    expect(text).toContain('rarityLuck')
    expect(text).toContain('装备品阶幸运')
    expect(text).toContain('远征通关')
    expect(text).toContain('高难通关')
  })

  it('shows the current luck progress and per-source breakdown', () => {
    const text = chestLuckExplain(fakeChestLuck()).lines.join('\n')
    expect(text).toContain('当前 p = 42.0%')
    expect(text).toContain('抽箱品阶概率料理 / 秘药')
    expect(text).toContain('装备品阶幸运')
    expect(text).toContain('仅提升箱子的装备品阶抽取概率')
  })
})

describe('equipEffectExplain', () => {
  it('explains an implemented mechanic with its shared-config parameters', () => {
    const text = equipEffectExplain('bleedProcPct')?.lines.join('\n') ?? ''
    expect(text).toContain('命中时按词条概率触发')
    expect(text).toContain('equipEffects')
  })

  it('returns null for stats without an extended mechanic', () => {
    expect(equipEffectExplain('attackPct')).toBeNull()
  })
})

const STAT_KEYS: StatKey[] = [
  'maxHp', 'maxMp', 'hpRegen', 'mpRegen', 'attack', 'magicAttack', 'physDef', 'magicDef',
  'critValue', 'dhValue', 'detValue', 'critRate', 'critDamage', 'dhRate', 'detBonus',
  'dodge', 'attackSpeed', 'haste', 'hitRate', 'lifesteal', 'tenacity', 'power',
]

const fakeBreakdown: StatBreakdown = {
  level: 60,
  bias: 'str',
  mainAttr: 'str',
  jobId: 'WAR',
  jobMatch: true,
  growthCoef: 1.1,
  biasRates: { str: 1.15, dex: 0.5, int: 0.5, vit: 1 },
  jobMatchBonusPct: 15,
  core: {
    hero: { str: 120, dex: 90, int: 70, vit: 0 },
    equip: { str: 92, dex: 0, int: 0, vit: 0 },
    total: { str: 212, dex: 90, int: 70, vit: 0 },
  },
  panelBase: {
    maxHp: 2960, maxMp: 248, hpRegen: 1, mpRegen: 11, attack: 212, magicAttack: 84,
    physDef: 106, magicDef: 21, dodgePct: 4.5, attackSpeedPct: 9, critRatePct: 5, hitRatePct: 3.6,
  },
  levelGrowth: { maxHp: 1000, maxMp: 40, attack: 60, mpRegen: 1, dodgePct: 0.5, attackSpeedPct: 0.9 },
  caps: { dodgePct: 30, attackSpeedPct: 50, critRatePct: 100, hitRatePct: 20 },
  equipFlat: { hp: 500, attack: 300, magicAttack: 0, physDef: 0, magicDef: 0 },
  subs: { regen: 0, dodge: 0, sks: 0, acc: 0, sps: 0, lifesteal: 0, tenacity: 0, crit: 600, dh: 0, det: 0 },
  termMods: { maxHpPct: 20 },
}

const fakeHeroStats = {
  level: 60, jobId: 'WAR', mainAttr: 'str',
  maxHp: 4152, maxMp: 248, hpRegen: 1, mpRegen: 11,
  attack: 512, magicAttack: 84, physDef: 106, magicDef: 21,
  dodgePct: 4.5, attackSpeedPct: 9, hitRatePct: 3.6, hastePct: 0, lifestealPct: 0, tenacityPct: 0,
  critValue: 600, dhValue: 0, detValue: 0,
  critRatePct: 6.8, critDamagePct: 140, dhRatePct: 0, detBonusPct: 0,
  termMods: { maxHpPct: 20 },
} as unknown as HeroStats

describe('statExplain', () => {
  const ctx = { breakdown: fakeBreakdown, stats: fakeHeroStats, hero: { level: 60, agility: 90 } }

  it('每个面板属性都有「作用 + 计算」说明', () => {
    for (const key of STAT_KEYS) {
      const e = statExplain(key, ctx)
      expect(e.title, key).toBeTruthy()
      expect(e.usage, key).toBeTruthy()
      expect(e.lines.length, key).toBeGreaterThan(1)
    }
  })

  it('生命值说明代入拆解数值并得出面板值', () => {
    const text = statExplain('maxHp', ctx).lines.join('\n')
    expect(text).toContain('212') // 力量核心属性总量
    expect(text).toContain('500') // 装备生命
    expect(text).toContain('4152') // 最终面板值
  })

  it('缺少拆解数据时降级为公式且不抛错', () => {
    const e = statExplain('maxHp', { stats: fakeHeroStats, hero: { level: 1, agility: 0 } })
    expect(e.usage).toBeTruthy()
    expect(e.lines.join('\n')).toContain('未就绪')
  })
})
