import data from '@shared/schema'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BattleSimulator } from '@/game/core/battle'
import { eggSkillSet } from '@/game/core/egg'
import { attackSpeedFactor, estimateDps, rollDamage, rollIncoming, secondsToKill, skillCooldown, ADVENTURER_SKILL } from '@/game/core/combat'
import {
  monsterExpMultiplier,
  monsterGoldMultiplier,
  monsterHpMultiplier,
  scalePlayerStats,
} from '@/game/core/difficulty'
import { bossStats, getRegion, goldRange, levelPenalty, monsterStats } from '@/game/core/regions'
import type { HeroStats, MonsterStats } from '@/game/types'

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
    const roll = rollDamage(stats, 100, 'physical', 99999, 1, null, 0, () => 0.9)
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
    const roll = rollDamage(stats, 100, 'physical', 0, 1, null, 0, () => 0)
    // 100 × 1.25(直击) × 2.0(暴击) × 0.95(浮动下限) = 237
    expect(roll.isCrit).toBe(true)
    expect(roll.isDirectHit).toBe(true)
    expect(roll.amount).toBeCloseTo(237, 0)
  })

  it('信念恒定乘算', () => {
    const base = rollDamage(makeStats({ attack: 100 }), 100, 'physical', 0, 1, null, 0, () => 0.5)
    const withDet = rollDamage(
      makeStats({ attack: 100, detBonusPct: 13 }),
      100,
      'physical',
      0,
      1,
      null,
      0,
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
    expect(ADVENTURER_SKILL.potency).toBe(data.combat.basicAttackPotency)
  })

  it('击杀耗时在可玩区间', () => {
    const stats = makeStats({ level: 20, attack: 679, maxHp: 2092 })
    const seconds = secondsToKill(stats, monsterStats(getRegion(5), 'normal'))
    expect(seconds).toBeGreaterThan(0.5)
    expect(seconds).toBeLessThan(60)
  })
})

describe('等级压制', () => {
  it('等级达到地区下限时无惩罚', () => {
    const region = getRegion(5) // levelMin 20
    for (const level of [20, 35, 100]) {
      const penalty = levelPenalty(level, region)
      expect(penalty.hitRatePenaltyPct).toBe(0)
      expect(penalty.damageDealtPenaltyPct).toBe(0)
      expect(penalty.damageTakenBonusPct).toBe(0)
      expect(penalty.defenseIgnorePct).toBe(0)
    }
  })

  it('每落后 1 级按配置累加四项惩罚', () => {
    const cfg = data.regions.levelPenalty
    const penalty = levelPenalty(35, getRegion(10)) // levelMin 45 → 落后 10 级
    expect(penalty.hitRatePenaltyPct).toBeCloseTo(10 * cfg.hitRatePenaltyPctPerLevel, 5)
    expect(penalty.damageDealtPenaltyPct).toBeCloseTo(10 * cfg.damageDealtPenaltyPctPerLevel, 5)
    expect(penalty.damageTakenBonusPct).toBeCloseTo(10 * cfg.damageTakenBonusPctPerLevel, 5)
    expect(penalty.defenseIgnorePct).toBeCloseTo(
      Math.min(cfg.maxDefenseIgnorePct, 10 * cfg.defenseIgnorePctPerLevel),
      5,
    )
  })

  it('惩罚不超过配置上限', () => {
    const cfg = data.regions.levelPenalty
    const penalty = levelPenalty(1, getRegion(40)) // 落后 98 级
    expect(penalty.hitRatePenaltyPct).toBe(cfg.maxHitRatePenaltyPct)
    expect(penalty.damageDealtPenaltyPct).toBe(cfg.maxDamageDealtPenaltyPct)
    expect(penalty.damageTakenBonusPct).toBe(cfg.maxDamageTakenBonusPct)
    expect(penalty.defenseIgnorePct).toBe(cfg.maxDefenseIgnorePct)
  })

  it('落后 10 级的输出惩罚已足够重（≥ 80%）', () => {
    const cfg = data.regions.levelPenalty
    const penalty = levelPenalty(60, getRegion(23)) // levelMin 70 → 落后 10 级
    expect(penalty.damageDealtPenaltyPct).toBeGreaterThanOrEqual(80)
    expect(penalty.defenseIgnorePct).toBeGreaterThanOrEqual(cfg.maxDefenseIgnorePct) // 防御归零
  })

  it('落后 20 级时击杀耗时至少放大 10 倍', () => {
    const region = getRegion(23) // levelMin 70
    const monster = monsterStats(region, 'normal')
    const matched = makeStats({ level: 70, attack: 3000, hitRatePct: 5 })
    const underLeveled = makeStats({ level: 50, attack: 3000, hitRatePct: 5 })
    const matchedSeconds = secondsToKill(matched, monster, levelPenalty(70, region))
    const underSeconds = secondsToKill(underLeveled, monster, levelPenalty(50, region))
    expect(underSeconds / matchedSeconds).toBeGreaterThan(10)
  })

  it('越级时防御衰减，承伤显著高于等级达标', () => {
    const region = getRegion(40) // levelMin 99
    const monster = monsterStats(region, 'normal')
    const atLevel = makeStats({ level: 99, attack: 3000, maxHp: 40000, physDef: 6000 })
    const under = makeStats({ level: 79, attack: 3000, maxHp: 40000, physDef: 6000 })
    const underPenalty = levelPenalty(79, region)
    expect(underPenalty.defenseIgnorePct).toBeGreaterThan(0)

    const base = rollIncoming(monster.attack, 100, atLevel.physDef, atLevel.tenacityPct, 0, 0)
    const scaled = rollIncoming(
      monster.attack,
      100,
      under.physDef * (1 - underPenalty.defenseIgnorePct / 100),
      under.tenacityPct,
      0,
      underPenalty.damageTakenBonusPct,
    )
    expect(scaled).toBeGreaterThan(base * 3)
  })

  it('未命中时判定不产生伤害', () => {
    const stats = makeStats({ attack: 1000, hitRatePct: 0 })
    const penalty = levelPenalty(1, getRegion(40))
    const roll = rollDamage(stats, 100, 'physical', 0, 1, penalty, 0, () => 1) // 必不命中
    expect(roll.missed).toBe(true)
    expect(roll.amount).toBe(0)
  })
})

describe('蓝量与治疗平衡', () => {
  it('持续战斗：技能仍消耗蓝量，普攻独立出手', () => {
    const stats = makeStats({
      level: 100,
      jobId: 'PLD',
      maxMp: 600,
      mpRegen: 3,
      attack: 4000,
      maxHp: 200000,
      physDef: 2000,
    })
    const sim = new BattleSimulator({
      stats,
      regionId: 1,
      killsRequired: 5,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    let minMp = stats.maxMp
    for (let i = 0; i < 2400; i += 1) {
      if (sim.phase === 'cleared') sim.continueAfterClear()
      sim.tick(0.05)
      minMp = Math.min(minMp, sim.heroMp)
    }
    // 蓝量仍会被技能消耗（普攻回蓝不足以让蓝条永远满）
    expect(minMp).toBeLessThan(stats.maxMp * 0.5)
    // 普攻与技能完全独立：日志中同时存在普攻与技能
    const texts = sim.log.map((e) => e.text)
    expect(texts.some((t) => t.startsWith('普攻'))).toBe(true)
    expect(texts.some((t) => t.includes('造成') && !t.startsWith('普攻'))).toBe(true)
  })

  it('治疗职业技能数值已下调、CD 已延长', () => {
    const jobs = data.jobs.jobs as Array<{
      id: string
      role: string
      skills: Array<{ cd: number; effects: Array<{ type: string; value?: number }> }>
    }>
    for (const job of jobs.filter((j) => j.role === 'healer')) {
      for (const skill of job.skills) {
        for (const effect of skill.effects ?? []) {
          if (effect.type === 'heal') {
            // 小/中治疗（CD < 120s）不超过 12%；大招允许 50%
            expect(effect.value ?? 0).toBeLessThanOrEqual(skill.cd >= 120 ? 0.5 : 0.12)
          }
          if (effect.type === 'healOverTime') expect(effect.value ?? 0).toBeLessThanOrEqual(0.02)
          if (effect.type === 'shield') expect(effect.value ?? 0).toBeLessThanOrEqual(0.12)
          expect(effect.type).not.toBe('fullHeal')
        }
        // 小治疗/中治疗的 CD 都已延长（不再有 15s）
        if (skill.effects?.some((e) => e.type === 'heal' && (e.value ?? 0) > 0)) {
          expect(skill.cd).toBeGreaterThanOrEqual(20)
        }
      }
    }
  })
})

describe('装备词条扩展机制', () => {
  beforeEach(() => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function runUntil(sim: BattleSimulator, marker: string, ticks = 600): boolean {
    for (let i = 0; i < ticks; i += 1) {
      sim.tick(0.05)
      if (sim.log.some((e) => e.text.includes(marker))) return true
    }
    return false
  }

  it('「连击」按概率追加普攻', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ termMods: { doubleAttackPct: 100 } }),
      regionId: 1,
      killsRequired: 999,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    expect(runUntil(sim, '连击')).toBe(true)
  })

  it('「蓄势」累计伤害达阈值后触发爆发', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 500, termMods: { chargeBlastPct: 20 } }),
      regionId: 1,
      killsRequired: 999,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    expect(runUntil(sim, '蓄势')).toBe(true)
  })

  it('「不死」受致命伤害时免死并保留 1 点生命', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ level: 100, maxHp: 100, hpRegen: 0, physDef: 0, attack: 1, termMods: { cheatDeathPct: 100 } }),
      regionId: 40,
      killsRequired: 999,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    expect(runUntil(sim, '不死')).toBe(true)
    expect(sim.phase).toBe('mob')
    expect(sim.heroHp).toBe(1)
  })

  it('「死亡抵抗」死亡时立即复活并回复 30% 生命', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ level: 100, maxHp: 100, hpRegen: 0, physDef: 0, attack: 1, termMods: { reviveChancePct: 100 } }),
      regionId: 40,
      killsRequired: 999,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    expect(runUntil(sim, '死亡抵抗')).toBe(true)
    expect(sim.phase).toBe('mob')
    expect(sim.heroHp).toBeCloseTo(30, 0)
  })

  it('存活英雄生命值恒为整数且 ≥ 1，不会出现「显示 0 血却仍可战斗」', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ level: 60, maxHp: 5000, hpRegen: 7.5, attack: 30, physDef: 20 }),
      regionId: 20,
      killsRequired: 5,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    for (let i = 0; i < 1500; i += 1) {
      sim.tick(0.1)
      if (sim.phase === 'dead') continue
      expect(Number.isInteger(sim.heroHp)).toBe(true)
      expect(sim.heroHp).toBeGreaterThanOrEqual(1)
    }
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

  it('BOSS 击败后留在当前地区可继续挂机', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 100000, maxHp: 200000 }),
      regionId: 1,
      killsRequired: 3,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    let guard = 0
    while (sim.phase !== 'cleared' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('cleared')

    sim.continueAfterClear()
    expect(sim.phase).toBe('mob')
    expect(sim.killCount).toBe(0)
    expect(sim.monster).toBeNull()

    sim.tick(2)
    expect(sim.monster).not.toBeNull()
  })

  it('BOSS 结算被服务端丢弃时退回小怪阶段，不会卡死在 cleared', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 100000, maxHp: 200000 }),
      regionId: 1,
      killsRequired: 3,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    let guard = 0
    while (sim.phase !== 'cleared' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('cleared')

    // 服务端把计数纠正为未达标：必须能恢复，否则 cleared 阶段不再产生任何事件
    sim.applyServerKillCount(1, 3)
    sim.resumeAfterDroppedBoss()
    expect(sim.phase).toBe('mob')
    expect(sim.killCount).toBe(1)
    sim.tick(2)
    expect(sim.monster).not.toBeNull()
  })

  it('服务端已认可达标但 BOSS 未结算时，恢复到 BOSS 阶段重试', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 100000, maxHp: 200000 }),
      regionId: 1,
      killsRequired: 3,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    let guard = 0
    while (sim.phase !== 'cleared' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('cleared')

    sim.applyServerKillCount(3, 3)
    sim.resumeAfterDroppedBoss()
    expect(sim.phase).toBe('boss')
  })

  it('普攻与技能完全独立：技能全都不可用时普攻照常出手并进入日志', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'PLD', attack: 2000, attackSpeedPct: 0 }),
      regionId: 1,
      killsRequired: 5,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    for (let i = 0; i < 200 && !sim.monster; i += 1) sim.tick(0.1)
    expect(sim.monster).toBeTruthy()

    // 蓝量为 0 → 所有技能都负担不起（技能不可用），普攻仍须正常出手
    sim.heroMp = 0
    sim.basicAttackTimer = 0
    const before = sim.log.length
    sim.tick(0.2)
    const basic = sim.log.slice(before).filter((e) => e.text.startsWith('普攻'))
    expect(basic.length).toBeGreaterThan(0)
    expect(basic.some((e) => e.text.includes('造成'))).toBe(true)
  })

  it('普攻频率受攻速影响（不影响技能 GCD）', () => {
    const cooldown = (attackSpeedPct: number): number => {
      const sim = new BattleSimulator({ stats: makeStats({ jobId: 'PLD', attackSpeedPct }), regionId: 1 })
      return (sim as unknown as { basicAttackCooldown(): number }).basicAttackCooldown()
    }
    const base = cooldown(0)
    expect(base).toBeCloseTo(data.combat.basicAttackCd as number, 5)
    expect(cooldown(100)).toBeCloseTo(base / 2, 5)
    // 上限 2.0：再高的攻速也不再缩短
    expect(cooldown(500)).toBeCloseTo(base / 2, 5)
  })

  it('普攻同样结算暴击 / 直击标记（日志带「!!」）', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0)
    try {
      const sim = new BattleSimulator({
        stats: makeStats({ jobId: 'PLD', attack: 1000, critRatePct: 100, dhRatePct: 100 }),
        regionId: 1,
      })
      ;(sim as unknown as { setMonster(m: MonsterStats): void }).setMonster({
        id: 'dummy', regionId: 0, name: '木桩', templateId: 'normal', kind: 'normal',
        hp: 1e12, attack: 0, defense: 0, attackInterval: 1, level: 100, resistancePct: 0,
      })
      sim.basicAttackTimer = 0
      ;(sim as unknown as { tickBasicAttack(): void }).tickBasicAttack()
      expect(sim.log.some((e) => e.text.startsWith('普攻') && e.text.includes('!!'))).toBe(true)
    } finally {
      spy.mockRestore()
    }
  })
})

describe('高难副本模拟器', () => {
  beforeEach(() => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function makeBoss(id: string, name: string, hp: number): MonsterStats {
    return {
      id,
      regionId: 0,
      name,
      templateId: id,
      kind: 'boss',
      hp,
      attack: 1,
      defense: 0,
      attackInterval: 2.5,
      level: 60,
      resistancePct: 25,
    }
  }

  function createRaid(bosses: MonsterStats[]) {
    return new BattleSimulator({
      stats: makeStats({ attack: 100000, maxHp: 500000 }),
      raid: {
        bosses,
        enrage: { attackMultiplier: 3.5, damageReductionPct: 70, attackSpeedBonusPct: 30 },
      },
    })
  }

  it('开局即与全部 BOSS 交战，不产生小怪击杀上报', () => {
    const sim = createRaid([makeBoss('a', '极·甲', 5000), makeBoss('b', '极·乙', 5000)])
    sim.start()
    expect(sim.phase).toBe('boss')
    expect(sim.bossEntries()).toHaveLength(2)
    expect(sim.monsterName).toBe('极·甲')

    let guard = 0
    while (sim.phase !== 'cleared' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('cleared')
    const pending = sim.drainPending()
    expect(pending.bossKilled).toBe(true)
    expect(pending.kills).toHaveLength(0)
  })

  it('切换目标后伤害落在新目标身上', () => {
    const sim = createRaid([makeBoss('a', '极·甲', 100000), makeBoss('b', '极·乙', 100000)])
    sim.start()
    sim.selectTarget(1)
    expect(sim.bossEntries()[1].isTarget).toBe(true)

    const before = sim.bossEntries().map((b) => b.hp)
    for (let i = 0; i < 30; i += 1) sim.tick(0.1)
    const after = sim.bossEntries().map((b) => b.hp)
    expect(after[0]).toBe(before[0])
    expect(after[1]).toBeLessThan(before[1])
  })

  it('一方阵亡后另一方狂暴，且必须两个都死才算通关', () => {
    const sim = createRaid([makeBoss('a', '极·甲', 3000), makeBoss('b', '极·乙', 400000)])
    sim.start()

    let guard = 0
    while (sim.bossEntries().length > 1 && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.bossEntries()).toHaveLength(1)
    expect(sim.phase).toBe('boss') // 还没打完
    const survivor = sim.bossEntries()[0]
    expect(survivor.enraged).toBe(true)
    expect(survivor.name).toBe('极·乙')

    guard = 0
    while (sim.phase !== 'cleared' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('cleared')
  })

  it('阵亡即挑战失败且不复活', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1, maxHp: 10, physDef: 0, hpRegen: 0, mpRegen: 0 }),
      raid: { bosses: [makeBoss('a', '极·甲', 10_000_000)], enrage: null },
    })
    sim.start()
    let guard = 0
    while (sim.phase !== 'dead' && guard < 20000) {
      sim.tick(0.1)
      guard += 1
    }
    expect(sim.phase).toBe('dead')
    for (let i = 0; i < 100; i += 1) sim.tick(0.1)
    expect(sim.phase).toBe('dead')
  })

  it('BOSS 减伤技能生效：相同输出下掉血更慢', () => {
    const plain = makeBoss('plain', '无技能', 1_000_000)
    const guarded: MonsterStats = {
      ...makeBoss('guarded', '坚壁', 1_000_000),
      skillInterval: 1,
      skills: [
        { id: 'bulwark', name: '坚壁', effect: 'shield', damageReduce: 0.8, duration: 999, desc: '' },
      ],
    }
    const heroStats = makeStats({ attack: 1000, maxHp: 100000 })
    const simPlain = new BattleSimulator({ stats: heroStats, raid: { bosses: [plain], enrage: null } })
    const simGuard = new BattleSimulator({ stats: heroStats, raid: { bosses: [guarded], enrage: null } })
    simPlain.start()
    simGuard.start()
    for (let i = 0; i < 50; i += 1) {
      simPlain.tick(0.1)
      simGuard.tick(0.1)
    }
    expect(simGuard.bossEntries()[0].hp).toBeGreaterThan(simPlain.bossEntries()[0].hp)
  })

  it('BOSS 增伤技能生效：英雄承受更多伤害', () => {
    const plain = makeBoss('plain2', '无技能', 1_000_000)
    const frenzied: MonsterStats = {
      ...makeBoss('frenzied', '战吼', 1_000_000),
      attack: 100,
      skillInterval: 1,
      skills: [
        { id: 'warCry', name: '战吼', effect: 'enrage', attackBuff: 0.6, duration: 999, desc: '' },
      ],
    }
    const heroStats = makeStats({ attack: 1000, maxHp: 100000, physDef: 0, tenacityPct: 0, hpRegen: 0 })
    const simPlain = new BattleSimulator({ stats: heroStats, raid: { bosses: [plain], enrage: null } })
    const simFrenzy = new BattleSimulator({ stats: heroStats, raid: { bosses: [frenzied], enrage: null } })
    simPlain.start()
    simFrenzy.start()
    for (let i = 0; i < 50; i += 1) {
      simPlain.tick(0.1)
      simFrenzy.tick(0.1)
    }
    expect(simFrenzy.heroHp).toBeLessThan(simPlain.heroHp)
  })

  it('BOSS 技能走共享 CD：间隔内只释放一次，到点再释放', () => {
    const boss: MonsterStats = {
      ...makeBoss('cd', '共享CD', 1_000_000),
      skillInterval: 5,
      skills: [{ id: 'ironWall', name: '铁壁', effect: 'shield', damageReduce: 0.3, duration: 1, desc: '' }],
    }
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1000, maxHp: 100000 }),
      raid: { bosses: [boss], enrage: null },
    })
    sim.start()
    const casts = () => sim.log.filter((e) => e.text.includes('施放 铁壁')).length
    sim.tick(1)
    expect(casts()).toBe(0)
    sim.tick(4.5) // 累计 5.5s，越过 5s 共享 CD
    expect(casts()).toBe(1)
    sim.tick(4)
    expect(casts()).toBe(1)
    sim.tick(1.5) // 累计越过第二个 5s
    expect(casts()).toBe(2)
  })

  it('BOSS 技能随机抽取：按随机数选中对应技能', () => {
    const boss = makeBoss('rng', '随机', 1_000_000)
    boss.skillInterval = 1
    boss.skills = [
      { id: 'a', name: '技能甲', effect: 'nuke', potency: 100, desc: '' },
      { id: 'b', name: '技能乙', effect: 'nuke', potency: 100, desc: '' },
      { id: 'c', name: '技能丙', effect: 'nuke', potency: 100, desc: '' },
    ]
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1000, maxHp: 100000 }),
      raid: { bosses: [boss], enrage: null },
    })
    vi.spyOn(Math, 'random').mockReturnValue(0.9) // floor(0.9 * 3) = 2 → 技能丙
    sim.start()
    sim.tick(1.1)
    const text = sim.log.map((e) => e.text).join('\n')
    expect(text).toContain('技能丙')
    expect(text).not.toContain('技能甲')
  })

  it('地区战斗不触发 BOSS 技能（副本战斗会触发）', () => {
    const skillBoss: MonsterStats = {
      ...makeBoss('raidBoss', '副本BOSS', 100000),
      skillInterval: 1,
      skills: [{ id: 'bulwark', name: '坚壁', effect: 'shield', damageReduce: 0.8, duration: 999, desc: '' }],
    }
    const raidSim = new BattleSimulator({
      stats: makeStats({ attack: 1000, maxHp: 100000 }),
      raid: { bosses: [skillBoss], enrage: null },
    })
    raidSim.start()
    for (let i = 0; i < 30; i += 1) raidSim.tick(0.1)
    expect(raidSim.log.map((e) => e.text).join('\n')).toContain('坚壁')

    // 地区战斗：即便关底 BOSS 自带技能也不触发
    const regionSim = new BattleSimulator({
      stats: makeStats({ attack: 100000, maxHp: 200000 }),
      regionId: 1,
      killsRequired: 1,
      spawnInterval: 0.1,
      killCount: 0,
    })
    regionSim.start()
    let guard = 0
    while (regionSim.phase !== 'cleared' && guard < 20000) {
      regionSim.tick(0.1)
      guard += 1
    }
    expect(regionSim.phase).toBe('cleared')
    expect(regionSim.log.map((e) => e.text).join('\n')).not.toContain('」施放')
  })

  it('副本共享技能池不少于 10 个技能', () => {
    expect(data.raids.bossSkillPool.length).toBeGreaterThanOrEqual(10)
  })
})

describe('普通副本多维软惩罚', () => {
  const penalty = {
    hitRatePenaltyPct: 10, damageDealtPenaltyPct: 35, damageTakenBonusPct: 30, defenseIgnorePct: 0,
    healingMultiplier: .75, resourceMultiplier: .8, cooldownMultiplier: 1.15,
    windowMultiplier: .8, rewardMultiplier: .6,
  }
  it('低战力普通副本仍有通关可能', () => {
    const sim = new BattleSimulator({ stats: makeStats({ maxHp: 10000 }), penalty,
      raid: { bosses: [{ ...monsterStats(getRegion(1),'normal'), kind:'boss',hp:1,attack:1 }],enrage:null } })
    sim.start()
    for(let i=0;i<100 && sim.phase!=='cleared';i++) sim.tick(.1)
    expect(sim.phase).toBe('cleared')
  })
  it('真实技能路径同时削弱治疗、护盾、资源及机制间隔', () => {
    const sim = new BattleSimulator({stats:makeStats(),penalty,
      raid:{bosses:[{...monsterStats(getRegion(1),'normal'),kind:'boss',hp:1e9,attack:0}],enrage:null}})
    sim.heroHp=1;sim.heroMp=0
    const engine=sim as unknown as {applyEffects(s:unknown):void;bossSkillInterval(s:unknown):number;cast(s:unknown):void;tickBasicAttack():void}
    engine.applyEffects({name:'测试治疗',effects:[{type:'heal',value:.1},{type:'shield',value:.1},{type:'mpRestore',value:.1}]})
    // 生命值以整数结算：治疗量按 .75 削弱后向下取整（33 ≈ 44×.75）。
    expect(sim.heroHp).toBe(Math.floor(1+Math.floor(sim.stats.maxHp*.1)*.75))
    expect(sim.shield).toBe(Math.floor(sim.stats.maxHp*.1*.75))
    expect(sim.heroMp).toBe(Math.floor(sim.stats.maxMp*.1*.8))
    expect(engine.bossSkillInterval({skillInterval:6})).toBeCloseTo(4.8)
    engine.cast(ADVENTURER_SKILL)
    // 技能 CD 受副本 CD 惩罚（cooldownMultiplier）影响
    expect(sim.cooldowns[ADVENTURER_SKILL.id]).toBeCloseTo(skillCooldown(sim.stats,ADVENTURER_SKILL.cd)*1.15)
    // 普攻由独立计时器驱动：CD 受攻速缩短，与技能 CD / GCD 无关
    sim.basicAttackTimer = 0
    engine.tickBasicAttack()
    expect(sim.basicAttackTimer).toBeCloseTo(skillCooldown(sim.stats,ADVENTURER_SKILL.cd)/attackSpeedFactor(sim.stats),5)
    const baseline = rollDamage(makeStats({attack:1000}),100,'physical',500,1,null,0,()=>.5)
    const weakened = rollDamage(makeStats({attack:1000}),100,'physical',500,1,penalty,0,()=>.5)
    expect(weakened.amount).toBe(Math.floor(baseline.amount*.65))
    expect(rollIncoming(1000,100,500,0,0,30)).toBe(Math.floor(rollIncoming(1000,100,500)*1.3))
  })
})

describe('蓝量经济（持续战斗不退化为「普攻循环」）', () => {
  // 持久木桩：全程处于战斗中，能测出真实「持续轮转」的耗蓝与技能分布。
  const dummy: MonsterStats = {
    id: 'dummy', regionId: 0, name: '木桩', templateId: 'dummy', kind: 'boss',
    hp: 1e12, attack: 0, defense: 0, attackInterval: 999, level: 100, resistancePct: 0,
  }

  function runRotation(jobId: string, maxMp: number, mpRegen: number, seconds = 180) {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId, maxMp, mpRegen, attack: 50000, maxHp: 1e7, hpRegen: 1000 }),
      raid: { bosses: [dummy], enrage: null },
    })
    sim.start()
    let basic = 0
    let total = 0
    let minMpPct = 100
    for (let i = 0; i < seconds * 10; i += 1) {
      sim.tick(0.1)
      for (const [id, count] of Object.entries(sim.drainPending().skillCasts)) {
        total += count
        if (id === ADVENTURER_SKILL.id) basic += count
      }
      minMpPct = Math.min(minMpPct, (sim.heroMp / maxMp) * 100)
    }
    return { basicShare: basic / total, total, minMpPct }
  }

  it('满级持续战斗：普攻不是主要手段，蓝条也不会被清空', () => {
    const r = runRotation('PLD', 1485, 14.2)
    expect(r.total).toBeGreaterThan(0)
    expect(r.basicShare).toBeLessThan(0.1)
    expect(r.minMpPct).toBeGreaterThan(20)
  })

  it('中低等级仍有蓝量压力，但轮转仍以技能为主', () => {
    const r = runRotation('PLD', 391, 11.6)
    expect(r.basicShare).toBeLessThan(0.25)
  })

  it('蓝量见底后仍能持续释放技能（普攻回蓝 + 自然回复）', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'PLD', maxMp: 1485, mpRegen: 14.2, attack: 50000, maxHp: 1e7, hpRegen: 1000 }),
      raid: { bosses: [dummy], enrage: null },
    })
    sim.start()
    sim.heroMp = 0
    let skillCasts = 0
    for (let i = 0; i < 300; i += 1) {
      sim.tick(0.1) // 30s
      for (const [id, count] of Object.entries(sim.drainPending().skillCasts)) {
        if (id !== ADVENTURER_SKILL.id) skillCasts += count
      }
    }
    // 不是「只能普攻」：蓝量见底后依然能稳定释放技能
    expect(skillCasts).toBeGreaterThanOrEqual(10)
  })

  it('零耗蓝普攻会按配置回复蓝量', () => {
    const maxMp = 1000
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'PLD', maxMp, mpRegen: 0, maxHp: 1e7 }),
      raid: { bosses: [dummy], enrage: null },
    })
    sim.start()
    sim.heroMp = 0
    sim.basicAttackTimer = 0
    ;(sim as unknown as { tickBasicAttack(): void }).tickBasicAttack()
    expect(sim.heroMp).toBe(Math.floor(maxMp * data.heroes.mp.basicAttackRestorePct))
  })
})

describe('地区击杀手感（普攻与技能独立出手：小怪 ~4 下 / 精英 ~7 下 / BOSS ~13 下）', () => {
  beforeEach(() => {
    // 0.1：不触发精英判定（< 0.08 才出精英）、必中、不暴击、随机浮动固定；同时普通怪模板取到 normal。
    vi.spyOn(Math, 'random').mockReturnValue(0.1)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // 等级匹配的期望英雄（地区 19 · Lv65），面板由后端 compute_stats 导出。
  // 生命 / 防御刻意拉高，只观察「击杀所需命中次数」，不受阵亡重置干扰。
  function expectedHero(overrides: Partial<HeroStats> = {}): HeroStats {
    return makeStats({
      level: 66,
      jobId: 'DRG',
      mainAttr: 'str',
      attack: 3517.35,
      magicAttack: 2330.36,
      maxMp: 551.11,
      mpRegen: 12.08,
      maxHp: 1e9,
      hpRegen: 0,
      physDef: 1e6,
      magicDef: 1e6,
      dodgePct: 0,
      attackSpeedPct: 24.75,
      hitRatePct: 1.32,
      critRatePct: 0,
      critDamagePct: 134.11,
      dhRatePct: 0,
      detBonusPct: 0,
      ...overrides,
    })
  }

  /**
   * 模拟整轮刷怪，按怪物种类收集「击杀所需命中次数」。
   * 直接统计 pushFloat 调用，避免浮动数字上限（MAX_FLOAT=12）导致高爆发时事件被丢弃、计数偏小。
   */
  function collectHits(killsRequired: number, stats: HeroStats): Record<string, number[]> {
    const spy = vi.spyOn(
      BattleSimulator.prototype as unknown as { pushFloat: (...a: unknown[]) => void },
      'pushFloat',
    )
    const sim = new BattleSimulator({ stats, regionId: 19, killsRequired, spawnInterval: 1, killCount: 0 })
    sim.start()
    const byKind: Record<string, number[]> = { normal: [], elite: [], boss: [] }
    let hits = 0
    let prev: MonsterStats | null = null
    for (let i = 0; i < 20000 && sim.phase !== 'cleared'; i += 1) {
      const before = spy.mock.calls.length
      sim.tick(0.05)
      const current = sim.monster
      if (current !== prev) {
        if (prev) byKind[prev.kind].push(hits)
        prev = current
        hits = 0
      }
      hits += spy.mock.calls
        .slice(before)
        .filter((c) => c[1] === 'monster' && /^\d/.test(String(c[0]))).length
    }
    spy.mockRestore()
    return byKind
  }

  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length

  // 按地区 19 真实的 20 杀额度取样：开局大招会秒掉最早几只，随后才进入稳定节奏。
  const KILLS_REQUIRED = 20

  it('普通小怪平均约 4 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero()).normal
    expect(hits.length).toBeGreaterThanOrEqual(KILLS_REQUIRED)
    expect(avg(hits)).toBeGreaterThanOrEqual(3)
    expect(avg(hits)).toBeLessThanOrEqual(5.5)
  })

  it('精英怪平均约 7 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero({ termMods: { eliteChancePct: 100 } })).elite
    expect(hits.length).toBeGreaterThanOrEqual(KILLS_REQUIRED)
    expect(avg(hits)).toBeGreaterThanOrEqual(4.5)
    expect(avg(hits)).toBeLessThanOrEqual(8)
  })

  it('关底 BOSS 约 13 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero()).boss
    expect(hits).toHaveLength(1)
    expect(hits[0]).toBeGreaterThanOrEqual(8)
    expect(hits[0]).toBeLessThanOrEqual(22)
  })

  it('单次命中对关底 BOSS 的伤害不超过其最大生命 20%（避免爆发 / 暴击秒杀）', () => {
    const region = getRegion(19)!
    const boss = bossStats(region)
    // 攻击力远高于 BOSS 生命，单次普攻也必然触顶，因而无需依赖 RNG 取最大值。
    const sim = new BattleSimulator({ stats: expectedHero({ attack: 1e9 }), regionId: 19 })
    ;(sim as unknown as { setMonster(m: MonsterStats): void }).setMonster(boss)
    const before = sim.monsterHp
    ;(sim as unknown as { tickBasicAttack(): void }).tickBasicAttack()
    const dealt = before - sim.monsterHp
    expect(dealt).toBeGreaterThan(0)
    expect(dealt).toBeLessThanOrEqual(Math.floor(boss.hp * 0.2))
    expect(sim.monsterHp).toBeGreaterThan(0) // 不会被单次命中秒杀
  })
})

describe('彩蛋英雄技能', () => {
  /** 访问私有 cast 以直接驱动技能释放。 */
  function forceCast(sim: BattleSimulator, skillId: string): void {
    const skill = sim.skills.find((s) => s.id === skillId)
    if (!skill) throw new Error(`skill not found: ${skillId}`)
    ;(sim as unknown as { cast(s: unknown): void }).cast(skill)
  }

  const attacker: MonsterStats = {
    id: 'dummy', regionId: 0, name: '木桩', templateId: 'dummy', kind: 'boss',
    hp: 1e12, attack: 1000, defense: 0, attackInterval: 1, level: 100, resistancePct: 0,
  }

  it('Astgen 使用黑魔法师时只拥有「崩溃」', () => {
    const sim = new BattleSimulator({ stats: makeStats({ jobId: 'BLM' }), regionId: 1, eggId: 'astgen' })
    const ids = sim.skills.map((s) => s.id)
    expect(ids).toEqual(['eggCrash'])
  })

  it('彩蛋英雄绑定职业不匹配时不影响正常技能组', () => {
    const sim = new BattleSimulator({ stats: makeStats({ jobId: 'SAM' }), regionId: 1, eggId: 'astgen' })
    const ids = sim.skills.map((s) => s.id)
    expect(ids).not.toContain('eggCrash')
    expect(ids).toEqual(data.jobById['SAM'].skills.map((s) => s.id))
  })

  it('追加型彩蛋技能加在职业技能之外', () => {
    const sim = new BattleSimulator({ stats: makeStats({ jobId: 'SAM' }), regionId: 1, eggId: 'gujiu' })
    const ids = sim.skills.map((s) => s.id)
    expect(ids).toContain('eggLogs')
    expect(ids).toHaveLength(data.jobById['SAM'].skills.length + 1)
  })

  it('「Logs」提供技能威力 +50% 的限时增益', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'SAM', termMods: {} }),
      regionId: 1,
      eggId: 'gujiu',
    })
    forceCast(sim, 'eggLogs')
    expect(sim.stats.termMods.skillDamagePct).toBeCloseTo(50, 5)
  })

  it('「割草」使接下来 2 次技能威力翻倍并逐次消耗', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'RPR', attack: 1000 }),
      raid: { bosses: [attacker], enrage: null },
      eggId: 'jibian',
    })
    sim.start()
    sim.doublePowerCharges = 2
    forceCast(sim, data.jobById['RPR'].skills.find((s) => s.potency > 0)!.id)
    expect(sim.doublePowerCharges).toBe(1)
  })

  it('「我布道啊」的免疫逐次消耗，免疫期间不掉血', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'DRK', maxHp: 100000, physDef: 0, dodgePct: 0, tenacityPct: 0 }),
      raid: { bosses: [attacker], enrage: null },
    })
    sim.start()
    sim.immunityCharges = 2
    const hp0 = sim.heroHp

    sim.tick(1.0)
    expect(sim.immunityCharges).toBe(1)
    expect(sim.heroHp).toBe(hp0)

    sim.tick(1.0)
    expect(sim.immunityCharges).toBe(0)
    expect(sim.heroHp).toBe(hp0)

    sim.tick(1.0)
    expect(sim.heroHp).toBeLessThan(hp0)
  })

  it('「拔豆芽」使接下来 10 个怪物的经验/金币翻倍', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0.5)
    try {
      const run = (charges: number): number => {
        const sim = new BattleSimulator({
          stats: makeStats({ jobId: 'DRG', attack: 1e7, maxHp: 1e7, dodgePct: 0 }),
          regionId: 1,
          killsRequired: 100,
          spawnInterval: 1,
          killCount: 0,
        })
        sim.start()
        sim.doubleRewardCharges = charges
        for (let i = 0; i < 200 && sim.pendingKills.length === 0; i += 1) sim.tick(0.05)
        return sim.pendingKills[0]?.gold ?? 0
      }
      const plain = run(0)
      expect(plain).toBeGreaterThan(0)
      expect(run(1)).toBe(plain * 2)
    } finally {
      spy.mockRestore()
    }
  })

  it('俍十四为任意职业提供经验被动且不追加技能', () => {
    const egg = data.eggHeroes.byId['liangshisi']
    expect(egg.jobId).toBeNull()
    expect(egg.passive).toEqual({ type: 'expGainBonus', value: 0.25 })
    expect(eggSkillSet('liangshisi', 'WAR')).toBeNull()
    expect(eggSkillSet('liangshisi', 'BLM')).toBeNull()
  })

  it('「水群」使接下来 5 次技能魔力消耗减半并逐次消耗', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'PLD', maxMp: 5000, attack: 1000 }),
      raid: { bosses: [attacker], enrage: null },
      eggId: 'qingfeng',
    })
    sim.start()
    forceCast(sim, 'eggWaterGroup')
    expect(sim.halfMpCharges).toBe(5)

    const skill = sim.skills.find((s) => s.mpCost > 0)!
    const scale =
      skill.damageType === 'magical'
        ? data.heroes.mp.magicalSkillCostScale
        : data.heroes.mp.physicalSkillCostScale
    const raw = Math.floor(skill.mpCost * scale)
    const before = sim.heroMp
    forceCast(sim, skill.id)
    expect(before - sim.heroMp).toBe(Math.floor(raw / 2))
    expect(sim.halfMpCharges).toBe(4)
  })

  it('「苍天之龙骑士」恢复其他技能冷却但不重置自身', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ jobId: 'DRG', attack: 1000 }),
      raid: { bosses: [attacker], enrage: null },
      eggId: 'meiruoyu',
    })
    sim.start()
    const other = sim.skills.find((s) => s.id !== 'eggAzureDragoon')!
    sim.cooldowns[other.id] = 30
    forceCast(sim, 'eggAzureDragoon')
    expect(sim.cooldowns[other.id]).toBe(0)
    expect(sim.cooldowns['eggAzureDragoon']).toBeGreaterThan(0)
  })

  it('「术道恒久」使自身治疗量提高 100%（10s）', () => {
    const healSkill = data.jobById['SGE'].skills.find((s) =>
      s.effects.some((e) => e.type === 'heal'),
    )!
    const healAmount = (eggId: string | null): number => {
      const sim = new BattleSimulator({
        stats: makeStats({ jobId: 'SGE', maxHp: 100000, hpRegen: 0 }),
        raid: { bosses: [attacker], enrage: null },
        eggId,
      })
      sim.start()
      if (eggId) forceCast(sim, 'eggEternalWay')
      sim.heroHp = 1000
      forceCast(sim, healSkill.id)
      return sim.heroHp - 1000
    }
    const plain = healAmount(null)
    expect(plain).toBeGreaterThan(0)
    expect(healAmount('aolongbaiban')).toBeCloseTo(plain * 2, 5)
  })

  it('新增彩蛋：牙子 / 罗洁愛尔 / 明岚 配置正确', () => {
    expect(data.eggHeroes.byId['yazi']).toMatchObject({
      jobId: 'MCH',
      attrBias: 'dex',
      talent: 'legendary',
      passive: { type: 'normalMobPotency100Bonus', value: 1 },
    })
    expect(data.eggHeroes.byId['luojieaier']).toMatchObject({
      jobId: null,
      attrBias: 'int',
      talent: 'legendary',
      passive: { type: 'craftExtraChance', value: 0.25 },
    })
    expect(data.eggHeroes.byId['minglan']).toMatchObject({
      jobId: 'VPR',
      attrBias: 'dex',
      talent: 'legendary',
    })
    expect(eggSkillSet('yazi', 'MCH')).toBeNull()
    expect(eggSkillSet('luojieaier', 'WAR')).toBeNull()
    expect(eggSkillSet('minglan', 'VPR')?.skills.map((s) => s.id)).toEqual(['eggSleep'])
    expect(eggSkillSet('minglan', 'MCH')).toBeNull()
  })

  it('「战斗爽」使威力 100% 的技能对战普通怪物时威力翻倍，对 BOSS 无效', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0.5)
    try {
      const stats = makeStats({
        jobId: 'MCH',
        attack: 1000,
        critRatePct: 0,
        dhRatePct: 0,
        detBonusPct: 0,
        termMods: {},
      })
      const dummy = (kind: MonsterStats['kind']): MonsterStats => ({
        id: 'dummy',
        regionId: 0,
        name: '木桩',
        templateId: 'normal',
        kind,
        hp: 1e12,
        attack: 0,
        defense: 0,
        attackInterval: 1,
        level: 100,
        resistancePct: 0,
      })
      const hit = (eggId: string | null, kind: MonsterStats['kind']): number => {
        const sim = new BattleSimulator({ stats, regionId: 1, eggId })
        ;(sim as unknown as { setMonster(m: MonsterStats): void }).setMonster(dummy(kind))
        const before = sim.monsterHp
        forceCast(sim, 'splitShot')
        return before - sim.monsterHp
      }
      const plain = hit(null, 'normal')
      const doubled = hit('yazi', 'normal')
      expect(plain).toBeGreaterThan(0)
      expect(Math.abs(doubled - plain * 2)).toBeLessThanOrEqual(1)
      expect(hit('yazi', 'boss')).toBe(hit(null, 'boss'))
    } finally {
      spy.mockRestore()
    }
  })

  it('「睡觉」停止攻击 10s 并恢复满血满蓝，期间不释放技能', () => {
    const stats = makeStats({ jobId: 'VPR', maxHp: 100000, maxMp: 500, attack: 1e6 })
    const sim = new BattleSimulator({
      stats,
      raid: { bosses: [attacker], enrage: null },
      eggId: 'minglan',
    })
    expect(sim.skills.map((s) => s.id)).toContain('eggSleep')
    sim.start()
    sim.heroHp = 1000
    sim.heroMp = 0
    forceCast(sim, 'eggSleep')
    expect(sim.heroHp).toBe(100000)
    expect(sim.heroMp).toBe(500)
    expect(sim.sleepTimer).toBe(10)
    expect(sim.cooldowns['eggSleep']).toBeGreaterThan(0)

    const totalCasts = () => Object.values(sim.pendingSkillCasts).reduce((a, b) => a + b, 0)
    const before = totalCasts()
    sim.tick(9)
    expect(totalCasts()).toBe(before)
    sim.tick(2)
    expect(totalCasts()).toBeGreaterThan(before)
  })
})

describe('装备触发效果（proc）', () => {
  it('命中时按概率触发灼烧 DOT 与疾风攻速', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ termMods: { burnProcPct: 100, hasteProcPct: 100 } }),
      regionId: 1,
    })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    expect(sim.monster).toBeTruthy()

    const engine = sim as unknown as { cast(s: unknown): void }
    engine.cast(ADVENTURER_SKILL)
    const text = sim.log.map((l) => l.text).join(' | ')
    expect(text).toContain('灼烧')
    expect(text).toContain('疾风')
  })

  it('无 proc 词条时不触发', () => {
    const sim = new BattleSimulator({ stats: makeStats(), regionId: 1 })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    const engine = sim as unknown as { cast(s: unknown): void }
    engine.cast(ADVENTURER_SKILL)
    const text = sim.log.map((l) => l.text).join(' | ')
    expect(text).not.toContain('灼烧')
    expect(text).not.toContain('疾风')
    expect(text).not.toContain('中毒')
    expect(text).not.toContain('双重施法')
  })

  it('命中时按概率触发中毒 / 凋零 / 失明 / 生机 / 灵息', () => {
    const sim = new BattleSimulator({
      stats: makeStats({
        termMods: {
          poisonProcPct: 100,
          witherProcPct: 100,
          blindProcPct: 100,
          hpRegenProcPct: 100,
          mpRegenProcPct: 100,
        },
      }),
      regionId: 1,
    })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    expect(sim.monster).toBeTruthy()
    const engine = sim as unknown as { cast(s: unknown): void }
    engine.cast(ADVENTURER_SKILL)
    const text = sim.log.map((l) => l.text).join(' | ')
    expect(text).toContain('中毒')
    expect(text).toContain('凋零')
    expect(text).toContain('失明')
    expect(text).toContain('生机')
    expect(text).toContain('灵息')
  })

  it('「凋零」降低目标攻击力、「失明」提高怪物失手率', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ dodgePct: 0, termMods: { witherProcPct: 100, blindProcPct: 100 } }),
      regionId: 1,
    })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    const engine = sim as unknown as {
      cast(s: unknown): void
      enemyAttackDown: number
      monsterMissChance: number
    }
    engine.cast(ADVENTURER_SKILL)
    expect(engine.enemyAttackDown).toBeCloseTo(0.2, 5)
    expect(engine.monsterMissChance).toBeCloseTo(25, 5)
  })

  it('「双重施法」按概率额外释放一次技能', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1, termMods: { doubleCastPct: 100 } }),
      regionId: 1,
    })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    const engine = sim as unknown as { cast(s: unknown): void }
    engine.cast(ADVENTURER_SKILL)
    const text = sim.log.map((l) => l.text).join(' | ')
    expect(text).toContain('双重施法')
    expect(sim.log.filter((l) => l.text.includes('普攻 造成')).length).toBeGreaterThanOrEqual(2)
  })

  it('「生机 / 灵息」在持续时间内回复生命与魔力', () => {
    const sim = new BattleSimulator({
      stats: makeStats({
        maxHp: 100000,
        maxMp: 100000,
        hpRegen: 0,
        mpRegen: 0,
        physDef: 1e6,
        magicDef: 1e6,
        termMods: { hpRegenProcPct: 100, mpRegenProcPct: 100 },
      }),
      regionId: 1,
    })
    sim.start()
    for (let i = 0; i < 40 && !sim.monster; i += 1) sim.tick(0.1)
    sim.heroHp = 1000
    sim.heroMp = 0
    const engine = sim as unknown as { cast(s: unknown): void }
    engine.cast(ADVENTURER_SKILL)
    sim.tick(1)
    expect(sim.heroHp).toBeGreaterThan(1000)
    expect(sim.heroMp).toBeGreaterThan(0)
  })

  it('「归魂」缩短 / 「沉魂」延长复活等待时间，最短 1 秒', () => {
    const haste = new BattleSimulator({ stats: makeStats({ termMods: { reviveHastePct: 50 } }), regionId: 1 })
    haste.start()
    ;(haste as unknown as { heroDies(): void }).heroDies()
    expect(haste.deathTimer).toBeCloseTo(5, 5)
    expect(haste.reviveTotal).toBeCloseTo(5, 5)

    const delay = new BattleSimulator({ stats: makeStats({ termMods: { reviveDelayPct: 50 } }), regionId: 1 })
    delay.start()
    ;(delay as unknown as { heroDies(): void }).heroDies()
    expect(delay.deathTimer).toBeCloseTo(15, 5)
  })
})

describe('技能治疗日志', () => {
  it('直接治疗记录实际恢复和溢出，满血不虚报恢复量', () => {
    const sim = new BattleSimulator({ stats: makeStats({ maxHp: 1000 }), regionId: 1 })
    const engine = sim as any
    sim.heroHp = 980
    engine.applyEffects({ name: '测试治疗', effects: [{ type: 'heal', value: .1 }] })
    expect(sim.heroHp).toBe(1000)
    expect(sim.log.at(-1)?.text).toBe('测试治疗 恢复 20 生命值（溢出 80）')
    engine.applyEffects({ name: '测试治疗', effects: [{ type: 'heal', value: .1 }] })
    expect(sim.log.at(-1)?.text).toBe('测试治疗 恢复 0 生命值（溢出 100）')
  })
  it('持续治疗逐跳记录技能名称和有效治疗量', () => {
    const sim = new BattleSimulator({ stats: makeStats({ maxHp: 1000, hpRegen: 0 }), regionId: 1 })
    sim.start()
    sim.heroHp = 100
    const engine = sim as any
    engine.applyEffects({ name: '再生', effects: [{ type: 'healOverTime', value: .01, duration: 5 }] })
    sim.tick(1)
    expect(sim.log.some(e => e.text === '再生（持续治疗） 恢复 10 生命值')).toBe(true)
  })
})

describe('暴击 / 直击标记样式', () => {
  // 持久木桩：始终有目标，且不会被打死。
  const dummy: MonsterStats = {
    id: 'dummy', regionId: 0, name: '木桩', templateId: 'dummy', kind: 'boss',
    hp: 1e12, attack: 0, defense: 0, attackInterval: 999, level: 100, resistancePct: 0,
  }

  function lastHit(critRatePct: number, dhRatePct: number) {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1000, critRatePct, critDamagePct: 200, dhRatePct }),
      raid: { bosses: [dummy], enrage: null },
    })
    sim.start()
    ;(sim as any).cast(ADVENTURER_SKILL)
    return { float: sim.floating.at(-1)!, log: sim.log.at(-1)! }
  }

  it('暴击「!」/ 直击「!」/ 同时触发「!!」，并写入对应色调', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0)
    // rand=0：命中判定先行（不 miss），再按 0 < 触发率 决定直击 / 暴击。
    const cases = [
      { critRatePct: 0, dhRatePct: 100, mark: '!', tone: 'dh' },
      { critRatePct: 100, dhRatePct: 0, mark: '!', tone: 'crit' },
      { critRatePct: 100, dhRatePct: 100, mark: '!!', tone: 'critDh' },
    ]
    for (const c of cases) {
      const { float, log } = lastHit(c.critRatePct, c.dhRatePct)
      expect(float.text.endsWith(c.mark)).toBe(true)
      expect(float.tone).toBe(c.tone)
      expect(log.text.endsWith('伤害' + c.mark)).toBe(true)
      expect(log.tone).toBe(c.tone)
    }
    spy.mockRestore()
  })

  it('未触发时不带标记，沿用普通伤害色调', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0)
    const { float, log } = lastHit(0, 0)
    spy.mockRestore()
    expect(float.text).toMatch(/^\d+$/)
    expect(float.tone).toBe('monster')
    expect(log.text.endsWith('伤害')).toBe(true)
    expect(log.tone).toBe('damage')
  })
})

describe('Lv80+ 地区强化与战斗日志', () => {
  it('Lv80 以上地区的怪物血量/攻击/防御整体 ×5', () => {
    const before = monsterStats(getRegion(28), 'normal') // Lv79：不触发
    const after = monsterStats(getRegion(29), 'normal') // Lv80：触发 ×5
    expect(after.hp).toBeGreaterThan(before.hp * 4)
    expect(after.attack).toBeGreaterThan(before.attack * 4)
    expect(after.defense).toBeGreaterThan(before.defense * 4)
  })

  it('怪物对英雄造成的伤害写入战斗日志', () => {
    const sim = new BattleSimulator({
      stats: makeStats({ attack: 1, maxHp: 1e6, hpRegen: 0 }),
      regionId: 1,
      killsRequired: 8,
      spawnInterval: 1,
      killCount: 0,
    })
    sim.start()
    for (let i = 0; i < 400 && !sim.log.some((e) => /造成 \d+ 点伤害/.test(e.text)); i += 1) sim.tick(0.1)
    const entry = sim.log.find((e) => /^「.+」造成 \d+ 点伤害$/.test(e.text))
    expect(entry).toBeDefined()
    expect(entry!.tone).toBe('danger')
  })

  it('伤害浮动数字约 1 秒后自动移除', () => {
    const sim = new BattleSimulator({ stats: makeStats(), regionId: 1 })
    sim.pushFloating('-100', 'hero', 'monster')
    expect(sim.floating).toHaveLength(1)
    sim.tick(0.5)
    expect(sim.floating).toHaveLength(1)
    sim.tick(0.6)
    expect(sim.floating).toHaveLength(0)
  })
})

describe('战斗难度等级', () => {
  it('难度 0 与基础数值逐位一致', () => {
    for (const regionId of [1, 20, 40]) {
      expect(monsterStats(getRegion(regionId), 'normal', 0)).toEqual(
        monsterStats(getRegion(regionId), 'normal'),
      )
      expect(bossStats(getRegion(regionId), 0)).toEqual(bossStats(getRegion(regionId)))
    }
  })

  it('怪物按加法放大：1 级 +100%、2 级 +200%（×3 而非 ×4）', () => {
    const base = monsterStats(getRegion(10), 'normal', 0)
    const d1 = monsterStats(getRegion(10), 'normal', 1)
    const d2 = monsterStats(getRegion(10), 'normal', 2)
    expect(d1.hp).toBeCloseTo(base.hp * 2, 0)
    expect(d1.attack).toBeCloseTo(base.attack * 1.5, 0)
    expect(d1.defense).toBeCloseTo(base.defense * 2, 0)
    expect(d2.hp).toBeCloseTo(base.hp * 3, 0)
    expect(d2.attack).toBeCloseTo(base.attack * 2, 0)
  })

  it('关底 BOSS 同样受难度影响', () => {
    const base = bossStats(getRegion(10), 0)
    const d3 = bossStats(getRegion(10), 3)
    expect(d3.hp).toBeCloseTo(base.hp * 4, 0)
    expect(d3.attack).toBeCloseTo(base.attack * 2.5, 0)
    expect(d3.defense).toBeCloseTo(base.defense * 4, 0)
  })

  it('玩家攻击/防御按乘法缩小，生命不缩放', () => {
    const stats = makeStats({ attack: 100, magicAttack: 100, physDef: 100, magicDef: 100, maxHp: 500 })
    const scaled = scalePlayerStats(stats, 1)
    expect(scaled.attack).toBeCloseTo(85, 5)
    expect(scaled.magicAttack).toBeCloseTo(85, 5)
    expect(scaled.physDef).toBeCloseTo(90, 5)
    expect(scaled.magicDef).toBeCloseTo(90, 5)
    expect(scaled.maxHp).toBe(500)
    expect(scalePlayerStats(stats, 0)).toBe(stats)
  })

  it('模拟器按难度生成更肉的怪物并降低玩家攻击', () => {
    const spy = vi.spyOn(Math, 'random').mockReturnValue(0.1)
    try {
      const opts = { killsRequired: 99, spawnInterval: 1, killCount: 0, stats: makeStats({ attack: 1000, maxHp: 1e6 }) }
      const base = new BattleSimulator({ ...opts, regionId: 5, difficulty: 0 })
      const hard = new BattleSimulator({ ...opts, regionId: 5, difficulty: 2 })
      base.start()
      hard.start()
      base.tick(1)
      hard.tick(1)
      expect(hard.stats.attack).toBeCloseTo(base.stats.attack * 0.85 ** 2, 5)
      expect(hard.monster!.hp).toBeCloseTo(base.monster!.hp * 3, 0)
    } finally {
      spy.mockRestore()
    }
  })

  it('难度 0 时金币/经验无加成', () => {
    expect(monsterHpMultiplier(0)).toBe(1)
    expect(monsterGoldMultiplier(0)).toBe(1)
    expect(monsterExpMultiplier(0)).toBe(1)
    expect(monsterGoldMultiplier(1)).toBeCloseTo(1.1, 5)
    expect(monsterExpMultiplier(1)).toBeCloseTo(2, 5)
  })
})
