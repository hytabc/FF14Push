import { describe, expect, it } from 'vitest'
import { consumableBonus } from './consumables'
import { experienceLog } from './battleLog'

describe('消耗品与经验展示', () => {
  it('显示所有效果和时长，并正确换算抽箱幸运比例', () => {
    expect(consumableBonus('p_chestLuck')).toBe('抽箱品阶概率 +15% · 持续 60 秒')
    expect(consumableBonus('f_fishInsightPct')).toBe('捕鱼人之识时长 +20% · 鱼王/鱼皇概率 +1.2% · 持续 1800 秒')
    expect(consumableBonus(null)).toBe('')
  })
  it('展示服务端结算增幅和可核对的加数', () => {
    expect(experienceLog(320, { base: 100, efficiencyBonus: 60, catchUpBonus: 160, totalBonusPct: 220 }))
      .toBe('获得经验 320（+220%；结算基础 100，效率加成 +60，追赶加成 +160）')
    expect(experienceLog(50)).toBe('获得经验 50')
  })
})
