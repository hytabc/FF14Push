/**
 * 世界BOSS 战斗引擎（100ms tick）——后端 `backend/app/services/worldboss_engine.py` 的 TypeScript 复刻。
 *
 * 运算下放客户端：本引擎在浏览器本地推进战斗表现并累计伤害，按窗口把伤害增量上报
 * （`POST /worldboss/report`）；服务端用 `services/worldboss_model.py` 的理论上界夹取。
 * 服务端仍是共享血量 / 贡献 / 奖励的权威。
 *
 * **必须与后端引擎逐位一致**（同种子 + 同配置 → 同结果）：改动任一侧都要同步另一侧，
 * 并回归 `worldbossEngine.spec.ts` 的跨语言确定性快照。
 */
import data from '@shared/schema'

export const TICK = 100
const BASIC_CD_MS = 2000
const GCD_MS = 1500
export const STATUS_RUNNING = 'running'

export type WorldBossConfig = typeof data.worldboss

export interface SnapshotStats {
  max_hp: number
  max_mp: number
  mp_regen?: number
  hp_regen?: number
  attack: number
  magic_attack: number
  crit_rate_pct?: number
  crit_damage_pct?: number
  det_bonus_pct?: number
  attack_speed_pct?: number
  phys_def?: number
  magic_def?: number
  main_attr?: string
}

export interface SnapshotSkill {
  id: string
  name?: string
  potency?: number
  cd?: number
  mpCost?: number
  priority?: number
  teamTarget?: string
  effects?: Array<Record<string, unknown>>
}

/** 上阵英雄快照：由服务端 `coop_snapshot` 生成，经 `/worldboss/enter` 下发。 */
export interface WorldBossSnapshot {
  heroId: number
  name: string
  jobId: string
  level: number
  role: string
  levelMultiplier?: number
  skillMultiplier?: number
  healing?: number
  stats: SnapshotStats
  skills: SnapshotSkill[]
}

/** 引擎内部的可变英雄状态（与后端 state['heroes'] 字段一一对应）。 */
export interface EngineHero {
  slot: number
  snapshot: WorldBossSnapshot
  levelMultiplier: number
  hp: number
  mp: number
  deadUntil: number
  cooldowns: Record<string, number>
  nextAttack: number
  gcdUntil: number
  nextHeal: number
  buffs: Array<{ type: string; value: number; until: number }>
  dots: Array<{ until: number; damage: number }>
  slow: Array<{ value: number; until: number }>
  damage: number
  healing: number
  damageTaken: number
  minHpRatio: number
  deaths: number
}

export interface WorldBossEvent {
  seq: number
  at: number
  kind: string
  text: string
  [key: string]: unknown
}

export interface EngineState {
  version: string
  elapsedMs: number
  status: string
  rng: number
  eventSequence: number
  events: WorldBossEvent[]
  heroes: EngineHero[]
  damageDealt: number
  reviveSeconds: number
  bossHpRatio: number
  phase: number
  defenseMultiplier: number
  skillPotencyMultiplier: number
  boss: {
    nextAttack: number
    nextSkill: number
    attackBuff: number
    attackBuffUntil: number
    damageReduce: number
    damageReduceUntil: number
    pendingSkill: { skill: BossSkill; at: number } | null
    skillCasts: number
    lastSkill: string | null
  }
}

export interface BossSkill {
  id: string
  name: string
  effect: string
  potency?: number
  duration?: number
  chargeSeconds?: number
  attackBuff?: number
  damageReduce?: number
  attackSpeedDebuff?: number
}

/** 线性同余随机数（与后端 `random_unit` 逐位一致）。 */
function randomUnit(state: EngineState): number {
  // `>>> 0` 等价于 Python 的 `& 0xffffffff`（乘积 < 2^53，浮点精确）。
  state.rng = (1664525 * state.rng + 1013904223) >>> 0
  return state.rng / 4294967296
}

function pushEvent(state: EngineState, kind: string, text: string, extra: Record<string, unknown> = {}): void {
  state.eventSequence += 1
  state.events.push({ seq: state.eventSequence, at: state.elapsedMs, kind, text, ...extra })
  state.events = state.events.slice(-200)
}

export function newState(config: WorldBossConfig, snapshots: WorldBossSnapshot[], seed = 20260924): EngineState {
  const bossCfg = config.boss
  const state: EngineState = {
    version: config.version,
    elapsedMs: 0,
    status: STATUS_RUNNING,
    rng: seed,
    eventSequence: 0,
    events: [],
    heroes: [],
    damageDealt: 0,
    reviveSeconds: Number(bossCfg.reviveSeconds),
    bossHpRatio: 1,
    phase: 1,
    defenseMultiplier: 1,
    skillPotencyMultiplier: 1,
    boss: {
      nextAttack: Math.trunc(Number(bossCfg.attackIntervalSeconds) * 1000),
      nextSkill: Math.trunc(Number(bossCfg.skillIntervalSeconds) * 1000),
      attackBuff: 0,
      attackBuffUntil: 0,
      damageReduce: 0,
      damageReduceUntil: 0,
      pendingSkill: null,
      skillCasts: 0,
      lastSkill: null,
    },
  }
  snapshots.forEach((snap, slot) => {
    const stats = snap.stats
    state.heroes.push({
      slot,
      snapshot: JSON.parse(JSON.stringify(snap)) as WorldBossSnapshot,
      levelMultiplier: Number(snap.levelMultiplier ?? 1),
      hp: Number(stats.max_hp),
      mp: Number(stats.max_mp),
      deadUntil: 0,
      cooldowns: {},
      nextAttack: 0,
      gcdUntil: 0,
      nextHeal: 0,
      buffs: [],
      dots: [],
      slow: [],
      damage: 0,
      healing: 0,
      damageTaken: 0,
      minHpRatio: 1,
      deaths: 0,
    })
  })
  return state
}

/** 按剩余血量占比结算阶段：血量越低 BOSS 防御越厚、技能威力越高（与后端 `phase_for_ratio` 同源）。 */
export function resolvePhase(state: EngineState, config: WorldBossConfig): void {
  const table = config.phases ?? []
  const ratio = state.bossHpRatio ?? 1
  if (!table.length) return
  let phase = table[0]
  let bestKey = phase.minHpRatio <= ratio ? phase.minHpRatio : -1
  for (const candidate of table) {
    const key = candidate.minHpRatio <= ratio ? candidate.minHpRatio : -1
    if (key > bestKey) {
      bestKey = key
      phase = candidate
    }
  }
  state.defenseMultiplier = Number(phase.defenseMultiplier)
  state.skillPotencyMultiplier = Number(phase.skillPotencyMultiplier)
  if (Number(phase.id) !== state.phase) {
    state.phase = Number(phase.id)
    pushEvent(
      state,
      'phase',
      `BOSS 进入${phase.name}：防御 ×${phase.defenseMultiplier}、技能威力 ×${phase.skillPotencyMultiplier}`,
      { phase: Number(phase.id) },
    )
  }
}

function bossAttackPower(state: EngineState, config: WorldBossConfig): number {
  let base = Number(config.boss.attack)
  if (state.boss.attackBuffUntil > state.elapsedMs) base *= 1 + state.boss.attackBuff
  return base
}

/** 英雄输出折算：BOSS 主动减伤 × 当前阶段防御（defenseMultiplier 越高，英雄输出越低）。 */
function bossDamageTakenFactor(state: EngineState): number {
  let factor = 1
  if (state.boss.damageReduceUntil > state.elapsedMs) factor *= Math.max(0, 1 - state.boss.damageReduce)
  factor /= Math.max(1e-6, state.defenseMultiplier)
  return factor
}

function dealDamage(state: EngineState, hero: EngineHero, amount: number): void {
  const value = Math.max(0, amount) * bossDamageTakenFactor(state)
  hero.damage += value
  state.damageDealt += value
}

// 与后端 `heal_hero(state, hero, amount)` 签名对齐：state 参数在后端同样未使用（保留形参便于对照）。
function healHero(_state: EngineState, hero: EngineHero, amount: number): void {
  if (hero.hp <= 0) return
  const value = Math.max(0, amount) * hero.levelMultiplier
  const actual = Math.min(value, hero.snapshot.stats.max_hp - hero.hp)
  hero.hp += actual
  hero.healing += actual
}

function damageHero(state: EngineState, hero: EngineHero, amount: number, source: string): void {
  if (hero.hp <= 0) return
  const reduction = Math.max(
    0,
    ...hero.buffs
      .filter((b) => b.type === 'damageReduction' && b.until > state.elapsedMs)
      .map((b) => b.value),
  )
  const value = Math.max(0, amount) * (1 - Math.min(0.8, reduction))
  const maxHp = hero.snapshot.stats.max_hp
  hero.damageTaken += Math.min(hero.hp, value)
  // 生命值以整数结算：伤害后向下取整，避免「显示 0 血却仍存活」。存活即至少 1 点，0 表示阵亡。
  hero.hp = Math.max(0, Math.trunc(hero.hp - value))
  hero.minHpRatio = Math.min(hero.minHpRatio, hero.hp / maxHp)
  if (hero.hp <= 0) {
    hero.deadUntil = state.elapsedMs + state.reviveSeconds * 1000
    hero.deaths += 1
    hero.buffs = []
    hero.dots = []
    hero.slow = []
    pushEvent(state, 'death', `${hero.snapshot.name}倒下了`, { slot: hero.slot, source })
  }
}

/** 当前攻速削减系数：1 − 生效中的最大削减（上限 60%）。 */
function slowFactor(hero: EngineHero, now: number): number {
  const active = hero.slow.filter((s) => s.until > now).map((s) => s.value)
  return 1 - Math.min(0.6, active.length ? Math.max(...active) : 0)
}

function autoActions(state: EngineState, hero: EngineHero): void {
  const now = state.elapsedMs
  const snap = hero.snapshot
  const stats = snap.stats
  const role = snap.role ?? 'dps'
  const attack = stats.main_attr === 'int' ? stats.magic_attack : stats.attack
  const buff =
    1 +
    hero.buffs
      .filter((b) => (b.type === 'allDamageBuff' || b.type === 'attackBuff') && b.until > now)
      .reduce((sum, b) => sum + b.value, 0)
  const crit =
    1 + ((stats.crit_rate_pct ?? 0) / 100) * Math.max(0, (stats.crit_damage_pct ?? 0) / 100 - 1)
  const mult = buff * crit * (1 + (stats.det_bonus_pct ?? 0) / 100) * hero.levelMultiplier
  const slow = slowFactor(hero, now)

  if (now >= hero.nextAttack) {
    dealDamage(state, hero, attack * mult * (0.9 + randomUnit(state) * 0.2))
    hero.nextAttack =
      now + Math.trunc(BASIC_CD_MS / Math.max(0.2, (1 + (stats.attack_speed_pct ?? 0) / 100) * slow))
  }

  if (role === 'healer' && now >= hero.nextHeal) {
    const alive = state.heroes.filter((h) => h.hp > 0)
    if (alive.length) {
      let target = alive[0]
      for (const h of alive) {
        if (h.hp / h.snapshot.stats.max_hp < target.hp / target.snapshot.stats.max_hp) target = h
      }
      healHero(state, target, (snap.healing ?? 0) * mult)
    }
    hero.nextHeal = now + 2000
  }

  if (now < hero.gcdUntil) return
  const skills = [...(snap.skills ?? [])].sort((a, b) => (a.priority ?? 3) - (b.priority ?? 3))
  const skill = skills.find((s) => (hero.cooldowns[s.id] ?? 0) <= now && (s.mpCost ?? 0) <= hero.mp)
  if (!skill) return
  hero.mp -= skill.mpCost ?? 0
  hero.gcdUntil = now + Math.trunc(GCD_MS / Math.max(0.2, slow))
  hero.cooldowns[skill.id] = now + Math.trunc(Number(skill.cd ?? 3) * 1000)
  if (skill.potency) {
    dealDamage(
      state,
      hero,
      (attack * Number(skill.potency)) / 100 *
        (snap.skillMultiplier ?? 1) *
        mult *
        (0.9 + randomUnit(state) * 0.2),
    )
  }

  const alive = state.heroes.filter((h) => h.hp > 0)
  for (const effect of skill.effects ?? []) {
    const typ = String(effect.type)
    const value = Number(effect.value ?? 0)
    const duration = Math.trunc(Number(effect.duration ?? 10) * 1000)
    if (typ === 'heal' || typ === 'fullHeal' || typ === 'shield') {
      const targets = skill.teamTarget === 'party' ? alive : [hero]
      for (const ally of targets) {
        if (typ === 'shield') continue
        healHero(state, ally, stats.max_hp * (typ === 'fullHeal' ? 1 : value))
      }
    } else if (typ === 'healOverTime') {
      const targets = skill.teamTarget === 'party' ? alive : [hero]
      for (const ally of targets) {
        ally.buffs.push({
          type: typ,
          value: stats.max_hp * value * hero.levelMultiplier,
          until: now + duration,
        })
      }
    } else if (
      typ === 'damageReduction' ||
      typ === 'allDamageBuff' ||
      typ === 'attackBuff' ||
      typ === 'critRateBuff'
    ) {
      hero.buffs.push({ type: typ, value, until: now + duration })
    }
  }
}

/** 按 BOSS 攻击力 × 威力% 对单个英雄结算伤害（防御减伤）。 */
function hitHero(state: EngineState, config: WorldBossConfig, hero: EngineHero, potencyPct: number): void {
  const power = (bossAttackPower(state, config) * potencyPct) / 100
  const defense = hero.snapshot.stats.phys_def ?? 0
  damageHero(state, hero, Math.max(power * 0.1, power - defense * 0.8), 'BOSS')
}

function castSkill(state: EngineState, config: WorldBossConfig, skill: BossSkill): void {
  const boss = state.boss
  const now = state.elapsedMs
  boss.skillCasts += 1
  boss.lastSkill = skill.id
  pushEvent(state, 'bossSkill', `BOSS 释放「${skill.name}」`, { skillId: skill.id, effect: skill.effect })

  const effect = skill.effect
  if (effect === 'charge') {
    boss.pendingSkill = { skill, at: now + Math.trunc(Number(skill.chargeSeconds ?? 2) * 1000) }
    return
  }
  if (effect === 'enrage') {
    boss.attackBuff = Number(skill.attackBuff ?? 0)
    boss.attackBuffUntil = now + Math.trunc(Number(skill.duration ?? 10) * 1000)
    return
  }
  if (effect === 'shield') {
    boss.damageReduce = Number(skill.damageReduce ?? 0)
    boss.damageReduceUntil = now + Math.trunc(Number(skill.duration ?? 6) * 1000)
    return
  }

  const alive = state.heroes.filter((h) => h.hp > 0)
  if (!alive.length) return
  const potency = Number(skill.potency ?? 0) * state.skillPotencyMultiplier
  const durationMs = Math.trunc(Number(skill.duration ?? 6) * 1000) || 6000
  if (effect === 'nuke') {
    const index = Math.trunc(randomUnit(state) * alive.length) % alive.length
    hitHero(state, config, alive[index], potency)
  } else if (effect === 'aoe') {
    for (const hero of alive) hitHero(state, config, hero, potency)
  } else if (effect === 'dot') {
    const perTick = ((bossAttackPower(state, config) * potency) / 100) * (TICK / durationMs)
    for (const hero of alive) hero.dots.push({ until: now + durationMs, damage: perTick })
  } else if (effect === 'debuff') {
    const slow = Number(skill.attackSpeedDebuff ?? 0)
    for (const hero of alive) {
      hitHero(state, config, hero, potency)
      hero.slow.push({ value: slow, until: now + durationMs })
    }
  }
}

export function step(state: EngineState, config: WorldBossConfig): void {
  if (state.status !== STATUS_RUNNING) return
  state.elapsedMs += TICK
  const now = state.elapsedMs
  const boss = state.boss
  const bossCfg = config.boss
  const skillPool = bossCfg.skillPool as unknown as BossSkill[]
  resolvePhase(state, config)

  for (const hero of state.heroes) {
    if (hero.hp <= 0) {
      if (now >= hero.deadUntil) {
        hero.hp = Number(hero.snapshot.stats.max_hp)
        pushEvent(state, 'revive', `${hero.snapshot.name}复活`, { slot: hero.slot })
      } else {
        continue
      }
    }
    const stats = hero.snapshot.stats
    hero.mp = Math.min(stats.max_mp, hero.mp + (stats.mp_regen ?? 0) * 0.1)
    hero.buffs = hero.buffs.filter((b) => b.until > now)
    hero.dots = hero.dots.filter((d) => d.until > now)
    hero.slow = hero.slow.filter((s) => s.until > now)
    healHero(state, hero, (stats.hp_regen ?? 0) * 0.1)
    for (const dot of hero.dots) damageHero(state, hero, dot.damage, '持续伤害')
    if (hero.hp > 0) autoActions(state, hero)
  }

  // BOSS 普攻：固定间隔，对全部存活英雄生效，与技能计时独立。
  if (now >= boss.nextAttack) {
    for (const hero of state.heroes.filter((h) => h.hp > 0)) {
      const power = bossAttackPower(state, config)
      const defense = hero.snapshot.stats.phys_def ?? 0
      damageHero(state, hero, Math.max(power * 0.1, power - defense * 0.8), bossCfg.name)
    }
    boss.nextAttack = now + Math.trunc(Number(bossCfg.attackIntervalSeconds) * 1000)
  }

  // BOSS 技能：固定间隔随机抽取，独立于普攻。
  const pending = boss.pendingSkill
  if (pending !== null && now >= pending.at) {
    boss.pendingSkill = null
    castSkill(state, config, { ...pending.skill, effect: 'aoe' })
  } else if (now >= boss.nextSkill) {
    const skill = skillPool[Math.trunc(randomUnit(state) * skillPool.length) % skillPool.length]
    boss.nextSkill = now + Math.trunc(Number(bossCfg.skillIntervalSeconds) * 1000)
    castSkill(state, config, skill)
  }
}

export function advance(state: EngineState, config: WorldBossConfig, milliseconds: number): EngineState {
  const ticks = Math.floor(Math.trunc(milliseconds) / TICK)
  for (let i = 0; i < ticks; i += 1) {
    step(state, config)
    if (state.status !== STATUS_RUNNING) break
  }
  return state
}

/** 本地战斗循环：以 100ms 为步长推进，单次调用最多推进 `maxMs` 毫秒（避免长时间卡帧）。 */
export class WorldBossSimulator {
  readonly state: EngineState
  private readonly config: WorldBossConfig

  constructor(snapshots: WorldBossSnapshot[], bossHpRatio = 1, seed = 20260924) {
    this.config = data.worldboss
    this.state = newState(this.config, snapshots, seed)
    this.state.bossHpRatio = bossHpRatio
  }

  /** 同步服务端全局血量占比（决定阶段：防御越厚、技能越强）。 */
  setBossHpRatio(ratio: number): void {
    this.state.bossHpRatio = Math.max(0, Math.min(1, ratio))
  }

  /** 推进 `dtMs` 毫秒（按 100ms 步长对齐）。 */
  tick(dtMs: number): void {
    advance(this.state, this.config, dtMs)
  }

  get heroes(): EngineHero[] {
    return this.state.heroes
  }

  get damageDealt(): number {
    return Math.round(this.state.damageDealt)
  }

  get elapsedMs(): number {
    return this.state.elapsedMs
  }

  get events(): WorldBossEvent[] {
    return this.state.events
  }
}
