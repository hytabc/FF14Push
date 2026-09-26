import { describe, expect, it } from 'vitest'

import data from '@shared/schema'

import {
  nextRewardTier,
  periodIn,
  phaseForRatio,
  respawnIn,
  rewardTier,
  reviveIn,
  tierProgress,
  weaknessHint,
  type WorldBossRewardTier,
  type WorldBossRules,
} from './worldboss'

const RULES: WorldBossRules = { heroSlots: 8, levelRequirement: 80, fullPowerLevel: 100, weaknessFloor: 0.1 }
const TIERS: WorldBossRewardTier[] = [
  { minDamage: 5_000_000, items: 1 },
  { minDamage: 50_000_000, items: 2 },
  { minDamage: 200_000_000, items: 4 },
]

describe('世界BOSS 前端辅助', () => {
  it('共享配置暴露世界BOSS 数值（60 亿血量 / 20000 攻击 / 5h 周期 / 短休整 / ≥20 技能 / 8 席 / P1-P3）', () => {
    const wb = data.worldboss
    expect(wb.boss.maxHp).toBe(6_000_000_000)
    expect(wb.boss.attack).toBe(20000)
    expect(wb.periodSeconds).toBe(5 * 3600)
    expect(wb.boss.respawnSeconds).toBeLessThanOrEqual(300)
    expect(wb.boss.skillPool.length).toBeGreaterThanOrEqual(20)
    expect(wb.rules.heroSlots).toBe(8)
    expect(wb.phases.map((p) => p.id)).toEqual([1, 2, 3])
    // 奖励 = 击杀奖励（全员同额）+ 档位 + 名次加成：首档即保底门槛。
    expect(wb.reward.tiers[0].minDamage).toBe(wb.reward.minDamage)
    expect(wb.reward.killReward.perKill).toBeGreaterThanOrEqual(1)
    const topItems =
      wb.reward.tiers[wb.reward.tiers.length - 1].items +
      wb.reward.rankBonus['1'] +
      wb.reward.killReward.maxItems
    expect(topItems).toBe(21)
  })

  it('阶段按血量占比递增：血量越低防御与技能威力越高', () => {
    const table = data.worldboss.phases
    expect(phaseForRatio(1, table)?.id).toBe(1)
    expect(phaseForRatio(0.6, table)?.id).toBe(1)
    expect(phaseForRatio(0.5, table)?.id).toBe(2)
    expect(phaseForRatio(0.2, table)?.id).toBe(3)
    expect(phaseForRatio(0, table)?.id).toBe(3)
    expect(table[2].defenseMultiplier).toBeGreaterThan(table[1].defenseMultiplier)
    expect(table[2].skillPotencyMultiplier).toBeGreaterThan(table[1].skillPotencyMultiplier)
  })

  it('绝境龙神 39 件单列一组且固定 100 级、红色（神话）', () => {
    const items = Object.values(data.exclusiveItemById)
    expect(items.length).toBe(39)
    for (const base of items) {
      expect(base.exclusive).toBe(true)
      expect(base.levelReq).toBe(100)
    }
    // 不在普通底材池中 => 抽箱/合成/生产无法产出
    expect(Object.values(data.baseItemById).some((b) => b.id in data.exclusiveItemById && !b.exclusive)).toBe(false)
    expect(items.some((b) => b.id in data.baseItemById)).toBe(true)
  })

  it('复活倒计时按会话内毫秒计算，不为负', () => {
    expect(reviveIn(12_000, 2_000)).toBe(10)
    expect(reviveIn(2_000, 5_000)).toBe(0)
  })

  it('刷新倒计时按服务端 epoch 秒计算', () => {
    expect(respawnIn(1_000, 400)).toBe(600)
    expect(respawnIn(null)).toBe(0)
    expect(respawnIn(100, 200)).toBe(0)
  })

  it('等级削弱提示：80 级严重削弱、满级解除', () => {
    expect(weaknessHint(100, RULES)).toBe('满级：无削弱')
    expect(weaknessHint(80, RULES)).toContain('×0.10')
    expect(weaknessHint(90, RULES)).toContain('×0.55')
  })

  it('紧凑削弱提示：省略括注，满级只显示「满级」（供上阵卡片使用）', () => {
    expect(weaknessHint(100, RULES, true)).toBe('满级')
    expect(weaknessHint(80, RULES, true)).toBe('削弱 ×0.10')
    expect(weaknessHint(90, RULES, true)).toBe('削弱 ×0.55')
  })

  it('讨伐周期倒计时按服务端 epoch 秒计算，不为负', () => {
    expect(periodIn(1_000, 400)).toBe(600)
    expect(periodIn(1_000, 1_000)).toBe(0)
    expect(periodIn(1_000, 2_000)).toBe(0)
    expect(periodIn(null)).toBe(0)
  })

  it('档位取最高达标档、未达档为 null；下一档用于「还差多少」提示', () => {
    expect(rewardTier(4_999_999, TIERS)).toBeNull()
    expect(rewardTier(5_000_000, TIERS)?.items).toBe(1)
    expect(rewardTier(199_999_999, TIERS)?.items).toBe(2)
    expect(rewardTier(999_999_999, TIERS)?.items).toBe(4)
    expect(nextRewardTier(0, TIERS)?.minDamage).toBe(5_000_000)
    expect(nextRewardTier(5_000_000, TIERS)?.minDamage).toBe(50_000_000)
    expect(nextRewardTier(200_000_000, TIERS)).toBeNull()
  })
})

describe('世界BOSS 档位进度', () => {
  it('未达首档：从 0 起算，next 指向首档', () => {
    const p = tierProgress(0, TIERS)
    expect(p.current).toBeNull()
    expect(p.next?.minDamage).toBe(5_000_000)
    expect(p.floor).toBe(0)
    expect(p.fraction).toBe(0)
    expect(p.remaining).toBe(5_000_000)
  })

  it('档内线性推进（首档 + 到二档的一半 = 50%）', () => {
    const p = tierProgress(5_000_000 + 22_500_000, TIERS)
    expect(p.current?.items).toBe(1)
    expect(p.next?.items).toBe(2)
    expect(p.fraction).toBeCloseTo(0.5, 6)
    expect(p.remaining).toBe(22_500_000)
  })

  it('恰好到档：进度归零、current 前进一档', () => {
    const p = tierProgress(50_000_000, TIERS)
    expect(p.current?.items).toBe(2)
    expect(p.next?.items).toBe(4)
    expect(p.floor).toBe(50_000_000)
    expect(p.fraction).toBe(0)
  })

  it('封顶：无下一档，进度为 1、remaining 为 0', () => {
    const p = tierProgress(999_999_999, TIERS)
    expect(p.current?.items).toBe(4)
    expect(p.next).toBeNull()
    expect(p.fraction).toBe(1)
    expect(p.remaining).toBe(0)
  })

  it('空档位表不崩：全部为 null / 进度 1', () => {
    const p = tierProgress(123, [])
    expect(p.current).toBeNull()
    expect(p.next).toBeNull()
    expect(p.fraction).toBe(1)
    expect(p.remaining).toBe(0)
  })
})
