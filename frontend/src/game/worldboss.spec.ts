import { describe, expect, it } from 'vitest'

import data from '@shared/schema'

import { phaseForRatio, respawnIn, reviveIn, weaknessHint, type WorldBossRules } from './worldboss'

const RULES: WorldBossRules = { heroSlots: 8, levelRequirement: 80, fullPowerLevel: 100, weaknessFloor: 0.1 }

describe('世界BOSS 前端辅助', () => {
  it('共享配置暴露世界BOSS 数值（20 亿血量 / 20000 攻击 / ≥20 技能 / 8 席 / P1-P3）', () => {
    const wb = data.worldboss
    expect(wb.boss.maxHp).toBe(2_000_000_000)
    expect(wb.boss.attack).toBe(20000)
    expect(wb.boss.respawnSeconds).toBe(5 * 3600)
    expect(wb.boss.skillPool.length).toBeGreaterThanOrEqual(20)
    expect(wb.rules.heroSlots).toBe(8)
    expect(wb.phases.map((p) => p.id)).toEqual([1, 2, 3])
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
})
