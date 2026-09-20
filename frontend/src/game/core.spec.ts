import data from '@shared/schema'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BattleSimulator } from '@/game/core/battle'
import { estimateDps, rollDamage, secondsToKill, skillCooldown, ADVENTURER_SKILL } from '@/game/core/combat'
import { bossStats, getRegion, goldRange, monsterStats } from '@/game/core/regions'
import type { HeroStats } from '@/game/types'

function makeStats(overrides: Partial<HeroStats> = {}): HeroStats {
  return {
    level: 1,
    jobId: 'adventurer',
    mainAttr: 'str',
    maxHp: 430,
    maxMp: 320,
    hpRegen: 2,
    mpRegen: 4,
    attack: 40,
    magicAttack: 40,
    physDef: 16,
    magicDef: 10,
    dodgePct: 1.6,
    attackSpeedPct: 3.3,
    hitRatePct: 1.3,
    hastePct: 0,
    lifestealPct: 0,
    tenacityPct: 0,
    critValue: 0,
    dhValue: 0,
    detValue: 0,
    critRatePct: 5,
    critDamagePct: 140,
    dhRatePct: 0,
    detBonusPct: 0,
    termMods: {},
    ...overrides,
  }
}

describe('地区与怪物配置', () => {
  it('40 个地区且按顺序递增刷新间隔递减', () => {
    const regions = data.regions.regions
    expect(regions).toHaveLength(40)
    expect(regions[0].spawnInterval).toBe(3.0)
    expect(regions[39].spawnInterval).toBe(1.0)
  })

  it('小怪属性随地区等级提高', () => {
    const low = monsterStats(getRegion(1), 'normal')
    const high = monsterStats(getRegion(40), 'normal')
    expect(high.hp).toBeGreaterThan(low.hp)
    expect(high.attack).toBeGreaterThan(low.attack)
  })

  it('精英怪属性与金币系数高于普通怪', () => {
    const normal = monsterStats(getRegion(5), 'normal')
    const elite = monsterStats(getRegion(5), 'elite')
    expect(elite.hp).toBeGreaterThan(normal.hp)
    expect(normal.kind).toBe('normal')
    expect(elite.kind).toBe('elite')
  })

  it('BOSS 属性显著高于同地区小怪', () => {
    const region = getRegion(10)
    const mob = monsterStats(region, 'normal')
    const boss = bossStats(region)
    expect(boss.hp).toBeGreaterThan(mob.hp * 2)
    expect(boss.attack).toBeGreaterThan(mob.attack)
    expect(boss.skills?.length).toBeGreaterThan(0)
  })

  it('金币掉落范围随地区递增', () => {
    expect(goldRange(40, 'normal').min).toBeGreaterThan(goldRange(1, 'normal').min)
    const boss = goldRange(1, 'boss')
    expect(boss.max).toBeGreaterThan(goldRange(1, 'normal').max)
  })
})

describe('伤害与技能', () => {
  it('减防后至少造成 10% 伤害', () => {
    const stats = makeStats({ attack: 100, detBonusPct: 0 })
    const roll = rollDamage(stats, 100, 'physical', 99999, 1, () => 0.9)
    expect(roll.amount).toBeGreaterThanOrEqual(10)
  })

  it('直击与暴击同时触发时按乘算叠加', () => {
    const stats = makeStats({
      attack: 100,
      critRatePct: 100,
      critDamagePct: 200,
      dhRatePct: 100,
      detBonusPct: 0,
    })
    // rand 返回 0 → 必然命中直击与暴击；固定随机浮动取中值
    const roll = rollDamage(stats, 100, 'physical', 0, 1, () => 0)
    // 100 × 1.25(直击) × 2.0(暴击) × 0.95(浮动下限) = 237
    expect(roll.isCrit).toBe(true)
    expect(roll.isDirectHit).toBe(true)
    expect(roll.amount).toBeCloseTo(237, 0)
  })

  it('信念恒定乘算', () => {
    const base = rollDamage(makeStats({ attack: 100 }), 100, 'physical', 0, 1, () => 0.5)
    const withDet = rollDamage(
      makeStats({ attack: 100, detBonusPct: 13 }),
      100,
      'physical',
      0,
      1,
      () => 0.5,
    )
    expect(withDet.amount / base.amount).toBeCloseTo(1.13, 1)
  })

  it('魔法职业使用魔法攻击力', () => {
    const physical = estimateDps(makeStats({ attack: 100, magicAttack: 0, jobId: 'PLD' }), 0)
    const magical = estimateDps(makeStats({ attack: 0, magicAttack: 100, jobId: 'BLM' }), 0)
    expect(physical).toBeGreaterThan(0)
    expect(magical).toBeGreaterThan(0)
  })

  it('技能急速降低技能 CD，缩减上限 70%', () => {
    const slow = skillCooldown(makeStats(), 60)
    const fast = skillCooldown(makeStats({ hastePct: 50 }), 60)
    expect(fast).toBeLessThan(slow)
    expect(fast).toBeCloseTo(60 * 0.5, 5)
    // 超过上限后仍按 70% 计算
    expect(skillCooldown(makeStats({ hastePct: 100000 }), 60)).toBeCloseTo(60 * 0.3, 5)
    // 短 CD 技能不低于 0.5 秒
    expect(skillCooldown(makeStats({ hastePct: 100000 }), 3)).toBeCloseTo(0.9, 5)
  })

  it('普攻兜底技能存在', () => {
    expect(ADVENTURER_SKILL.potency).toBe(100)
  })

  it('击杀耗时在可玩区间', () => {
    const stats = makeStats({ level: 20, attack: 679, maxHp: 2092 })
    const seconds = secondsToKill(stats, monsterStats(getRegion(5), 'normal'))
    expect(seconds).toBeGreaterThan(0.5)
    expect(seconds).toBeLessThan(60)
  })
})

describe('战斗模拟器', () => {
  beforeEach(() => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function createSim() {
    return new BattleSimulator({
      stats: makeStats({ attack: 200, maxHp: 2000 }),
      regionId: 1,
      killsRequired: 3,
      spawnInterval: 3,
      killCount: 0,
    })
  }

  it('开始后进入小怪阶段', () => {
    const sim = createSim()
    sim.start()
    expect(sim.phase).toBe('mob')
    sim.tick(1)
    expect(sim.monster).not.toBeNull()
    expect(sim.monsterHp).toBeGreaterThan(0)
  })

  it('击杀小怪后计数增加并生成上报事件', () => {
    const sim = createSim()
    sim.start()
    for (let i = 0; i < 600; i += 1) sim.tick(0.1)
    const pending = sim.drainPending()
    expect(pending.kills.length).toBeGreaterThan(0)
    expect(sim.killCount).toBeGreaterThan(0)
  })

  it('击杀数达标后进入 BOSS 阶段', () => {
    const sim = createSim()
    sim.start()
    let guard = 0
    while (sim.killCount < 3 && guard < 2000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.killCount).toBeGreaterThanOrEqual(3)
    expect(sim.phase).toBe('boss')
  })

  it('阵亡后击杀计数归零并进入复活', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1, maxHp: 10, physDef: 0 }),
      regionId: 1,
      killsRequired: 20,
      spawnInterval: 1,
      killCount: 5,
    })
    sim.start()
    let guard = 0
    while (sim.phase !== 'dead' && guard < 5000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('dead')
    expect(sim.killCount).toBe(0)
    const pending = sim.drainPending()
    expect(pending.died).toBe(true)
  })

  it('服务端纠正击杀计数', () => {
    const sim = createSim()
    sim.start()
    sim.applyServerKillCount(2, 3)
    expect(sim.killCount).toBe(2)
  })

  it('属性更新后生命值不越界', () => {
    const sim = createSim()
    sim.start()
    sim.tick(0.5)
    sim.updateStats(makeStats({ maxHp: 100, attack: 500 }))
    expect(sim.heroHp).toBeLessThanOrEqual(100)
    expect(sim.heroHp).toBeGreaterThan(0)
  })
})
