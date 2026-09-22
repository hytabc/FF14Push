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
import { eggSkillSet } from './egg'
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
  tone: 'normal' | 'skill' | 'damage' | 'loot' | 'danger' | 'system' | 'boss'
}

type FloatTone = 'hero' | 'monster' | 'crit' | 'miss'

export interface FloatingText {
  id: number
  text: string
  tone: FloatTone
  side: 'hero' | 'monster'
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
  spawnTimer = 0
  bossTimer = 0
  deathTimer = 0
  bossFightMs = 0
  deathCount = 0

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
  private buffs: ActiveBuff[] = []
  private dots: Array<{ remaining: number; potency: number; tick: number }> = []
  /** BOSS 施加给英雄的持续伤害（高难副本）。 */
  private heroDots: Array<{ remaining: number; potencyPerSec: number; tick: number; source: string }> = []
  private regenTimer = 0
  /** 越级时的等级压制惩罚（英雄等级 ≥ 地区下限则为全 0）。 */
  readonly penalty: LevelPenalty

  constructor(options: {
    stats: HeroStats
    penalty?: LevelPenalty
    regionId?: number
    killsRequired?: number
    spawnInterval?: number
    killCount?: number
    raid?: { bosses: MonsterStats[]; enrage: RaidEnrage | null }
    /** 彩蛋英雄 id：命中对应职业时追加/替换技能。 */
    eggId?: string | null
  }) {
    this.baseStats = options.stats
    this.eggId = options.eggId ?? null
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
    this.boss = bossStats(this.region)
    this.penalty = options.penalty ?? NO_LEVEL_PENALTY
    this.pushLog(`进入「${this.region.name}」· Lv.${this.region.levelMin}-${this.region.levelMax}`, 'system')
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
    this.pushLog(`切换目标 →「${this.enemies[index].stats.name}」`, 'system')
  }

  get stats(): HeroStats {
    if (this.buffs.length === 0) return this.baseStats
    const clone: HeroStats = { ...this.baseStats, termMods: { ...this.baseStats.termMods } }
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
      const total = Math.max(0.01, skillCooldown(stats, skill.cd) * cooldownMultiplier)
      const remaining = Math.max(0, this.cooldowns[skill.id] ?? 0)
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
    if (this.phase === 'idle' || this.phase === 'cleared') return

    this.gcd = Math.max(0, this.gcd - dt)
    for (const key of Object.keys(this.cooldowns)) {
      this.cooldowns[key] = Math.max(0, this.cooldowns[key] - dt)
    }
    this.buffs = this.buffs.filter((b) => (b.remaining -= dt) > 0)

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
      this.heroMp = Math.min(stats.maxMp, this.heroMp + stats.mpRegen * ticks * (this.penalty.resourceMultiplier ?? 1))
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

    this.castIfReady()
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
    this.setMonster(monsterStats(this.region!, templateId))
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
    this.heroDots = []
  }

  /** 目标阵亡：移出战斗。副本模式下若仍有存活 BOSS，则对其施加狂暴。 */
  private removeCurrentEnemy(): void {
    this.enemies.splice(this.targetIndex, 1)
    this.dots = []
    this.heroDots = []
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
    if (this.gcd > 0) return
    const ready = this.skills.filter((skill) => (this.cooldowns[skill.id] ?? 0) <= 0)
    if (ready.length === 0) return

    // 蓝量不足的技能无法施放：若没有任何负担得起的技能，回退到零耗蓝普攻
    const castable = ready.filter((skill) => this.mpCost(skill) <= this.heroMp)
    if (castable.length === 0) {
      if ((this.cooldowns[ADVENTURER_SKILL.id] ?? 0) <= 0) this.cast(ADVENTURER_SKILL)
      return
    }
    this.cast(this.pickSkill(castable))
  }

  private pickSkill(pool: SkillLike[]): SkillLike {
    const sorted = [...pool].sort((a, b) => {
      if (a.priority !== b.priority) return a.priority - b.priority
      return b.potency - a.potency
    })
    // 普攻兜底：其他技能都在 CD 时使用
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

  private cast(skill: SkillLike): void {
    const stats = this.stats
    const rawCost = this.rawMpCost(skill)
    const cost = this.mpCost(skill)
    this.heroMp = Math.max(0, this.heroMp - cost)
    if (rawCost > 0 && this.halfMpCharges > 0) {
      this.halfMpCharges -= 1
      this.pushLog(`「水群」生效，${skill.name} 魔力消耗减半（剩余 ${this.halfMpCharges} 次）`, 'skill')
    }
    // 零耗蓝普攻作为兜底回蓝手段：蓝量见底时仍能缓慢回蓝，避免退化成「只剩普攻」。
    if (rawCost <= 0) {
      const restore = Math.floor(stats.maxMp * Number(data.heroes.mp.basicAttackRestorePct ?? 0))
      if (restore > 0) this.heroMp = Math.min(stats.maxMp, this.heroMp + restore)
    }
    // 攻速：缩短 GCD，并让普攻（基础攻击）出手更快
    const speed = attackSpeedFactor(stats)
    const cdMult = (this.penalty.cooldownMultiplier ?? 1) / (skill.id === ADVENTURER_SKILL.id ? speed : 1)
    this.cooldowns[skill.id] = skillCooldown(stats, skill.cd) * cdMult
    this.gcd = (data.combat.gcdSeconds as number) / speed
    this.pendingSkillCasts[skill.id] = (this.pendingSkillCasts[skill.id] ?? 0) + 1

    if (skill.potency > 0 && this.monster) {
      let mult = skillDamageMultiplier(stats, stats.jobId)
      if (this.doublePowerCharges > 0) {
        mult *= 2
        this.doublePowerCharges -= 1
        this.pushLog(`${skill.name} 触发「割草」，威力翻倍`, 'skill')
      }
      const roll = rollDamage(
        stats,
        skill.potency,
        skill.damageType,
        this.monster.defense,
        mult,
        this.penalty,
        this.targetResistance(),
      )
      if (roll.missed) {
        this.pushFloat('未命中', 'monster', 'miss')
        this.pushLog(`${skill.name} 未命中`, 'damage')
      } else {
        this.monsterHp -= roll.amount
        this.pushFloat(
          `${roll.amount}${roll.isCrit ? '!' : ''}`,
          'monster',
          roll.isCrit || roll.isDirectHit ? 'crit' : 'monster',
        )
        if (roll.isCrit) this.pushLog(`${skill.name} 暴击 ${roll.amount} 伤害`, 'damage')
        else this.pushLog(`${skill.name} 造成 ${roll.amount} 伤害`, skill.priority === 1 ? 'skill' : 'damage')
        this.rollProcs(stats)
      }
    } else {
      this.pushLog(`施放 ${skill.name}`, 'skill')
    }

    this.applyEffects(skill)

    if (this.monster && this.monsterHp <= 0) this.killMonster()
  }

  /** 命中触发效果（proc）：灼烧 DOT / 疾风限时攻速。与后端 `combat_model.proc_dps_bonus` 同源。 */
  private rollProcs(stats: HeroStats): void {
    if (!this.monster) return
    const proc = (data.combat.proc ?? {}) as {
      burn?: { potencyPct: number; durationSec: number }
      haste?: { attackSpeedPct: number; durationSec: number }
    }
    const burnChance = Math.max(0, stats.termMods.burnProcPct ?? 0)
    if (proc.burn && burnChance > 0 && Math.random() * 100 < burnChance) {
      this.dots.push({ remaining: proc.burn.durationSec, potency: proc.burn.potencyPct, tick: 1 })
      this.pushLog('装备触发「灼烧」', 'skill')
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
            this.monsterHp -= roll.amount
            this.pushFloat(`${roll.amount}${roll.isCrit ? '!' : ''}`, 'monster', 'crit')
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

  /** 越级时英雄防御的剩余比例（0-1）。等级达标时为 1。 */
  private get defenseScale(): number {
    return Math.max(0, 1 - this.penalty.defenseIgnorePct / 100)
  }

  /** 治疗量倍率：等级压制系数 × 彩蛋「术道恒久」等治疗增益。 */
  private get healMultiplier(): number {
    const buff = this.buffs.reduce((sum, b) => (b.stat === 'healingBuff' ? sum + b.value : sum), 0)
    return (this.penalty.healingMultiplier ?? 1) * (1 + buff)
  }

  /** 消耗一层彩蛋「免疫」：返回 true 表示本次伤害被免疫。 */
  private consumeImmunity(): boolean {
    if (this.immunityCharges <= 0) return false
    this.immunityCharges -= 1
    this.pushFloat('免疫', 'hero', 'hero')
    this.pushLog(`免疫了本次伤害（剩余 ${this.immunityCharges} 次）`, 'skill')
    return true
  }

  private tickMonster(dt: number): void {
    if (!this.monster) return
    this.monsterAttackTimer -= dt
    if (this.monsterAttackTimer > 0) return
    this.monsterAttackTimer = this.monster.attackInterval
    this.monsterAttack()
  }

  private monsterAttack(): void {
    const stats = this.stats
    if (Math.random() * 100 < Math.min(60, stats.dodgePct)) {
      this.pushFloat('闪避', 'hero', 'hero')
      return
    }
    if (this.consumeImmunity()) return
    let damage = rollIncoming(
      this.monster!.attack * this.bossAttackMultiplier(),
      100,
      stats.physDef * this.defenseScale,
      stats.tenacityPct,
      stats.termMods.damageTakenPct ?? 0,
      this.penalty.damageTakenBonusPct,
    )

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
    if (Math.random() * 100 < Math.min(60, stats.dodgePct)) {
      this.pushFloat('闪避', 'hero', 'hero')
      return
    }
    if (this.consumeImmunity()) return
    const attackBuff = enemy.selfBuffs.reduce((sum, b) => (b.stat === 'attackBuff' ? sum + b.value : sum), 0)
    const attack = enemy.stats.attack * (1 + attackBuff)
    const defense = (skill.damageType === 'magical' ? stats.magicDef : stats.physDef) * this.defenseScale
    let damage = rollIncoming(
      attack,
      potency,
      defense,
      stats.tenacityPct,
      stats.termMods.damageTakenPct ?? 0,
      this.penalty.damageTakenBonusPct,
    )
    if (this.shield > 0) {
      const absorbed = Math.min(this.shield, damage)
      this.shield -= absorbed
      damage -= absorbed
    }
    if (damage > 0) {
      this.heroHp -= damage
      this.pushFloat(`-${damage}`, 'hero', 'monster')
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

    if (!this.isRaid) {
      // 地区战斗：小怪计入上报，BOSS 触发通关
      let gold = this.rollGold(monster.kind)
      let doubled = false
      if (!isBoss && this.doubleRewardCharges > 0) {
        this.doubleRewardCharges -= 1
        gold *= 2
        doubled = true
      }
      const exp = Math.max(1, Math.floor(gold * data.monsters.xpPerGold))
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
    this.phase = 'dead'
    this.deathTimer = data.heroes.reviveDelaySeconds
    this.deathCount += 1
    this.pendingDeath = true
    this.killCount = 0 // PRD 地区 3.2：阵亡后小怪击杀计数归零
    this.enemies = []
    this.dots = []
    this.heroDots = []
    this.pushLog(this.isRaid ? '英雄阵亡！副本挑战失败' : '英雄阵亡！小怪阶段进度重置', 'danger')
  }

  private revive(): void {
    const stats = this.stats
    this.heroHp = stats.maxHp
    this.heroMp = stats.maxMp
    this.shield = 0
    this.heroDots = []
    this.phase = 'mob'
    this.spawnTimer = this.spawnInterval
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
    return Math.max(1, Math.floor(value * (1 + bonus / 100)))
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
    this.baseStats = stats
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
    this.floating.push({ id: nextId(), text, tone, side })
    if (this.floating.length > MAX_FLOAT) this.floating.splice(0, this.floating.length - MAX_FLOAT)
  }

  recordReward(text: string): void {
    this.pushLog(text, 'loot')
  }

  private pushLog(text: string, tone: LogEntry['tone']): void {
    this.log.push({ id: nextId(), text, tone })
    if (this.log.length > MAX_LOG) this.log.splice(0, this.log.length - MAX_LOG)
  }

  clearFloating(): void {
    this.floating = []
  }

  get isMagicalJob(): boolean {
    return isMagical(this.baseStats)
  }
}
