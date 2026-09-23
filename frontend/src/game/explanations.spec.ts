import { describe, expect, it } from 'vitest'

import data from '@shared/schema'

import { chestLuckExplain, craftRarityExplain } from './explanations'
import type { ChestRarityLuck, CraftOdds, RarityId } from './types'

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
