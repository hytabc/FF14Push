/**
 * 客户端战斗模拟。
 *
 * 只负责表现与「发生了哪些事件」；金币与经验一律以服务端结算为准
 * （装备只能通过抽箱获取，怪物不掉落装备）。
 */
import data from '@shared/schema'

import type { BossSkill, HeroStats, MonsterStats, RaidBossEntry, RaidEnrage, RegionDef } from '../types'
import {
  ADVENTURER_SKILL,
  attackSpeedFactor,
  isMagical,
  jobSkills,
  powerAttack,
  rollDamage,
  rollIncoming,
  skillCooldown,
  skillDamageMultiplier,
  type SkillLike,
} from './combat'
import { eggNormalMobPotency100Bonus, eggSkillSet } from './egg'
import {
  monsterAttackMultiplier,
  monsterExpMultiplier,
  monsterGoldMultiplier,
  monsterHpMultiplier,
  playerAttackMultiplier,
  playerDefenseMultiplier,
  scalePlayerStats,
} from './difficulty'
import {
  bossStats,
  eliteChance,
  getRegion,
  monsterStats,
  NO_LEVEL_PENALTY,
  regionTemplates,
  type LevelPenalty,
} from './regions'

export interface KillRecord {
  monsterId: string
  gold: number
  exp: number
}

export interface LogEntry {
  id: number
  text: string
  tone:
    | 'normal'
    | 'skill'
    | 'damage'
    | 'loot'
    | 'danger'
    | 'system'
    | 'boss'
    /** 暴击 / 直击 / 同时触发：样式不同（见 MainView / RaidView 的 logTone）。 */
    | 'crit'
    | 'dh'
    | 'critDh'
}

type FloatTone = 'hero' | 'monster' | 'crit' | 'dh' | 'critDh' | 'miss'

/** 一次伤害的命中类型色调：暴击 / 直击 / 双触发。 */
type HitTone = 'crit' | 'dh' | 'critDh'

/** 伤害标记：暴击「!」、直击「!」、同时触发「!!」。 */
function hitMark(isCrit: boolean, isDirectHit: boolean): string {
  if (isCrit && isDirectHit) return '!!'
  return isCrit || isDirectHit ? '!' : ''
}

function hitTone(isCrit: boolean, isDirectHit: boolean): HitTone {
  if (isCrit && isDirectHit) return 'critDh'
  return isCrit ? 'crit' : 'dh'
}

export interface FloatingText {
  id: number
  text: string
  tone: FloatTone
  side: 'hero' | 'monster'
  /** 剩余存活秒数，≤0 时移除。 */
  remaining: number
}

type Phase = 'idle' | 'mob' | 'boss' | 'dead' | 'cleared'

interface ActiveBuff {
  stat: string
  value: number
  remaining: number
  name: string
}

/** 一个敌方单位（地区战斗只有 1 个；高难副本可能有 2 个 BOSS）。 */
interface EnemyState {
  stats: MonsterStats
  hp: number
  maxHp: number
  attackTimer: number
  enraged: boolean
  /** 副本 BOSS 共享技能冷却：归零后从技能池随机抽一个释放。 */
  pendingSkill: { skill: BossSkill; remaining: number } | null
  skillTimer: number
  /** BOSS 自身增益：减伤（damageReduce）/ 增伤（attackBuff）。 */
  selfBuffs: Array<{ stat: string; value: number; remaining: number }>
}

const MAX_LOG = 160
const MAX_FLOAT = 12
/** 伤害浮动数字的存活时长（秒）：到期自动移除，UI 侧播放淡出。 */
const FLOAT_LIFE = 1
/** 单次命中对地区关底 BOSS 的伤害上限（占其最大生命 %），见 `bosses.json:maxHitDamagePct`。 */
const BOSS_MAX_HIT_PCT = Number(data.bosses.maxHitDamagePct ?? 100)

/** 装备词条扩展机制参数（`combat.json:equipEffects`）。概率/强度由词条值承载，此处只放效果量与阈值。 */
const EQUIP = ((data.combat as Record<string, any>).equipEffects ?? {}) as {
  proc?: {
    bleed?: { potencyPct: number; durationSec: number }
    defBreak?: { defenseDownPct: number; durationSec: number }
    slow?: { attackSpeedDownPct: number; durationSec: number }
    stun?: { durationSec: number }
    reflect?: { damagePct: number }
    vengeance?: { attackBuffPct: number; durationSec: number }
    aegis?: { maxHpShieldPct: number; durationSec: number }
    resolve?: { maxMpRestorePct: number }
  }
  conditional?: {
    lowHp?: { hpThresholdPct: number }
    opening?: { windowSec: number }
    boss?: { kinds: string[] }
    lowMp?: { mpThresholdPct: number }
  }
  growth?: {
    killStackAttackPct?: { maxStacks: number }
    hitStackSpeedPct?: { maxStacks: number }
    skillStackDamagePct?: { maxStacks: number }
  }
  convert?: { hpToMp?: { intervalSec: number }; mpSurge?: { basePctOfMp: number }; killRestoreMp?: unknown }
  charge?: {
    chargeBlast?: { hpThresholdPct: number; potencyPct: number }
    chargeShield?: { hpThresholdPct: number }
    chargeHeal?: { castThreshold: number }
  }
  special?: {
    execute?: { hpThresholdPct: number }
    cheatDeath?: { durationSec: number }
    revive?: { reviveHpPct: number }
  }
}

let uid = 0
const nextId = () => ++uid

export class BattleSimulator {
  readonly region: RegionDef | null
  killsRequired: number
  spawnInterval: number
  boss: MonsterStats | null

  phase: Phase = 'idle'
  killCount = 0
  heroHp = 0
  heroMp = 0
  mechanismFailures: string[] = []
  shield = 0
  /** 彩蛋技能「免疫」剩余次数：命中时优先消耗。 */
  immunityCharges = 0
  /** 彩蛋技能「割草」剩余次数：接下来 N 次技能威力翻倍。 */
  doublePowerCharges = 0
  /** 彩蛋技能「拔豆芽」剩余次数：接下来 N 个怪物经验/金币翻倍。 */
  doubleRewardCharges = 0
  /** 彩蛋技能「水群」剩余次数：接下来 N 次技能释放的魔力消耗减半。 */
  halfMpCharges = 0

  log: LogEntry[] = []
  floating: FloatingText[] = []
  cooldowns: Record<string, number> = {}
  gcd = 0
  /** 彩蛋技能「睡觉」剩余停止攻击时间（秒）：>0 时不释放任何技能与普攻。 */
  sleepTimer = 0
  /** 普攻独立冷却计时（秒）：与技能 GCD / CD 完全独立，仅受攻速影响。 */
  basicAttackTimer = 0
  spawnTimer = 0
  bossTimer = 0
  deathTimer = 0
  /** 本次阵亡的复活等待总时长（秒）：随「归魂 / 沉魂」词条变化，供 UI 计算进度条。 */
  reviveTotal = 0
  bossFightMs = 0
  deathCount = 0

  /** 条件「先手」计时：当前目标登场后的秒数。 */
  private monsterElapsed = 0
  /** 动态成长层数（按词条 stat 键计数）。 */
  private growthCounts: Record<string, number> = {
    killStackAttackPct: 0,
    hitStackSpeedPct: 0,
    skillStackDamagePct: 0,
  }
  /** 累计触发计数：累计造成伤害 / 累计受到伤害 / 累计释放技能次数。 */
  private chargeDamage = 0
  private chargeTaken = 0
  private chargeCasts = 0
  /** 「不死」每场战斗仅触发一次。 */
  private cheatDeathUsed = false

  pendingKills: KillRecord[] = []
  pendingSkillCasts: Record<string, number> = {}
  pendingBossKill = false
  pendingDeath = false

  /** 高难副本模式：仅 BOSS、可切换目标、一方阵亡后另一方狂暴。 */
  readonly isRaid: boolean
  private enemies: EnemyState[] = []
  private targetIndex = 0
  private readonly raidEnrage: RaidEnrage | null

  private baseStats: HeroStats
  private readonly eggId: string | null
  /** 彩蛋被动「战斗爽」：对战普通怪物时，威力恰为 100% 的技能威力加成（0 表示无）。 */
  private readonly normalMobPotency100Bonus: number
  private buffs: ActiveBuff[] = []
  private dots: Array<{ remaining: number; potency: number; tick: number }> = []
  /** 装备命中触发的敌方减益（凋零=减攻 / 失明=降命中 / 破防=降防 / 缓速=降攻速），随目标切换清空。 */
  private enemyDebuffs: Array<{
    stat: 'attackDown' | 'hitDown' | 'defDown' | 'speedDown'
    value: number
    remaining: number
    name: string
  }> = []
  /** BOSS 施加给英雄的持续伤害（高难副本）。 */
  private heroDots: Array<{ remaining: number; potencyPerSec: number; tick: number; source: string }> = []
  private regenTimer = 0
  /** 越级时的等级压制惩罚（英雄等级 ≥ 地区下限则为全 0）。 */
  readonly penalty: LevelPenalty
  /** 地区战斗难度等级（0 = 当前各地区数值）；高难副本恒为 0。 */
  readonly difficulty: number

  constructor(options: {
    stats: HeroStats
    penalty?: LevelPenalty
    regionId?: number
    killsRequired?: number
    spawnInterval?: number
    killCount?: number
    /** 地区战斗难度等级：怪物数值放大、玩家攻击/防御缩小。高难副本不传。 */
    difficulty?: number
    raid?: { bosses: MonsterStats[]; enrage: RaidEnrage | null }
    /** 彩蛋英雄 id：命中对应职业时追加/替换技能。 */
    eggId?: string | null
  }) {
    this.difficulty = Math.max(0, Math.floor(options.difficulty ?? 0))
    this.baseStats = scalePlayerStats(options.stats, this.difficulty)
    this.eggId = options.eggId ?? null
    this.normalMobPotency100Bonus = eggNormalMobPotency100Bonus(this.eggId)
    this.isRaid = options.raid !== undefined
    this.raidEnrage = options.raid?.enrage ?? null
    this.killsRequired = options.killsRequired ?? 0
    this.spawnInterval = options.spawnInterval ?? 1
    this.killCount = options.killCount ?? 0
    this.heroHp = options.stats.maxHp
    this.heroMp = options.stats.maxMp
    this.spawnTimer = 0.6
    this.penalty = options.penalty ?? NO_LEVEL_PENALTY
    this.boss = null

    if (this.isRaid) {
      this.region = null
      this.enemies = (options.raid?.bosses ?? []).map((stats) => this.makeEnemy(stats))
      this.pushLog(`进入高难副本，共 ${this.enemies.length} 个 BOSS`, 'boss')
      return
    }

    this.region = getRegion(options.regionId ?? 1)
    this.boss = bossStats(this.region, this.difficulty)
    this.penalty = options.penalty ?? NO_LEVEL_PENALTY
    this.pushLog(`进入「${this.region.name}」· Lv.${this.region.levelMin}-${this.region.levelMax}`, 'system')
    if (this.difficulty > 0) {
      this.pushLog(
        `难度 ${this.difficulty}：玩家攻击 ×${playerAttackMultiplier(this.difficulty).toFixed(2)}、` +
          `防御 ×${playerDefenseMultiplier(this.difficulty).toFixed(2)}；` +
          `怪物生命 ×${monsterHpMultiplier(this.difficulty).toFixed(2)}、` +
          `攻击 ×${monsterAttackMultiplier(this.difficulty).toFixed(2)}、` +
          `金币 ×${monsterGoldMultiplier(this.difficulty).toFixed(2)}`,
        'system',
      )
    }
    if (this.penalty.hitRatePenaltyPct > 0) {
      this.pushLog(
        `战力差距惩罚，命中 -${this.penalty.hitRatePenaltyPct.toFixed(0)}%、` +
          `伤害 -${this.penalty.damageDealtPenaltyPct.toFixed(0)}%、受到伤害 +${this.penalty.damageTakenBonusPct.toFixed(0)}%、` +
          `防御 -${this.penalty.defenseIgnorePct.toFixed(0)}%`,
        'system',
      )
    }
  }

  // ---------- 敌方单位：对外保持「当前目标」视角，兼容地区战斗的既有读取 ----------

  private get current(): EnemyState | undefined {
    return this.enemies[this.targetIndex]
  }

  get monster(): MonsterStats | null {
    return this.current?.stats ?? null
  }

  get monsterHp(): number {
    return this.current?.hp ?? 0
  }

  set monsterHp(value: number) {
    if (this.current) this.current.hp = value
  }

  get monsterMaxHp(): number {
    return this.current?.maxHp ?? 0
  }

  private get monsterAttackTimer(): number {
    return this.current?.attackTimer ?? 0
  }

  private set monsterAttackTimer(value: number) {
    if (this.current) this.current.attackTimer = value
  }

  /** 当前目标受到的伤害减免（BOSS 自带抗性 + 狂暴减伤 + 高难技能减伤）。 */
  private targetResistance(): number {
    const enemy = this.current
    if (!enemy) return 0
    const innate = Number(enemy.stats.resistancePct ?? 0)
    const enrage = enemy.enraged && this.raidEnrage ? Number(this.raidEnrage.damageReductionPct) : 0
    const skillDr =
      enemy.selfBuffs.reduce((sum, b) => (b.stat === 'damageReduce' ? sum + b.value : sum), 0) * 100
    return Math.min(90, innate + enrage + skillDr)
  }

  /** 当前目标的攻击力倍率（高难技能的增伤）。 */
  private bossAttackMultiplier(): number {
    const enemy = this.current
    if (!enemy) return 1
    const buff = enemy.selfBuffs.reduce((sum, b) => (b.stat === 'attackBuff' ? sum + b.value : sum), 0)
    return 1 + buff
  }

  /** 装备「凋零」对当前目标的减攻比例（0-0.8）。 */
  private get enemyAttackDown(): number {
    return Math.min(0.8, this.enemyDebuffs.reduce((sum, b) => (b.stat === 'attackDown' ? sum + b.value : sum), 0))
  }

  /** 装备「破防」对当前目标的降防比例（0-0.8），在伤害结算中削减目标防御。 */
  private get enemyDefenseDown(): number {
    return Math.min(0.8, this.enemyDebuffs.reduce((sum, b) => (b.stat === 'defDown' ? sum + b.value : sum), 0))
  }

  /** 装备「缓速」对当前目标的攻速削减比例（0-0.8），在出手间隔上生效。 */
  private get enemySpeedDown(): number {
    return Math.min(0.8, this.enemyDebuffs.reduce((sum, b) => (b.stat === 'speedDown' ? sum + b.value : sum), 0))
  }

  /** 当前目标的实际防御（含「破防」削减）。 */
  private get targetDefense(): number {
    return Math.max(0, (this.monster?.defense ?? 0) * (1 - this.enemyDefenseDown))
  }

  /** 怪物出手的失手率（%）：英雄闪避 + 装备「失明」加成，上限 75。 */
  private get monsterMissChance(): number {
    const blind = this.enemyDebuffs.reduce((sum, b) => (b.stat === 'hitDown' ? sum + b.value : sum), 0) * 100
    return Math.min(75, this.stats.dodgePct + blind)
  }

  /** 副本战斗面板用：所有 BOSS 的血量快照。 */
  bossEntries(): RaidBossEntry[] {
    return this.enemies.map((enemy, index) => ({
      id: enemy.stats.id,
      name: enemy.stats.name,
      hp: Math.max(0, enemy.hp),
      maxHp: enemy.maxHp,
      hpPct: enemy.maxHp > 0 ? Math.max(0, (enemy.hp / enemy.maxHp) * 100) : 0,
      enraged: enemy.enraged,
      isTarget: index === this.targetIndex,
      skillNames: (enemy.stats.skills ?? []).map((s) => s.name),
    }))
  }

  /** 切换攻击目标（仅高难副本可用）。 */
  selectTarget(index: number): void {
    if (!this.isRaid || index < 0 || index >= this.enemies.length || index === this.targetIndex) return
    this.targetIndex = index
    this.dots = []
    this.enemyDebuffs = []
    this.monsterElapsed = 0
    this.chargeDamage = 0
    this.pushLog(`切换目标 →「${this.enemies[index].stats.name}」`, 'system')
  }

  get stats(): HeroStats {
    const mods = this.baseStats.termMods
    const hasGrowth = Boolean(mods.killStackAttackPct || mods.hitStackSpeedPct)
    const hasConditional = Boolean(mods.lowHpAttackPct)
    if (this.buffs.length === 0 && !hasGrowth && !hasConditional) return this.baseStats
    const clone: HeroStats = { ...this.baseStats, termMods: { ...this.baseStats.termMods } }
    // 动态成长：战意（攻击）/ 锐意（攻速），层数由战斗事件累加。
    const g = this.growthCounts
    if (mods.killStackAttackPct && g.killStackAttackPct > 0) {
      const m = 1 + (g.killStackAttackPct * mods.killStackAttackPct) / 100
      clone.attack *= m
      clone.magicAttack *= m
    }
    if (mods.hitStackSpeedPct && g.hitStackSpeedPct > 0) {
      clone.attackSpeedPct += g.hitStackSpeedPct * mods.hitStackSpeedPct
    }
    // 条件：背水（生命低于阈值时攻击提升）
    const hpPct = this.baseStats.maxHp > 0 ? (this.heroHp / this.baseStats.maxHp) * 100 : 100
    if (mods.lowHpAttackPct && hpPct < (EQUIP.conditional?.lowHp?.hpThresholdPct ?? 50)) {
      const m = 1 + mods.lowHpAttackPct / 100
      clone.attack *= m
      clone.magicAttack *= m
    }
    for (const buff of this.buffs) {
      switch (buff.stat) {
        case 'attackBuff':
          clone.attack *= 1 + buff.value
          clone.magicAttack *= 1 + buff.value
          break
        case 'allDamageBuff':
          clone.detBonusPct += buff.value * 100
          break
        case 'skillDamageBuff':
          clone.termMods.skillDamagePct = (clone.termMods.skillDamagePct ?? 0) + buff.value * 100
          break
        case 'critRateBuff':
          clone.critRatePct += buff.value * 100
          break
        case 'attackSpeedBuff':
          clone.attackSpeedPct += buff.value * 100
          break
        case 'damageReduction':
          clone.tenacityPct += buff.value * 100
          break
        default:
          break
      }
    }
    return clone
  }

  get skills(): SkillLike[] {
    const jobId = this.baseStats.jobId
    const base = jobId === 'adventurer' ? [ADVENTURER_SKILL] : jobSkills(jobId)
    const egg = eggSkillSet(this.eggId, jobId)
    if (!egg) return base
    return egg.replace ? egg.skills : [...egg.skills, ...base]
  }

  get monsterName(): string {
    return this.monster?.name ?? '—'
  }

  get heroHpPct(): number {
    return Math.max(0, Math.min(100, (this.heroHp / this.stats.maxHp) * 100))
  }

  get monsterHpPct(): number {
    return this.monsterMaxHp > 0 ? Math.max(0, (this.monsterHp / this.monsterMaxHp) * 100) : 0
  }

  get mpPct(): number {
    return Math.max(0, Math.min(100, (this.heroMp / this.stats.maxMp) * 100))
  }

  /** 各技能的 CD 状态（剩余秒数 / 总时长 / 已就绪百分比），供 UI 画倒计时进度条。 */
  get skillStates(): Array<{ id: string; remaining: number; total: number; pct: number }> {
    const stats = this.stats
    const cooldownMultiplier = this.penalty.cooldownMultiplier ?? 1
    return this.skills.map((skill) => {
      // 普攻由独立计时器驱动（不占用技能 CD），CD 显示取自该计时器。
      const total = Math.max(
        0.01,
        skill.id === ADVENTURER_SKILL.id
          ? this.basicAttackCooldown()
          : skillCooldown(stats, skill.cd) * cooldownMultiplier,
      )
      const remaining = Math.max(
        0,
        skill.id === ADVENTURER_SKILL.id ? this.basicAttackTimer : this.cooldowns[skill.id] ?? 0,
      )
      return {
        id: skill.id,
        remaining,
        total,
        pct: Math.max(0, Math.min(100, ((total - remaining) / total) * 100)),
      }
    })
  }

  /** 推进 dt 秒。 */
  tick(dt: number): void {
    this.tickFloating(dt)
    if (this.phase === 'idle' || this.phase === 'cleared') return

    this.gcd = Math.max(0, this.gcd - dt)
    this.sleepTimer = Math.max(0, this.sleepTimer - dt)
    this.basicAttackTimer = Math.max(0, this.basicAttackTimer - dt)
    for (const key of Object.keys(this.cooldowns)) {
      this.cooldowns[key] = Math.max(0, this.cooldowns[key] - dt)
    }
    this.buffs = this.buffs.filter((b) => (b.remaining -= dt) > 0)
    this.enemyDebuffs = this.enemyDebuffs.filter((b) => (b.remaining -= dt) > 0)

    // 回复
    this.regenTimer += dt
    if (this.regenTimer >= 1) {
      const ticks = Math.floor(this.regenTimer)
      this.regenTimer -= ticks
      const stats = this.stats
      this.heroHp = Math.min(stats.maxHp, this.heroHp + stats.hpRegen * ticks * this.healMultiplier)
      for (const buff of this.buffs.filter((b) => b.stat === 'healOverTime')) {
        this.restoreHealth(stats.maxHp * buff.value * ticks * this.healMultiplier, buff.name + '（持续治疗）')
      }
      for (const buff of this.buffs.filter((b) => b.stat === 'hpRegenBuff')) {
        this.restoreHealth(stats.maxHp * buff.value * ticks * this.healMultiplier, buff.name + '（持续回复）')
      }
      this.heroMp = Math.min(stats.maxMp, this.heroMp + stats.mpRegen * ticks * (this.penalty.resourceMultiplier ?? 1) * this.lowMpRegenFactor(stats))
      for (const buff of this.buffs.filter((b) => b.stat === 'mpRegenBuff')) {
        this.heroMp = Math.min(
          stats.maxMp,
          this.heroMp + stats.maxMp * buff.value * ticks * (this.penalty.resourceMultiplier ?? 1),
        )
      }
      // 资源转换「转魔」：每秒将最大生命一部分转为魔力（生命不足时不生效）。
      const hpToMp = this.baseStats.termMods.hpToMpPct ?? 0
      if (hpToMp > 0) {
        const cost = stats.maxHp * (hpToMp / 100) * ticks
        if (this.heroHp > cost) {
          this.heroHp -= cost
          this.heroMp = Math.min(stats.maxMp, this.heroMp + stats.maxMp * (hpToMp / 100) * ticks)
        }
      }
    }

    if (this.phase === 'dead') {
      if (this.isRaid) return // 副本阵亡即挑战失败，不复活
      this.deathTimer -= dt
      if (this.deathTimer <= 0) this.revive()
      return
    }

    this.tickDots(dt)
    this.tickHeroDots(dt)

    if (!this.monster) {
      if (this.isRaid) return
      if (this.phase === 'boss') {
        this.bossTimer -= dt
        if (this.bossTimer <= 0) this.spawnBoss()
        return
      }
      this.spawnTimer -= dt
      if (this.spawnTimer <= 0) this.spawnMonster()
      return
    }

    if (this.phase === 'boss') this.bossFightMs += dt * 1000
    this.monsterElapsed += dt

    this.castIfReady()
    this.tickBasicAttack()
    this.tickMonster(dt)
    this.tickBossSkills(dt)
  }

  private tickDots(dt: number): void {
    if (!this.monster || this.dots.length === 0) return
    for (const dot of this.dots) {
      dot.remaining -= dt
      dot.tick -= dt
      if (dot.tick <= 0) {
        dot.tick = 1
        const damage = Math.max(1, Math.floor(powerAttack(this.stats) * (dot.potency / 100)))
        this.monsterHp -= damage
        this.pushFloat(String(damage), 'monster', 'monster')
      }
    }
    this.dots = this.dots.filter((d) => d.remaining > 0)
    if (this.monsterHp <= 0) this.killMonster()
  }

  private spawnMonster(): void {
    const stats = this.stats
    const chance = eliteChance(stats.termMods)
    const templates = regionTemplates()
    let templateId = 'normal'
    if (Math.random() < chance) {
      templateId = 'elite'
    } else {
      const pool = templates.filter((t) => t.id !== 'elite')
      templateId = pool[Math.floor(Math.random() * pool.length)].id
    }
    this.setMonster(monsterStats(this.region!, templateId, this.difficulty))
    this.pushLog(`遭遇 ${this.monster!.name}`, 'normal')
  }

  private spawnBoss(): void {
    this.setMonster({ ...this.boss! })
    this.bossFightMs = 0
    this.pushLog(`关底 BOSS「${this.boss!.name}」出现！`, 'boss')
  }

  /** 构造敌方单位：初始化共享技能冷却与自身增益容器。 */
  private makeEnemy(stats: MonsterStats): EnemyState {
    return {
      stats,
      hp: stats.hp,
      maxHp: stats.hp,
      attackTimer: stats.attackInterval,
      enraged: false,
      skillTimer: this.bossSkillInterval(stats),
      selfBuffs: [],
      pendingSkill: null,
    }
  }

  /** 共享技能 CD（秒）：来自 BOSS 数据，缺省 6 秒。 */
  private bossSkillInterval(stats: MonsterStats): number {
    return Math.max(1, Number(stats.skillInterval ?? 6)) * (this.penalty.windowMultiplier ?? 1)
  }

  private setMonster(monster: MonsterStats): void {
    this.enemies = [this.makeEnemy(monster)]
    this.targetIndex = 0
    this.dots = []
    this.enemyDebuffs = []
    this.heroDots = []
    this.monsterElapsed = 0
    this.chargeDamage = 0
  }

  /** 目标阵亡：移出战斗。副本模式下若仍有存活 BOSS，则对其施加狂暴。 */
  private removeCurrentEnemy(): void {
    this.enemies.splice(this.targetIndex, 1)
    this.dots = []
    this.enemyDebuffs = []
    this.heroDots = []
    this.monsterElapsed = 0
    this.chargeDamage = 0
    if (this.targetIndex >= this.enemies.length) this.targetIndex = Math.max(0, this.enemies.length - 1)
  }

  private enrageSurvivors(): void {
    if (!this.raidEnrage) return
    for (const enemy of this.enemies) {
      if (enemy.enraged) continue
      enemy.enraged = true
      enemy.stats = {
        ...enemy.stats,
        attack: enemy.stats.attack * Number(this.raidEnrage.attackMultiplier),
        attackInterval: Math.max(
          0.5,
          enemy.stats.attackInterval / (1 + Number(this.raidEnrage.attackSpeedBonusPct) / 100),
        ),
      }
      this.pushLog(
        `「${enemy.stats.name}」因同伴阵亡而狂暴！攻击 ×${this.raidEnrage.attackMultiplier}、减伤 +${this.raidEnrage.damageReductionPct}%`,
        'danger',
      )
    }
  }

  private castIfReady(): void {
    if (this.gcd > 0 || this.sleepTimer > 0) return
    // 普攻与技能完全独立（自身计时器驱动，见 tickBasicAttack），此处只挑技能。
    // 技能需「CD 就绪 且 蓝量充足」（PRD 2.7.1-3 / 7.2）。
    const castable = this.skills.filter(
      (skill) =>
        skill.id !== ADVENTURER_SKILL.id &&
        (this.cooldowns[skill.id] ?? 0) <= 0 &&
        this.mpCost(skill) <= this.heroMp,
    )
    if (castable.length === 0) return
    this.cast(this.pickSkill(castable))
  }

  /** 普攻冷却（秒）：受攻速缩短（PRD 2.7.3「攻击速度 影响普攻频率」）。 */
  private basicAttackCooldown(): number {
    const base = skillCooldown(this.stats, ADVENTURER_SKILL.cd)
    return Math.max(0.2, base / attackSpeedFactor(this.stats))
  }

  /**
   * 普攻：与技能完全独立，按自身冷却出手；不占用 GCD，也不受技能 CD / 蓝量影响。
   * 伤害与技能同源：同样结算命中 / 暴击 / 直击（日志与浮动数字带「!」「!!」标记）。
   */
  private tickBasicAttack(): void {
    if (this.basicAttackTimer > 0 || this.sleepTimer > 0) return
    this.basicAttackTimer = this.basicAttackCooldown()
    // 零耗蓝普攻的回蓝兜底：避免蓝量见底后彻底退化为「只能普攻」。
    const stats = this.stats
    const restore = Math.floor(stats.maxMp * Number(data.heroes.mp.basicAttackRestorePct ?? 0))
    if (restore > 0) this.heroMp = Math.min(stats.maxMp, this.heroMp + restore)
    this.resolveDamage(ADVENTURER_SKILL, false)
    // 「连击」：概率追加一次普攻（附加普攻不再判定连击，避免无限递归）。
    const combo = Math.max(0, this.baseStats.termMods.doubleAttackPct ?? 0)
    if (this.monster && combo > 0 && Math.random() * 100 < combo) {
      this.pushLog('「连击」触发，追加一次普攻', 'skill')
      this.resolveDamage(ADVENTURER_SKILL, false)
    }
  }

  private pickSkill(pool: SkillLike[]): SkillLike {
    const sorted = [...pool].sort((a, b) => {
      if (a.priority !== b.priority) return a.priority - b.priority
      return b.potency - a.potency
    })
    return sorted[0] ?? ADVENTURER_SKILL
  }

  private rawMpCost(skill: SkillLike): number {
    const scale = skill.damageType === 'magical' ? data.heroes.mp.magicalSkillCostScale : data.heroes.mp.physicalSkillCostScale
    return Math.floor(skill.mpCost * scale)
  }

  /** 实际魔力消耗：彩蛋「水群」生效时减半（仅对有耗蓝的技能生效）。 */
  private mpCost(skill: SkillLike): number {
    const base = this.rawMpCost(skill)
    return base > 0 && this.halfMpCharges > 0 ? Math.floor(base / 2) : base
  }

  /** 一次技能结算的「伤害 + 效果」部分（不含魔力 / CD / GCD）；双重施法时复用。 */
  private resolveSkillBody(skill: SkillLike): void {
    if (skill.potency > 0 && this.monster) this.resolveDamage(skill, true)
    else this.pushLog(`施放 ${skill.name}`, 'skill')
    this.applyEffects(skill)
  }

  private cast(skill: SkillLike): void {
    const stats = this.stats
    const rawCost = this.rawMpCost(skill)
    const cost = this.mpCost(skill)
    this.heroMp = Math.max(0, this.heroMp - cost)
    if (rawCost > 0 && this.halfMpCharges > 0) {
      this.halfMpCharges -= 1
      this.pushLog(`「水群」生效，${skill.name} 魔力消耗减半（剩余 ${this.halfMpCharges} 次）`, 'skill')
    }
    // 攻速：缩短 GCD
    const speed = attackSpeedFactor(stats)
    this.cooldowns[skill.id] = skillCooldown(stats, skill.cd) * (this.penalty.cooldownMultiplier ?? 1)
    this.gcd = (data.combat.gcdSeconds as number) / speed
    this.pendingSkillCasts[skill.id] = (this.pendingSkillCasts[skill.id] ?? 0) + 1

    // 动态成长「咏唱」：每次释放技能叠加技能伤害层数。
    if (this.baseStats.termMods.skillStackDamagePct) {
      const max = EQUIP.growth?.skillStackDamagePct?.maxStacks ?? 8
      this.growthCounts.skillStackDamagePct = Math.min(max, (this.growthCounts.skillStackDamagePct ?? 0) + 1)
    }
    // 累计触发「咏唱蓄能」：累计释放技能达阈值后治疗。
    this.chargeCasts += 1
    const chargeHeal = this.baseStats.termMods.chargeHealPct ?? 0
    const healThreshold = EQUIP.charge?.chargeHeal?.castThreshold ?? 10
    if (chargeHeal > 0 && this.chargeCasts >= healThreshold) {
      this.chargeCasts = 0
      this.restoreHealth(Math.floor(this.stats.maxHp * (chargeHeal / 100)), '装备「咏唱蓄能」')
    }

    this.resolveSkillBody(skill)

    // 装备「双重施法」：概率额外释放一次（不再扣蓝 / 不重置 CD-GCD / 不再次判定，避免递归）。
    const doubleCast = Math.max(0, this.baseStats.termMods.doubleCastPct ?? 0)
    if (doubleCast > 0 && this.monster && Math.random() * 100 < doubleCast) {
      this.pushLog(`「双重施法」触发，${skill.name} 再次释放`, 'skill')
      this.resolveSkillBody(skill)
    }

    if (this.monster && this.monsterHp <= 0) this.killMonster()
  }

  /**
   * 一次命中结算：伤害 + 浮动数字 + 日志 + proc。
   * isSkill 决定是否消耗充能类彩蛋（「割草」只作用于技能，普攻不吃）。
   */
  private resolveDamage(skill: SkillLike, isSkill: boolean): void {
    const stats = this.stats
    if (!this.monster) return
    const mods = this.baseStats.termMods
    let mult = skillDamageMultiplier(stats, stats.jobId)
    // 条件增伤：先手（开战窗口）/ 讨伐（精英与 BOSS）/ 处决（目标残血）。
    const cond = EQUIP.conditional ?? {}
    if (mods.openingDamagePct && this.monsterElapsed < (cond.opening?.windowSec ?? 10)) {
      mult *= 1 + mods.openingDamagePct / 100
    }
    if (mods.bossDamagePct && (cond.boss?.kinds ?? ['elite', 'boss']).includes(this.monster.kind)) {
      mult *= 1 + mods.bossDamagePct / 100
    }
    const execHp = EQUIP.special?.execute?.hpThresholdPct ?? 30
    if (mods.executePct && this.monsterMaxHp > 0 && (this.monsterHp / this.monsterMaxHp) * 100 < execHp) {
      mult *= 1 + mods.executePct / 100
    }
    // 资源转换「魔力灌注」：技能伤害随当前魔力百分比提升。
    if (mods.mpSurgeDamagePct && stats.maxMp > 0) {
      mult *= 1 + (this.heroMp / stats.maxMp) * (mods.mpSurgeDamagePct / 100)
    }
    // 动态成长「咏唱」：技能伤害按层数提升。
    if (isSkill && mods.skillStackDamagePct && this.growthCounts.skillStackDamagePct > 0) {
      mult *= 1 + (this.growthCounts.skillStackDamagePct * mods.skillStackDamagePct) / 100
    }
    if (isSkill && this.doublePowerCharges > 0) {
      mult *= 2
      this.doublePowerCharges -= 1
      this.pushLog(`${skill.name} 触发「割草」，威力翻倍`, 'skill')
    }
    // 彩蛋被动「战斗爽」：对战普通怪物时，威力恰为 100% 的技能威力翻倍。
    if (
      this.normalMobPotency100Bonus > 0 &&
      skill.potency === 100 &&
      this.monster.kind === 'normal'
    ) {
      mult *= 1 + this.normalMobPotency100Bonus
    }
    const roll = rollDamage(
      stats,
      skill.potency,
      skill.damageType,
      this.targetDefense,
      mult,
      this.penalty,
      this.targetResistance(),
    )
    if (roll.missed) {
      this.pushFloat('未命中', 'monster', 'miss')
      this.pushLog(`${skill.name} 未命中`, 'damage')
      return
    }
    const amount = this.capBossHit(roll.amount)
    this.monsterHp -= amount
    const mark = hitMark(roll.isCrit, roll.isDirectHit)
    this.pushFloat(
      `${amount}${mark}`,
      'monster',
      mark ? hitTone(roll.isCrit, roll.isDirectHit) : 'monster',
    )
    if (mark) this.pushLog(`${skill.name} 造成 ${amount} 伤害${mark}`, hitTone(roll.isCrit, roll.isDirectHit))
    else this.pushLog(`${skill.name} 造成 ${amount} 伤害`, skill.priority === 1 ? 'skill' : 'damage')
    // 动态成长「锐意」：每次命中叠加攻速层数。
    if (mods.hitStackSpeedPct) {
      const max = EQUIP.growth?.hitStackSpeedPct?.maxStacks ?? 10
      this.growthCounts.hitStackSpeedPct = Math.min(max, (this.growthCounts.hitStackSpeedPct ?? 0) + 1)
    }
    // 累计触发「蓄势」：累计造成伤害达阈值后爆发。
    this.chargeDamage += amount
    this.maybeChargeBlast()
    this.rollProcs(stats)
  }

  /** 累计触发「蓄势」：累计造成目标一定比例最大生命的伤害后，触发一次额外爆发。 */
  private maybeChargeBlast(): void {
    if (!this.monster) return
    const bonus = this.baseStats.termMods.chargeBlastPct ?? 0
    const hpThreshold = EQUIP.charge?.chargeBlast?.hpThresholdPct ?? 100
    if (bonus <= 0 || this.monsterMaxHp <= 0) return
    if (this.chargeDamage < this.monsterMaxHp * (hpThreshold / 100)) return
    this.chargeDamage = 0
    const blast = Math.max(1, Math.floor(powerAttack(this.stats) * (bonus / 100)))
    this.monsterHp -= blast
    this.pushFloat(`${blast}`, 'monster', 'monster')
    this.pushLog(`装备触发「蓄势」，造成 ${blast} 伤害`, 'skill')
    if (this.monsterHp <= 0) this.killMonster()
  }

  /** 命中触发效果（proc）：灼烧/中毒 DOT、疾风限时攻速、凋零减攻、失明降命中、生机/灵息持续回复。与后端 `combat_model.proc_dps_bonus` 同源。 */
  private rollProcs(stats: HeroStats): void {
    if (!this.monster) return
    const proc = (data.combat.proc ?? {}) as {
      burn?: { potencyPct: number; durationSec: number }
      poison?: { potencyPct: number; durationSec: number }
      haste?: { attackSpeedPct: number; durationSec: number }
      wither?: { attackDownPct: number; durationSec: number }
      blind?: { hitDownPct: number; durationSec: number }
      hpRegenBuff?: { maxHpPctPerSec: number; durationSec: number }
      mpRegenBuff?: { maxMpPctPerSec: number; durationSec: number }
    }
    // 灼烧 / 中毒：命中概率触发，每秒造成 攻击力 × potencyPct% 的持续伤害。
    const dotProcs: Array<[typeof proc.burn, number | undefined, string]> = [
      [proc.burn, stats.termMods.burnProcPct, '灼烧'],
      [proc.poison, stats.termMods.poisonProcPct, '中毒'],
    ]
    for (const [dot, chancePct, label] of dotProcs) {
      const chance = Math.max(0, chancePct ?? 0)
      if (dot && chance > 0 && Math.random() * 100 < chance) {
        this.dots.push({ remaining: dot.durationSec, potency: dot.potencyPct, tick: 1 })
        this.pushLog(`装备触发「${label}」`, 'skill')
      }
    }
    const hasteChance = Math.max(0, stats.termMods.hasteProcPct ?? 0)
    if (proc.haste && hasteChance > 0 && Math.random() * 100 < hasteChance) {
      this.buffs.push({
        stat: 'attackSpeedBuff',
        value: proc.haste.attackSpeedPct / 100,
        remaining: proc.haste.durationSec,
        name: '疾风',
      })
      this.pushLog('装备触发「疾风」', 'skill')
    }
    // 凋零：降低目标攻击力（持续）。
    const witherChance = Math.max(0, stats.termMods.witherProcPct ?? 0)
    if (proc.wither && witherChance > 0 && Math.random() * 100 < witherChance) {
      this.enemyDebuffs.push({
        stat: 'attackDown',
        value: proc.wither.attackDownPct / 100,
        remaining: proc.wither.durationSec,
        name: '凋零',
      })
      this.pushLog('装备触发「凋零」', 'skill')
    }
    // 失明：降低目标命中率（持续）。
    const blindChance = Math.max(0, stats.termMods.blindProcPct ?? 0)
    if (proc.blind && blindChance > 0 && Math.random() * 100 < blindChance) {
      this.enemyDebuffs.push({
        stat: 'hitDown',
        value: proc.blind.hitDownPct / 100,
        remaining: proc.blind.durationSec,
        name: '失明',
      })
      this.pushLog('装备触发「失明」', 'skill')
    }
    // 扩展 proc（combat.json:equipEffects.proc）：裂伤 / 破防 / 缓速 / 眩晕。
    const equipProc = EQUIP.proc ?? {}
    const bleedChance = Math.max(0, stats.termMods.bleedProcPct ?? 0)
    if (equipProc.bleed && bleedChance > 0 && Math.random() * 100 < bleedChance) {
      this.dots.push({ remaining: equipProc.bleed.durationSec, potency: equipProc.bleed.potencyPct, tick: 1 })
      this.pushLog('装备触发「裂伤」', 'skill')
    }
    const defBreakChance = Math.max(0, stats.termMods.defBreakProcPct ?? 0)
    if (equipProc.defBreak && defBreakChance > 0 && Math.random() * 100 < defBreakChance) {
      this.enemyDebuffs.push({
        stat: 'defDown',
        value: equipProc.defBreak.defenseDownPct / 100,
        remaining: equipProc.defBreak.durationSec,
        name: '破防',
      })
      this.pushLog('装备触发「破防」', 'skill')
    }
    const slowChance = Math.max(0, stats.termMods.slowProcPct ?? 0)
    if (equipProc.slow && slowChance > 0 && Math.random() * 100 < slowChance) {
      this.enemyDebuffs.push({
        stat: 'speedDown',
        value: equipProc.slow.attackSpeedDownPct / 100,
        remaining: equipProc.slow.durationSec,
        name: '缓速',
      })
      this.pushLog('装备触发「缓速」', 'skill')
    }
    const stunChance = Math.max(0, stats.termMods.stunProcPct ?? 0)
    if (equipProc.stun && stunChance > 0 && Math.random() * 100 < stunChance) {
      this.monsterAttackTimer += equipProc.stun.durationSec
      this.pushLog('装备触发「眩晕」', 'skill')
    }
    // 生机 / 灵息：命中概率获得限时持续回复。
    const hpRegenChance = Math.max(0, stats.termMods.hpRegenProcPct ?? 0)
    if (proc.hpRegenBuff && hpRegenChance > 0 && Math.random() * 100 < hpRegenChance) {
      this.buffs.push({
        stat: 'hpRegenBuff',
        value: proc.hpRegenBuff.maxHpPctPerSec,
        remaining: proc.hpRegenBuff.durationSec,
        name: '生机',
      })
      this.pushLog('装备触发「生机」', 'skill')
    }
    const mpRegenChance = Math.max(0, stats.termMods.mpRegenProcPct ?? 0)
    if (proc.mpRegenBuff && mpRegenChance > 0 && Math.random() * 100 < mpRegenChance) {
      this.buffs.push({
        stat: 'mpRegenBuff',
        value: proc.mpRegenBuff.maxMpPctPerSec,
        remaining: proc.mpRegenBuff.durationSec,
        name: '灵息',
      })
      this.pushLog('装备触发「灵息」', 'skill')
    }
  }

  private restoreHealth(amount: number, source: string): void {
    const before = this.heroHp
    this.heroHp = Math.min(this.stats.maxHp, this.heroHp + amount)
    const restored = Math.max(0, this.heroHp - before)
    const shown = Number(restored.toFixed(2))
    const overflow = Number(Math.max(0, amount - restored).toFixed(2))
    this.pushLog(source + ' 恢复 ' + shown + ' 生命值' + (overflow > 0 ? '（溢出 ' + overflow + '）' : ''), 'skill')
    if (restored > 0) this.pushFloat('+' + shown, 'hero', 'hero')
  }

  private applyEffects(skill: SkillLike): void {
    const stats = this.stats
    for (const effect of skill.effects as Array<Record<string, number | string>>) {
      const type = String(effect.type)
      const value = Number(effect.value ?? 0)
      const duration = Number(effect.duration ?? 0)
      switch (type) {
        case 'heal':
        case 'fullHeal': {
          const amount = (type === 'fullHeal' ? stats.maxHp : Math.floor(stats.maxHp * value)) * this.healMultiplier
          this.restoreHealth(amount, skill.name)
          break
        }
        case 'healOverTime':
          this.buffs.push({ stat: 'healOverTime', value, remaining: duration, name: skill.name })
          break
        case 'shield':
          this.shield += Math.floor(stats.maxHp * value * this.healMultiplier)
          break
        case 'mpRestore':
          this.heroMp = Math.min(stats.maxMp, this.heroMp + Math.floor(stats.maxMp * value * (this.penalty.resourceMultiplier ?? 1)))
          break
        case 'dot':
          this.dots.push({ remaining: duration, potency: value * 100, tick: 1 })
          break
        case 'cdReduceAll':
          for (const key of Object.keys(this.cooldowns)) {
            this.cooldowns[key] = Math.max(0, this.cooldowns[key] * (1 - value))
          }
          break
        case 'stun':
          this.monsterAttackTimer += duration
          break
        case 'mpDumpPotency': {
          if (!this.monster) break
          const ratio = stats.maxMp > 0 ? this.heroMp / stats.maxMp : 0
          const maxPotency = Number(effect.maxPotency ?? 600)
          const potency = 400 + (maxPotency - 400) * ratio * 2
          const roll = rollDamage(
            stats,
            potency,
            skill.damageType,
            this.monster.defense,
            1,
            this.penalty,
            this.targetResistance(),
          )
          if (roll.missed) {
            this.pushFloat('未命中', 'monster', 'miss')
          } else {
            const mark = hitMark(roll.isCrit, roll.isDirectHit)
            const amount = this.capBossHit(roll.amount)
            this.monsterHp -= amount
            this.pushFloat(
              `${amount}${mark}`,
              'monster',
              mark ? hitTone(roll.isCrit, roll.isDirectHit) : 'monster',
            )
          }
          this.heroMp = 0
          break
        }
        case 'immunity':
          this.immunityCharges += Math.max(0, Math.floor(value))
          this.pushLog(`获得免疫，接下来 ${this.immunityCharges} 次伤害无效`, 'skill')
          break
        case 'doublePowerCharges':
          this.doublePowerCharges += Math.max(0, Math.floor(value))
          this.pushLog(`接下来 ${this.doublePowerCharges} 次技能威力翻倍`, 'skill')
          break
        case 'doubleRewardCharges':
          this.doubleRewardCharges += Math.max(0, Math.floor(value))
          this.pushLog(`接下来 ${this.doubleRewardCharges} 个怪物经验/金币翻倍`, 'skill')
          break
        case 'mpCostHalveCharges':
          this.halfMpCharges += Math.max(0, Math.floor(value))
          this.pushLog(`接下来 ${this.halfMpCharges} 次技能魔力消耗减半`, 'skill')
          break
        case 'cdResetAll':
          for (const key of Object.keys(this.cooldowns)) {
            if (key !== skill.id) this.cooldowns[key] = 0
          }
          this.pushLog('恢复全部技能冷却时间', 'skill')
          break
        case 'healingBuff':
          this.buffs.push({ stat: 'healingBuff', value, remaining: duration, name: skill.name })
          this.pushLog(`治疗量 +${Math.round(value * 100)}%${duration > 0 ? `（${duration}s）` : ''}`, 'skill')
          break
        case 'sleep':
          this.sleepTimer = Math.max(this.sleepTimer, value)
          this.pushLog(`进入睡眠，停止攻击 ${value}s`, 'skill')
          break
        default:
          if (duration > 0 && (type.endsWith('Buff') || type === 'damageReduction')) {
            this.buffs.push({ stat: type, value, remaining: duration, name: skill.name })
          }
          break
      }
    }
    if (this.heroHp > stats.maxHp) this.heroHp = stats.maxHp
    if (this.monster && this.monsterHp <= 0) this.killMonster()
  }

  /**
   * 单次命中对地区关底 BOSS 的伤害上限（占其最大生命 %，见 `bosses.json:maxHitDamagePct`）：
   * 防止开局技能全就绪时的爆发 / 暴击大招单次秒杀 BOSS。高难副本与联机不走此上限。
   */
  private capBossHit(amount: number): number {
    if (this.isRaid) return amount
    const enemy = this.current
    if (!enemy || enemy.stats.kind !== 'boss') return amount
    const cap = Math.max(1, Math.floor(enemy.maxHp * (BOSS_MAX_HIT_PCT / 100)))
    return Math.min(amount, cap)
  }

  /** 越级时英雄防御的剩余比例（0-1）。等级达标时为 1。 */
  private get defenseScale(): number {
    return Math.max(0, 1 - this.penalty.defenseIgnorePct / 100)
  }

  /** 治疗量倍率：等级压制系数 × 彩蛋「术道恒久」等治疗增益 × 词条「治愈之力」。 */
  private get healMultiplier(): number {
    const buff = this.buffs.reduce((sum, b) => (b.stat === 'healingBuff' ? sum + b.value : sum), 0)
    const power = (this.baseStats.termMods.healPowerPct ?? 0) / 100
    return (this.penalty.healingMultiplier ?? 1) * (1 + buff + power)
  }

  /** 条件「枯竭」：魔力低于阈值时提升魔力恢复的倍率。 */
  private lowMpRegenFactor(stats: HeroStats): number {
    const bonus = this.baseStats.termMods.lowMpRegenPct ?? 0
    if (bonus <= 0 || stats.maxMp <= 0) return 1
    const mpPct = (this.heroMp / stats.maxMp) * 100
    return mpPct < (EQUIP.conditional?.lowMp?.mpThresholdPct ?? 30) ? 1 + bonus / 100 : 1
  }

  /** 消耗一层彩蛋「免疫」：返回 true 表示本次伤害被免疫。 */
  private consumeImmunity(): boolean {
    if (this.immunityCharges <= 0) return false
    this.immunityCharges -= 1
    this.pushFloat('免疫', 'hero', 'hero')
    this.pushLog(`免疫了本次伤害（剩余 ${this.immunityCharges} 次）`, 'skill')
    return true
  }

  /** 护盾获得量倍率（词条「护盾强化」）。 */
  private get shieldMultiplier(): number {
    return 1 + (this.baseStats.termMods.shieldBoostPct ?? 0) / 100
  }

  /**
   * 受击触发（受击类 / 防御类）：格挡减伤 + 反震 / 复仇 / 庇护 / 坚毅概率触发，
   * 并累计「受创蓄力」。返回结算后的伤害；不建模进后端 DPS（仅影响生存与资源）。
   */
  private onHitTaken(stats: HeroStats, damage: number): number {
    const proc = EQUIP.proc ?? {}
    const mods = this.baseStats.termMods
    let out = damage
    // 格挡：概率使本次伤害减半
    const blockChance = Math.max(0, mods.blockProcPct ?? 0)
    if (blockChance > 0 && Math.random() * 100 < blockChance) {
      out = Math.max(1, Math.floor(out * 0.5))
      this.pushLog('装备触发「格挡」，伤害减半', 'skill')
    }
    // 反震：概率反弹本次伤害的一部分
    const reflectChance = Math.max(0, mods.reflectProcPct ?? 0)
    if (proc.reflect && this.monster && reflectChance > 0 && Math.random() * 100 < reflectChance) {
      const back = Math.max(1, Math.floor(out * (proc.reflect.damagePct / 100)))
      this.monsterHp -= back
      this.pushLog(`装备触发「反震」，反弹 ${back} 点伤害`, 'skill')
      if (this.monsterHp <= 0) {
        this.killMonster()
        return out
      }
    }
    // 复仇：概率获得攻击增益
    const vengeanceChance = Math.max(0, mods.vengeanceProcPct ?? 0)
    if (proc.vengeance && vengeanceChance > 0 && Math.random() * 100 < vengeanceChance) {
      this.buffs.push({
        stat: 'attackBuff',
        value: proc.vengeance.attackBuffPct / 100,
        remaining: proc.vengeance.durationSec,
        name: '复仇',
      })
      this.pushLog('装备触发「复仇」，攻击力提升', 'skill')
    }
    // 庇护：概率获得护盾
    const aegisChance = Math.max(0, mods.aegisProcPct ?? 0)
    if (proc.aegis && aegisChance > 0 && Math.random() * 100 < aegisChance) {
      this.shield += Math.floor(stats.maxHp * proc.aegis.maxHpShieldPct * this.shieldMultiplier)
      this.pushLog('装备触发「庇护」，获得护盾', 'skill')
    }
    // 坚毅：概率恢复魔力
    const resolveChance = Math.max(0, mods.resolveProcPct ?? 0)
    if (proc.resolve && resolveChance > 0 && Math.random() * 100 < resolveChance) {
      this.heroMp = Math.min(stats.maxMp, this.heroMp + Math.floor(stats.maxMp * proc.resolve.maxMpRestorePct))
      this.pushLog('装备触发「坚毅」，恢复魔力', 'skill')
    }
    // 累计触发「受创蓄力」：累计受到一定比例最大生命的伤害后获得护盾。
    this.chargeTaken += damage
    const chargeShield = mods.chargeShieldPct ?? 0
    const shieldThreshold = EQUIP.charge?.chargeShield?.hpThresholdPct ?? 30
    if (chargeShield > 0 && stats.maxHp > 0 && this.chargeTaken >= stats.maxHp * (shieldThreshold / 100)) {
      this.chargeTaken = 0
      this.shield += Math.floor(stats.maxHp * (chargeShield / 100) * this.shieldMultiplier)
      this.pushLog('装备触发「受创蓄力」，获得护盾', 'skill')
    }
    return out
  }

  private tickMonster(dt: number): void {
    if (!this.monster) return
    this.monsterAttackTimer -= dt
    if (this.monsterAttackTimer > 0) return
    // 「缓速」延长目标出手间隔（攻速下降）
    this.monsterAttackTimer = this.monster.attackInterval / (1 - this.enemySpeedDown)
    this.monsterAttack()
  }

  private monsterAttack(): void {
    const stats = this.stats
    if (Math.random() * 100 < this.monsterMissChance) {
      this.pushFloat('闪避', 'hero', 'hero')
      return
    }
    if (this.consumeImmunity()) return
    let damage = rollIncoming(
      this.monster!.attack * this.bossAttackMultiplier() * (1 - this.enemyAttackDown),
      100,
      stats.physDef * this.defenseScale,
      stats.tenacityPct,
      stats.termMods.damageTakenPct ?? 0,
      this.penalty.damageTakenBonusPct,
    )
    damage = this.onHitTaken(stats, damage)
    if (!this.monster) return

    // 荆棘反弹
    const thorns = stats.termMods.thornsPct
    if (thorns) this.monsterHp -= Math.max(1, Math.floor(damage * (thorns / 100)))

    if (this.shield > 0) {
      const absorbed = Math.min(this.shield, damage)
      this.shield -= absorbed
      damage -= absorbed
    }
    if (damage <= 0) {
      this.pushFloat('护盾', 'hero', 'hero')
    } else {
      this.heroHp -= damage
      this.pushFloat(`-${damage}`, 'hero', 'monster')
      this.logIncomingDamage(this.monster!.name, damage)
    }

    // 吸血
    if (stats.lifestealPct > 0) {
      this.heroHp = Math.min(stats.maxHp, this.heroHp + Math.floor(damage * (stats.lifestealPct / 100) * this.healMultiplier))
    }

    if (this.monsterHp <= 0) {
      this.killMonster()
      return
    }
    if (this.heroHp <= 0) this.heroDies()
  }

  // ---------- 副本 BOSS 技能（仅副本生效，地区战斗不受影响） ----------

  /** 推进 BOSS 共享技能 CD 与自身增益；CD 归零后从技能池随机抽一个释放。 */
  private tickBossSkills(dt: number): void {
    if (!this.isRaid) return
    const enemy = this.current
    if (!enemy) return

    for (const buff of enemy.selfBuffs) buff.remaining -= dt
    enemy.selfBuffs = enemy.selfBuffs.filter((b) => b.remaining > 0)

    if (enemy.pendingSkill) {
      enemy.pendingSkill.remaining -= dt
      if (enemy.pendingSkill.remaining <= 0) {
        const pending = enemy.pendingSkill.skill
        enemy.pendingSkill = null
        this.castBossSkill(enemy, { ...pending, effect: 'nuke' })
      }
      return
    }
    const skills = enemy.stats.skills ?? []
    if (skills.length === 0) return

    enemy.skillTimer -= dt
    if (enemy.skillTimer > 0) return

    enemy.skillTimer = this.bossSkillInterval(enemy.stats)
    const skill = skills[Math.floor(Math.random() * skills.length)]
    if (skill) this.castBossSkill(enemy, skill)
  }

  private castBossSkill(enemy: EnemyState, skill: BossSkill): void {
    const effect = String(skill.effect ?? '')
    const duration = Math.max(0, Number(skill.duration ?? 0))
    switch (effect) {
      case 'charge': {
        const seconds = Number(skill.chargeSeconds ?? 2) * (this.penalty.windowMultiplier ?? 1)
        enemy.pendingSkill = { skill, remaining: seconds }
        this.pushLog(`「${enemy.stats.name}」蓄力 ${skill.name}：${seconds.toFixed(1)} 秒后命中`, 'danger')
        break
      }
      case 'shield': {
        const reduce = Number(skill.damageReduce ?? 0)
        if (reduce > 0) {
          const seconds = duration || 6
          enemy.selfBuffs.push({ stat: 'damageReduce', value: reduce, remaining: seconds })
          this.pushLog(
            `「${enemy.stats.name}」施放 ${skill.name}：受到伤害 −${Math.round(reduce * 100)}%（${seconds}s）`,
            'danger',
          )
        }
        break
      }
      case 'enrage': {
        const buff = Number(skill.attackBuff ?? 0)
        if (buff > 0 && duration > 0) {
          enemy.selfBuffs.push({ stat: 'attackBuff', value: buff, remaining: duration })
          this.pushLog(
            `「${enemy.stats.name}」施放 ${skill.name}：攻击力 +${Math.round(buff * 100)}%（${duration}s）`,
            'danger',
          )
        }
        break
      }
      case 'dot': {
        const potency = Number(skill.potency ?? 0)
        if (potency > 0) {
          const seconds = duration || 5
          this.heroDots.push({
            remaining: seconds,
            potencyPerSec: potency / seconds,
            tick: 1,
            source: skill.id,
          })
          this.pushLog(
            `「${enemy.stats.name}」施放 ${skill.name}：持续伤害 ${Math.round(potency)}%（${seconds}s）`,
            'danger',
          )
        }
        break
      }
      case 'nuke':
      case 'aoe':
      case 'debuff': {
        const potency = Number(skill.potency ?? 0)
        if (potency > 0) {
          this.pushLog(`「${enemy.stats.name}」施放 ${skill.name}`, 'danger')
          this.bossSkillDamage(enemy, skill, potency)
        }
        const speedDebuff = Number(skill.attackSpeedDebuff ?? 0)
        if (effect === 'debuff' && speedDebuff > 0 && this.phase !== 'dead') {
          const seconds = duration || 5
          this.buffs.push({ stat: 'attackSpeedBuff', value: -speedDebuff, remaining: seconds, name: skill.name })
          this.pushLog(
            `「${enemy.stats.name}」施放 ${skill.name}：攻击速度 −${Math.round(speedDebuff * 100)}%（${seconds}s）`,
            'danger',
          )
        }
        break
      }
      default:
        break
    }
  }

  /** BOSS 高威力技能：对英雄造成 `potency%` × BOSS 攻击的伤害。 */
  private bossSkillDamage(enemy: EnemyState, skill: BossSkill, potency: number): void {
    const stats = this.stats
    if (Math.random() * 100 < this.monsterMissChance) {
      this.pushFloat('闪避', 'hero', 'hero')
      return
    }
    if (this.consumeImmunity()) return
    const attackBuff = enemy.selfBuffs.reduce((sum, b) => (b.stat === 'attackBuff' ? sum + b.value : sum), 0)
    const attack = enemy.stats.attack * (1 + attackBuff) * (1 - this.enemyAttackDown)
    const defense = (skill.damageType === 'magical' ? stats.magicDef : stats.physDef) * this.defenseScale
    let damage = rollIncoming(
      attack,
      potency,
      defense,
      stats.tenacityPct,
      stats.termMods.damageTakenPct ?? 0,
      this.penalty.damageTakenBonusPct,
    )
    damage = this.onHitTaken(stats, damage)
    if (this.shield > 0) {
      const absorbed = Math.min(this.shield, damage)
      this.shield -= absorbed
      damage -= absorbed
    }
    if (damage > 0) {
      this.heroHp -= damage
      this.pushFloat(`-${damage}`, 'hero', 'monster')
      this.logIncomingDamage(enemy.stats.name, damage, skill.name)
    }
    if (stats.lifestealPct > 0) {
      this.heroHp = Math.min(stats.maxHp, this.heroHp + Math.floor(Math.max(0, damage) * (stats.lifestealPct / 100) * this.healMultiplier))
    }
    if (this.heroHp <= 0) { this.mechanismFailures.push(skill.id); this.heroDies() }
  }

  /** BOSS 持续伤害计时（作用于英雄）。 */
  private tickHeroDots(dt: number): void {
    if (this.heroDots.length === 0) return
    const enemy = this.current
    const base = enemy ? enemy.stats.attack * this.bossAttackMultiplier() : 0
    for (const dot of this.heroDots) {
      dot.remaining -= dt
      dot.tick -= dt
      if (dot.tick <= 0) {
        dot.tick = 1
        if (this.consumeImmunity()) continue
        let damage = Math.max(1, Math.floor(base * (dot.potencyPerSec / 100) * (1 + this.penalty.damageTakenBonusPct / 100)))
        const absorbed = Math.min(this.shield, damage)
        this.shield -= absorbed
        damage -= absorbed
        this.heroHp -= damage
        if (this.heroHp <= 0) this.mechanismFailures.push(dot.source)
        this.pushFloat(`-${damage}`, 'hero', 'monster')
        this.logIncomingDamage(enemy?.stats.name ?? '持续伤害', damage, '持续伤害')
      }
    }
    this.heroDots = this.heroDots.filter((d) => d.remaining > 0)
    if (this.heroHp <= 0) this.heroDies()
  }

  private killMonster(): void {
    const monster = this.monster
    if (!monster) return
    const isBoss = monster.kind === 'boss'
    this.pushLog(`击败「${monster.name}」！`, 'boss')
    // 动态成长「战意」：击杀叠加攻击层数。
    if (this.baseStats.termMods.killStackAttackPct) {
      const max = EQUIP.growth?.killStackAttackPct?.maxStacks ?? 10
      this.growthCounts.killStackAttackPct = Math.min(max, (this.growthCounts.killStackAttackPct ?? 0) + 1)
    }
    // 资源转换「汲魔」：击杀恢复魔力。
    const killMp = this.baseStats.termMods.killRestoreMpPct ?? 0
    if (killMp > 0) {
      this.heroMp = Math.min(this.stats.maxMp, this.heroMp + Math.floor(this.stats.maxMp * (killMp / 100)))
    }

    if (!this.isRaid) {
      // 地区战斗：小怪计入上报，BOSS 触发通关
      let gold = this.rollGold(monster.kind)
      let doubled = false
      if (!isBoss && this.doubleRewardCharges > 0) {
        this.doubleRewardCharges -= 1
        gold *= 2
        doubled = true
      }
      const exp = Math.max(
        1,
        Math.floor(gold * data.monsters.xpPerGold * monsterExpMultiplier(this.difficulty)),
      )
      if (isBoss) {
        this.pendingBossKill = true
      } else {
        // 装备不再由怪物掉落：只能通过抽箱获取
        this.pendingKills.push({ monsterId: monster.templateId, gold, exp })
        this.pushLog(`击败 ${monster.name}，获得 ${gold} 金币${doubled ? '（翻倍）' : ''}`, 'loot')
      }
    }

    this.removeCurrentEnemy()

    if (this.isRaid) {
      if (this.enemies.length === 0) {
        this.pendingBossKill = true
        this.phase = 'cleared'
      } else {
        this.enrageSurvivors()
      }
      return
    }

    if (isBoss) {
      this.phase = 'cleared'
      return
    }

    this.killCount += 1
    if (this.killCount >= this.killsRequired) {
      this.phase = 'boss'
      this.bossTimer = data.heroes.bossSpawnDelaySeconds
      this.pushLog('小怪阶段完成，BOSS 即将出现…', 'system')
    } else {
      this.spawnTimer = this.spawnInterval
    }
  }

  private heroDies(): void {
    // 「不死」：受致命伤害时概率免死并保留 1 点生命（每场战斗 1 次）。
    const cheat = this.baseStats.termMods.cheatDeathPct ?? 0
    if (cheat > 0 && !this.cheatDeathUsed && Math.random() * 100 < cheat) {
      this.cheatDeathUsed = true
      this.heroHp = 1
      this.pushLog('装备触发「不死」，免于死亡并保留 1 点生命', 'danger')
      return
    }
    this.phase = 'dead'
    // 「归魂」缩短 / 「沉魂」延长复活等待，最短 1 秒。
    const mods = this.baseStats.termMods
    const factor = 1 - ((mods.reviveHastePct ?? 0) - (mods.reviveDelayPct ?? 0)) / 100
    this.deathTimer = Math.max(1, Number(data.heroes.reviveDelaySeconds) * factor)
    this.reviveTotal = this.deathTimer
    this.deathCount += 1
    this.pendingDeath = true
    this.killCount = 0 // PRD 地区 3.2：阵亡后小怪击杀计数归零
    this.enemies = []
    this.dots = []
    this.enemyDebuffs = []
    this.heroDots = []
    this.resetCombatGrowth()
    // 「死亡抵抗」：概率当场复活（回复 30% 生命，不进入等待）。
    const reviveChance = mods.reviveChancePct ?? 0
    if (!this.isRaid && reviveChance > 0 && Math.random() * 100 < reviveChance) {
      this.pendingDeath = false
      this.pushLog('装备触发「死亡抵抗」，立即复活', 'danger')
      this.revive()
      this.heroHp = Math.max(1, Math.floor(this.stats.maxHp * (EQUIP.special?.revive?.reviveHpPct ?? 0.3)))
      return
    }
    this.pushLog(this.isRaid ? '英雄阵亡！副本挑战失败' : '英雄阵亡！小怪阶段进度重置', 'danger')
  }

  /** 复活 / 免死后重置战斗内成长与累计计数。 */
  private resetCombatGrowth(): void {
    this.growthCounts = { killStackAttackPct: 0, hitStackSpeedPct: 0, skillStackDamagePct: 0 }
    this.chargeDamage = 0
    this.chargeTaken = 0
    this.chargeCasts = 0
  }

  private revive(): void {
    const stats = this.stats
    this.heroHp = stats.maxHp
    this.heroMp = stats.maxMp
    this.shield = 0
    this.heroDots = []
    this.phase = 'mob'
    this.spawnTimer = this.spawnInterval
    this.basicAttackTimer = 0
    this.cheatDeathUsed = false
    this.resetCombatGrowth()
    this.pushLog('英雄已复活，生命值回满', 'system')
  }

  private rollGold(kind: 'normal' | 'elite' | 'boss'): number {
    if (!this.region) return 1 // 副本奖励由服务端结算，不本地掷金
    const multiplier = data.regions.goldMultipliers[kind] ?? 1
    const spread = data.regions.goldFloat
    const base = this.region.baseGold * multiplier
    const value = base * (1 + (Math.random() * 2 - 1) * spread)
    const bonus = Math.min(
      data.regions.maxGoldBonus * 100,
      Math.max(
        0,
        (this.baseStats.termMods.goldGainPct ?? 0) +
          (this.baseStats.termMods.goldAllPct ?? 0) +
          (kind === 'boss' ? this.baseStats.termMods.goldBossPct ?? 0 : 0),
      ),
    )
    return Math.max(1, Math.floor(value * (1 + bonus / 100) * monsterGoldMultiplier(this.difficulty)))
  }

  start(): void {
    if (this.phase !== 'idle') return
    if (this.isRaid) {
      // 副本无小怪阶段：开局即与全部 BOSS 交战
      this.phase = 'boss'
      this.bossFightMs = 0
      this.pushLog('副本战斗开始！', 'system')
      return
    }
    this.phase = 'mob'
    this.spawnTimer = 0.6
    this.pushLog('开始自动战斗', 'system')
  }

  pause(): void {
    if (this.phase !== 'cleared') this.phase = 'idle'
  }

  /** BOSS 已击败后留在当前地区：重置小怪阶段，继续原地挂机。仅地区战斗可用。 */
  continueAfterClear(): void {
    if (this.isRaid || this.phase !== 'cleared') return
    this.killCount = 0
    this.enemies = []
    this.dots = []
    this.enemyDebuffs = []
    this.phase = 'mob'
    this.spawnTimer = this.spawnInterval
    this.pushLog('留在当前地区，继续挂机', 'system')
  }

  /** 取出并清空待上报的事件。 */
  drainPending(): {
    kills: KillRecord[]
    skillCasts: Record<string, number>
    bossKilled: boolean
    died: boolean
    bossFightMs: number
  } {
    const payload = {
      kills: this.pendingKills,
      skillCasts: this.pendingSkillCasts,
      bossKilled: this.pendingBossKill,
      died: this.pendingDeath,
      bossFightMs: Math.round(this.bossFightMs),
    }
    this.pendingKills = []
    this.pendingSkillCasts = {}
    this.pendingBossKill = false
    this.pendingDeath = false
    this.bossFightMs = 0
    return payload
  }

  /** 英雄属性变化（升级 / 换装）后同步，避免模拟使用过期数值。 */
  updateStats(stats: HeroStats): void {
    const ratio = this.baseStats.maxHp > 0 ? this.heroHp / this.baseStats.maxHp : 1
    this.baseStats = scalePlayerStats(stats, this.difficulty)
    this.heroHp = Math.max(1, Math.min(stats.maxHp, stats.maxHp * ratio))
    this.heroMp = Math.min(stats.maxMp, this.heroMp)
  }

  /** 上报失败时把事件放回队列，避免丢失收益。 */
  restorePending(pending: {
    kills: KillRecord[]
    skillCasts: Record<string, number>
    bossKilled: boolean
    died: boolean
    bossFightMs: number
  }): void {
    this.pendingKills = [...pending.kills, ...this.pendingKills]
    for (const [skillId, count] of Object.entries(pending.skillCasts)) {
      this.pendingSkillCasts[skillId] = (this.pendingSkillCasts[skillId] ?? 0) + count
    }
    this.pendingBossKill = this.pendingBossKill || pending.bossKilled
    this.pendingDeath = this.pendingDeath || pending.died
    this.bossFightMs = Math.max(this.bossFightMs, pending.bossFightMs)
  }

  /** 服务端纠正后的击杀计数。 */
  syncKillCount(count: number): void {
    if (count < this.killCount) this.killCount = count
  }

  applyServerKillCount(count: number, killsRequired: number): void {
    this.killCount = count
    this.killsRequired = killsRequired
    if (count >= killsRequired && this.phase === 'mob' && !this.monster) {
      this.phase = 'boss'
      this.bossTimer = data.heroes.bossSpawnDelaySeconds
    }
  }

  pushFloating(text: string, side: 'hero' | 'monster', tone: FloatTone): void {
    this.pushFloat(text, side, tone)
  }

  private pushFloat(text: string, side: 'hero' | 'monster', tone: FloatTone): void {
    this.floating.push({ id: nextId(), text, tone, side, remaining: FLOAT_LIFE })
    if (this.floating.length > MAX_FLOAT) this.floating.splice(0, this.floating.length - MAX_FLOAT)
  }

  /** 伤害浮动数字按存活时间衰减，过期的移除（供 UI 播放淡出）。 */
  private tickFloating(dt: number): void {
    if (this.floating.length === 0) return
    for (const f of this.floating) f.remaining -= dt
    this.floating = this.floating.filter((f) => f.remaining > 0)
  }

  /** 日志：怪物对英雄造成的伤害。 */
  private logIncomingDamage(source: string, damage: number, skill?: string): void {
    this.pushLog(
      skill ? `「${source}」的 ${skill} 造成 ${damage} 点伤害` : `「${source}」造成 ${damage} 点伤害`,
      'danger',
    )
  }

  recordReward(text: string): void {
    this.pushLog(text, 'loot')
  }

  private pushLog(text: string, tone: LogEntry['tone']): void {
    this.log.push({ id: nextId(), text, tone })
    if (this.log.length > MAX_LOG) this.log.splice(0, this.log.length - MAX_LOG)
  }

  get isMagicalJob(): boolean {
    return isMagical(this.baseStats)
  }
}
