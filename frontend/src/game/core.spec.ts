import data from '@shared/schema'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BattleSimulator } from '@/game/core/battle'
import { estimateDps, rollDamage, rollIncoming, secondsToKill, skillCooldown, ADVENTURER_SKILL } from '@/game/core/combat'
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
    expect(ADVENTURER_SKILL.potency).toBe(100)
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
  it('持续施放会耗尽蓝量并回落到普攻', () => {
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
    expect(minMp).toBeLessThanOrEqual(2)
    expect(sim.log.some((e) => e.text.startsWith('普攻'))).toBe(true)
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
    const engine=sim as unknown as {applyEffects(s:unknown):void;bossSkillInterval(s:unknown):number;cast(s:unknown):void}
    engine.applyEffects({name:'测试治疗',effects:[{type:'heal',value:.1},{type:'shield',value:.1},{type:'mpRestore',value:.1}]})
    expect(sim.heroHp).toBeCloseTo(1+Math.floor(sim.stats.maxHp*.1)*.75)
    expect(sim.shield).toBe(Math.floor(sim.stats.maxHp*.1*.75))
    expect(sim.heroMp).toBe(Math.floor(sim.stats.maxMp*.1*.8))
    expect(engine.bossSkillInterval({skillInterval:6})).toBeCloseTo(4.8)
    engine.cast(ADVENTURER_SKILL)
    expect(sim.cooldowns[ADVENTURER_SKILL.id]).toBeCloseTo(skillCooldown(sim.stats,ADVENTURER_SKILL.cd)*1.15)
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
    ;(sim as unknown as { cast(s: unknown): void }).cast(ADVENTURER_SKILL)
    expect(sim.heroMp).toBe(Math.floor(maxMp * data.heroes.mp.basicAttackRestorePct))
  })
})

describe('地区击杀手感（小怪 3 下 / 精英 5 下 / BOSS 10 下）', () => {
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

  /** 模拟整轮刷怪，按怪物种类收集「击杀所需命中次数」。 */
  function collectHits(killsRequired: number, stats: HeroStats): Record<string, number[]> {
    const sim = new BattleSimulator({ stats, regionId: 19, killsRequired, spawnInterval: 1, killCount: 0 })
    sim.start()
    const byKind: Record<string, number[]> = { normal: [], elite: [], boss: [] }
    const seen = new Set<number>()
    let hits = 0
    let prev: MonsterStats | null = null
    for (let i = 0; i < 20000 && sim.phase !== 'cleared'; i += 1) {
      sim.tick(0.05)
      for (const float of sim.floating) {
        if (seen.has(float.id)) continue
        seen.add(float.id)
        if (float.side === 'monster' && /^\d/.test(float.text)) hits += 1
      }
      const current = sim.monster
      if (current !== prev) {
        if (prev) byKind[prev.kind].push(hits)
        prev = current
        hits = 0
      }
    }
    return byKind
  }

  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length

  // 按地区 19 真实的 20 杀额度取样：开局大招会秒掉最早几只，随后才进入稳定节奏。
  const KILLS_REQUIRED = 20

  it('普通小怪平均约 3 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero()).normal
    expect(hits.length).toBeGreaterThanOrEqual(KILLS_REQUIRED)
    expect(avg(hits)).toBeGreaterThanOrEqual(2.5)
    expect(avg(hits)).toBeLessThanOrEqual(4.5)
  })

  it('精英怪平均约 5 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero({ termMods: { eliteChancePct: 100 } })).elite
    expect(hits.length).toBeGreaterThanOrEqual(KILLS_REQUIRED)
    expect(avg(hits)).toBeGreaterThanOrEqual(4)
    expect(avg(hits)).toBeLessThanOrEqual(7)
  })

  it('关底 BOSS 约 10 下', () => {
    const hits = collectHits(KILLS_REQUIRED, expectedHero()).boss
    expect(hits).toHaveLength(1)
    expect(hits[0]).toBeGreaterThanOrEqual(6)
    expect(hits[0]).toBeLessThanOrEqual(14)
  })
})
