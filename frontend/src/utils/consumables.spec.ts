import { describe, expect, it } from 'vitest'
import { consumableBonus } from './consumables'
import { activityExpLog, experienceLog, goldLog } from './battleLog'

describe('消耗品与经验展示', () => {
  it('显示所有效果和时长，并正确换算抽箱幸运比例', () => {
    expect(consumableBonus('p_chestLuck')).toBe('抽箱品阶概率 +15% · 持续 600 秒')
    expect(consumableBonus('f_fishInsightPct')).toBe('捕鱼人之识时长 +20% · 特殊鱼概率 +1.2% · 持续 1800 秒')
    expect(consumableBonus(null)).toBe('')
  })
  it('展示服务端结算增幅和可核对的加数', () => {
    expect(experienceLog(320, { base: 100, efficiencyBonus: 60, catchUpBonus: 160, totalBonusPct: 220 }))
      .toBe('获得经验 320（+220%；结算基础 100，效率加成 +60，追赶加成 +160）')
    expect(experienceLog(50)).toBe('获得经验 50')
  })
  it('金币收益展示服务端结算明细（与经验日志同构）', () => {
    expect(goldLog(307, { base: 450, penaltyBonus: -171, potionBonus: 28, totalBonusPct: -31.78 }))
      .toBe('获得金币 307（-31.78%；结算基础 450，收益加成 −171，药水加成 +28）')
    expect(goldLog(120)).toBe('获得金币 120')
  })
  it('生产 / 采集经验展示基础、品阶系数与逐条来源', () => {
    expect(
      activityExpLog({ base: 18, rarityMultiplier: 1, bonusPct: 0, amount: 18, sources: [] }),
    ).toBe('获得经验 18（基础 18）')
    expect(
      activityExpLog({
        base: 24,
        rarityMultiplier: 2.4,
        bonusPct: 15,
        amount: 68,
        sources: [{ label: '灵感', pct: 15 }],
      }),
    ).toBe('获得经验 68（基础 24，品阶 ×2.4，经验加成 +15%：灵感 +15%）')
    expect(
      activityExpLog({
        base: 48,
        rarityMultiplier: 1,
        bonusPct: 25,
        amount: 60,
        sources: [{ label: '经验获取秘药', pct: 25 }],
      }),
    ).toBe('获得经验 60（基础 48，经验加成 +25%：经验获取秘药 +25%）')
  })
})
