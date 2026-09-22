import { describe, expect, it } from 'vitest'

import data from '@shared/schema'

import { craftRarityExplain } from './explanations'
import type { CraftOdds, RarityId } from './types'

function fakeCraft(): CraftOdds {
  const odds = Object.fromEntries(data.rarities.order.map((r) => [r, 0])) as Record<RarityId, number>
  odds.common = 0.28
  odds.mythic = 0.5
  return {
    odds,
    luck: 0.5,
    mythicCap: 0.2,
    sources: [
      { key: 'heroLevel', value: 50, ref: 100, norm: 0.5, weight: 0.25 },
      { key: 'clearedRegions', value: 20, ref: 40, norm: 0.5, weight: 0.25 },
      { key: 'prodLevel', value: 25, ref: 50, norm: 0.5, weight: 0.25 },
      { key: 'gearPct', value: 30, ref: 60, norm: 0.5, weight: 0.25 },
    ],
  }
}

describe('craftRarityExplain', () => {
  it('explains the scaling formula from shared config without player context', () => {
    const text = craftRarityExplain().lines.join('\n')
    expect(text).toContain('rarityScaling')
    expect(text).toContain('20%')
  })

  it('lists all four sources and the resolved odds with player context', () => {
    const text = craftRarityExplain(fakeCraft()).lines.join('\n')
    expect(text).toContain('英雄等级')
    expect(text).toContain('通关地区数')
    expect(text).toContain('生产等级')
    expect(text).toContain('专用装备品阶幸运')
    expect(text).toContain('50.0%')
    expect(text).toContain('硬上限 20%')
  })
})
