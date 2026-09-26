/**
 * 世界BOSS 引擎跨语言确定性：与后端 `backend/app/services/worldboss_engine.py`
 * 同种子 + 同输入必须得到一致结果。
 *
 * 黄金值由 **Python 引擎**在同一输入下生成（生成脚本见
 * `docs/multiplayer-load-bandwidth-design.md` 阶段 4）。改动任一侧引擎都要同步刷新本快照，
 * 否则客户端表现会与服务端校验模型漂移。
 *
 * 浮点用 `toBeCloseTo`（万级数值下 1e-6 绝对容差 ≈ 10⁻¹² 相对量级）；
 * 整数与枚举（hp / deaths / 计数）必须完全相等。
 */
import data from '@shared/schema'
import { describe, expect, it } from 'vitest'

import { advance, newState, WorldBossSimulator, type WorldBossSnapshot } from './worldboss'

const SNAPSHOTS: WorldBossSnapshot[] = [
  {
    heroId: 1,
    name: '光之战士',
    jobId: 'PLD',
    level: 100,
    role: 'dps',
    levelMultiplier: 1.0,
    skillMultiplier: 1.0,
    healing: 4000.0,
    stats: {
      max_hp: 144112,
      max_mp: 1500,
      mp_regen: 14,
      hp_regen: 50,
      attack: 38060,
      magic_attack: 1000,
      crit_rate_pct: 20,
      crit_damage_pct: 160,
      det_bonus_pct: 10,
      attack_speed_pct: 10,
      phys_def: 5002,
      magic_def: 3600,
      main_attr: 'str',
    },
    skills: [
      { id: 's1', name: '重击', potency: 200, cd: 3, mpCost: 50, priority: 1, effects: [] },
      {
        id: 's2',
        name: '战吼',
        potency: 100,
        cd: 5,
        mpCost: 30,
        priority: 2,
        effects: [{ type: 'allDamageBuff', value: 0.2, duration: 8 }],
      },
      {
        id: 's3',
        name: '铁壁',
        potency: 0,
        cd: 6,
        mpCost: 20,
        priority: 3,
        effects: [{ type: 'damageReduction', value: 0.3, duration: 6 }],
      },
    ],
  },
  {
    heroId: 2,
    name: '龙骑士',
    jobId: 'DRG',
    level: 100,
    role: 'dps',
    levelMultiplier: 0.8,
    skillMultiplier: 1.1,
    healing: 3000.0,
    stats: {
      max_hp: 120000,
      max_mp: 1200,
      mp_regen: 12,
      hp_regen: 40,
      attack: 42000,
      magic_attack: 900,
      crit_rate_pct: 25,
      crit_damage_pct: 155,
      det_bonus_pct: 8,
      attack_speed_pct: 15,
      phys_def: 4200,
      magic_def: 3000,
      main_attr: 'str',
    },
    skills: [
      { id: 'd1', name: '贯穿', potency: 260, cd: 4, mpCost: 60, priority: 1, effects: [] },
      { id: 'd2', name: '龙枪', potency: 120, cd: 6, mpCost: 25, priority: 2, effects: [] },
    ],
  },
  {
    heroId: 3,
    name: '白魔法师',
    jobId: 'WHM',
    level: 100,
    role: 'healer',
    levelMultiplier: 1.0,
    skillMultiplier: 1.0,
    healing: 9000.0,
    stats: {
      max_hp: 110000,
      max_mp: 1800,
      mp_regen: 18,
      hp_regen: 60,
      attack: 12000,
      magic_attack: 30000,
      crit_rate_pct: 15,
      crit_damage_pct: 150,
      det_bonus_pct: 12,
      attack_speed_pct: 5,
      phys_def: 3800,
      magic_def: 5000,
      main_attr: 'int',
    },
    skills: [
      {
        id: 'w1',
        name: '医疗',
        potency: 0,
        cd: 3,
        mpCost: 40,
        priority: 1,
        effects: [{ type: 'heal', value: 0.2, duration: 0 }],
      },
      { id: 'w2', name: '神圣', potency: 180, cd: 5, mpCost: 80, priority: 2, effects: [] },
    ],
  },
]

/** Python 引擎输出的黄金值（seed=20260925）。 */
const GOLDEN = {
  t30000: {
    elapsedMs: 30000,
    damageDealt: 1128185.787855,
    eventSequence: 15,
    phase: 3,
    skillCasts: 6,
    lastSkill: 'frostbind',
    heroes: [
      { slot: 0, hp: 10817.0, mp: 1280.0000000000182, damage: 503934.00159, deaths: 1 },
      { slot: 1, hp: 0.0, mp: 1040.000000000009, damage: 421102.431371, deaths: 2 },
      { slot: 2, hp: 0.0, mp: 1559.999999999991, damage: 203149.354894, deaths: 2 },
    ],
  },
  t6000: {
    elapsedMs: 6000,
    damageDealt: 1103119.700921,
    eventSequence: 1,
    phase: 1,
    skillCasts: 1,
    lastSkill: 'bahamutFlare',
    heroes: [
      { slot: 0, hp: 117064.0, mp: 1432.6000000000054, damage: 469184.292119, deaths: 0 },
      { slot: 1, hp: 95484.0, mp: 1125.8000000000027, damage: 467569.994073, deaths: 0 },
      { slot: 2, hp: 93040.0, mp: 1746.1999999999973, damage: 166365.414729, deaths: 0 },
    ],
  },
}

describe('worldboss engine: 与后端逐位一致', () => {
  it('30 秒 / P3 阶段与 Python 引擎结果一致', () => {
    const state = newState(data.worldboss, SNAPSHOTS, 20260925)
    state.bossHpRatio = 0.25
    advance(state, data.worldboss, 30_000)
    const golden = GOLDEN.t30000

    expect(state.elapsedMs).toBe(golden.elapsedMs)
    expect(state.eventSequence).toBe(golden.eventSequence)
    expect(state.phase).toBe(golden.phase)
    expect(state.boss.skillCasts).toBe(golden.skillCasts)
    expect(state.boss.lastSkill).toBe(golden.lastSkill)
    expect(state.damageDealt).toBeCloseTo(golden.damageDealt, 6)

    state.heroes.forEach((hero, index) => {
      const expected = golden.heroes[index]
      expect(hero.slot).toBe(expected.slot)
      expect(hero.hp).toBe(expected.hp)
      expect(hero.deaths).toBe(expected.deaths)
      expect(hero.damage).toBeCloseTo(expected.damage, 6)
      expect(hero.mp).toBeCloseTo(expected.mp, 6)
    })
  })

  it('6 秒 / P1 阶段与 Python 引擎结果一致', () => {
    const state = newState(data.worldboss, SNAPSHOTS, 20260925)
    state.bossHpRatio = 1.0
    advance(state, data.worldboss, 6_000)
    const golden = GOLDEN.t6000

    expect(state.elapsedMs).toBe(golden.elapsedMs)
    expect(state.eventSequence).toBe(golden.eventSequence)
    expect(state.phase).toBe(golden.phase)
    expect(state.boss.skillCasts).toBe(golden.skillCasts)
    expect(state.boss.lastSkill).toBe(golden.lastSkill)
    expect(state.damageDealt).toBeCloseTo(golden.damageDealt, 6)

    state.heroes.forEach((hero, index) => {
      const expected = golden.heroes[index]
      expect(hero.hp).toBe(expected.hp)
      expect(hero.deaths).toBe(expected.deaths)
      expect(hero.damage).toBeCloseTo(expected.damage, 6)
      expect(hero.mp).toBeCloseTo(expected.mp, 6)
    })
  })

  it('advance 只推进 100ms 整数倍（不足一步的时间不跨步）', () => {
    const state = newState(data.worldboss, SNAPSHOTS, 1)
    advance(state, data.worldboss, 250)
    expect(state.elapsedMs).toBe(200)
  })

  it('包装层按 100ms 累计推进：逐帧毫秒（60fps ≈ 16.7ms）不会被丢弃', () => {
    const sim = new WorldBossSimulator(SNAPSHOTS, 1.0, 20260925)
    // 20 帧 × 16.7ms = 334ms → 推进 3 个整步（300ms），余数 34ms 留到后续帧。
    for (let i = 0; i < 20; i += 1) sim.tick(16.7)
    expect(sim.elapsedMs).toBe(300)
    expect(sim.damageDealt).toBeGreaterThan(0)

    // 不足一步时不推进，但余数会累积：50ms + 50ms = 100ms → 1 步。
    const remainder = new WorldBossSimulator(SNAPSHOTS, 1.0, 1)
    remainder.tick(50)
    expect(remainder.elapsedMs).toBe(0)
    remainder.tick(50)
    expect(remainder.elapsedMs).toBe(100)
  })
})

/** BOSS 不出手的场景配置：只保留 hero 自身的出手，用于隔离 DOT / HOT 结算。 */
const DOT_CFG = {
  ...data.worldboss,
  boss: {
    ...data.worldboss.boss,
    attack: 0,
    attackIntervalSeconds: 9999,
    skillIntervalSeconds: 9999,
  },
}

describe('worldboss engine: DOT / HOT 每 3 秒结算（跨语言一致）', () => {
  it('注入 DOT 与 HOT 后与 Python 引擎逐位一致', () => {
    const state = newState(DOT_CFG, [SNAPSHOTS[0]], 20260925)
    state.heroes[0].hp = 100000
    state.heroes[0].dots.push({ until: 6000, damage: 50, acc: 0 })
    state.heroes[0].buffs.push({ type: 'healOverTime', value: 100, until: 12000, acc: 0 })
    advance(state, DOT_CFG, 12000)
    const hero = state.heroes[0]
    expect(state.elapsedMs).toBe(12000)
    expect(hero.damage).toBeCloseTo(925543.5226942768, 6)
    expect(state.damageDealt).toBeCloseTo(925543.5226942768, 6)
    // DOT 净伤 2550（第二次结算被「铁壁」减伤 30%）＋ HOT 1200 ＋ 被动回复 600 → hp 99250 / 治疗 1800。
    expect(hero.hp).toBe(99250)
    expect(hero.healing).toBe(1800)
  })
})
