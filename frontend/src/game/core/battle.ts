/**
 * 客户端战斗模拟。
 *
 * 只负责表现与「发生了哪些事件」；金币与经验一律以服务端结算为准
 * （装备只能通过抽箱获取，怪物不掉落装备）。
 */
import data from '@shared/schema'

import type { HeroStats, MonsterStats, RegionDef } from '../types'
import {
  ADVENTURER_SKILL,
  isMagical,
  jobSkills,
  powerAttack,
  rollDamage,
  rollIncoming,
  skillCooldown,
  skillDamageMultiplier,
  type SkillLike,
} from './combat'
import { bossStats, eliteChance, getRegion, monsterStats, regionTemplates } from './regions'

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

export interface FloatingText {
  id: number
  text: string
  tone: 'hero' | 'monster' | 'crit'
  side: 'hero' | 'monster'
}

type Phase = 'idle' | 'mob' | 'boss' | 'dead' | 'cleared'

interface ActiveBuff {
  stat: string
  value: number
  remaining: number
  name: string
}

const MAX_LOG = 160
const MAX_FLOAT = 12

let uid = 0
const nextId = () => ++uid

export class BattleSimulator {
  readonly region: RegionDef
  killsRequired: number
  spawnInterval: number
  boss: MonsterStats

  phase: Phase = 'idle'
  killCount = 0
  monster: MonsterStats | null = null
  monsterHp = 0
  monsterMaxHp = 0
  heroHp = 0
  heroMp = 0
  shield = 0

  log: LogEntry[] = []
  floating: FloatingText[] = []
  cooldowns: Record<string, number> = {}
  gcd = 0
  spawnTimer = 0
  bossTimer = 0
  deathTimer = 0
  monsterAttackTimer = 0
  bossFightMs = 0
  deathCount = 0

  pendingKills: KillRecord[] = []
  pendingSkillCasts: Record<string, number> = {}
  pendingBossKill = false
  pendingDeath = false

  private baseStats: HeroStats
  private buffs: ActiveBuff[] = []
  private dots: Array<{ remaining: number; potency: number; tick: number }> = []
  private regenTimer = 0

  constructor(options: {
    stats: HeroStats
    regionId: number
    killsRequired: number
    spawnInterval: number
    killCount?: number
  }) {
    this.baseStats = options.stats
    this.region = getRegion(options.regionId)
    this.killsRequired = options.killsRequired
    this.spawnInterval = options.spawnInterval
    this.boss = bossStats(this.region)
    this.killCount = options.killCount ?? 0
    this.heroHp = options.stats.maxHp
    this.heroMp = options.stats.maxMp
    this.spawnTimer = 0.6
    this.pushLog(`进入「${this.region.name}」· Lv.${this.region.levelMin}-${this.region.levelMax}`, 'system')
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
    return this.baseStats.jobId === 'adventurer' ? [ADVENTURER_SKILL] : jobSkills(this.baseStats.jobId)
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
      this.heroHp = Math.min(stats.maxHp, this.heroHp + stats.hpRegen * ticks)
      this.heroMp = Math.min(stats.maxMp, this.heroMp + stats.mpRegen * ticks)
    }

    if (this.phase === 'dead') {
      this.deathTimer -= dt
      if (this.deathTimer <= 0) this.revive()
      return
    }

    this.tickDots(dt)

    if (!this.monster) {
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
    this.setMonster(monsterStats(this.region, templateId))
    this.pushLog(`遭遇 ${this.monster!.name}`, 'normal')
  }

  private spawnBoss(): void {
    this.setMonster({ ...this.boss })
    this.bossFightMs = 0
    this.pushLog(`关底 BOSS「${this.boss.name}」出现！`, 'boss')
  }

  private setMonster(monster: MonsterStats): void {
    this.monster = monster
    this.monsterMaxHp = monster.hp
    this.monsterHp = monster.hp
    this.monsterAttackTimer = monster.attackInterval
    this.dots = []
  }

  private castIfReady(): void {
    if (this.gcd > 0) return
    const ready = this.skills.filter((skill) => (this.cooldowns[skill.id] ?? 0) <= 0)
    if (ready.length === 0) return

    const castable = ready.filter((skill) => this.mpCost(skill) <= this.heroMp)
    const pool = castable.length > 0 ? castable : ready.filter((s) => s.potency > 0)
    const skill = this.pickSkill(pool)
    this.cast(skill)
  }

  private pickSkill(pool: SkillLike[]): SkillLike {
    const sorted = [...pool].sort((a, b) => {
      if (a.priority !== b.priority) return a.priority - b.priority
      return b.potency - a.potency
    })
    // 普攻兜底：其他技能都在 CD 时使用
    return sorted[0] ?? ADVENTURER_SKILL
  }

  private mpCost(skill: SkillLike): number {
    const scale = skill.damageType === 'magical' ? data.heroes.mp.magicalSkillCostScale : data.heroes.mp.physicalSkillCostScale
    return Math.floor(skill.mpCost * scale)
  }

  private cast(skill: SkillLike): void {
    const stats = this.stats
    const cost = this.mpCost(skill)
    this.heroMp = Math.max(0, this.heroMp - cost)
    this.cooldowns[skill.id] = skillCooldown(stats, skill.cd)
    this.gcd = data.combat.gcdSeconds as number
    this.pendingSkillCasts[skill.id] = (this.pendingSkillCasts[skill.id] ?? 0) + 1

    if (skill.potency > 0 && this.monster) {
      const mult = skillDamageMultiplier(stats, stats.jobId)
      const roll = rollDamage(stats, skill.potency, skill.damageType, this.monster.defense, mult)
      this.monsterHp -= roll.amount
      this.pushFloat(
        `${roll.amount}${roll.isCrit ? '!' : ''}`,
        'monster',
        roll.isCrit || roll.isDirectHit ? 'crit' : 'monster',
      )
      if (roll.isCrit) this.pushLog(`${skill.name} 暴击 ${roll.amount} 伤害`, 'damage')
      else this.pushLog(`${skill.name} 造成 ${roll.amount} 伤害`, skill.priority === 1 ? 'skill' : 'damage')
    } else {
      this.pushLog(`施放 ${skill.name}`, 'skill')
    }

    this.applyEffects(skill)

    if (this.monster && this.monsterHp <= 0) this.killMonster()
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
          const amount = type === 'fullHeal' ? stats.maxHp : Math.floor(stats.maxHp * value)
          this.heroHp = Math.min(stats.maxHp, this.heroHp + amount)
          this.pushFloat(`+${Math.floor(amount)}`, 'hero', 'hero')
          break
        }
        case 'healOverTime':
          this.buffs.push({ stat: 'healOverTime', value, remaining: duration, name: skill.name })
          break
        case 'shield':
          this.shield += Math.floor(stats.maxHp * value)
          break
        case 'mpRestore':
          this.heroMp = Math.min(stats.maxMp, this.heroMp + Math.floor(stats.maxMp * value))
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
          const roll = rollDamage(stats, potency, skill.damageType, this.monster.defense)
          this.monsterHp -= roll.amount
          this.pushFloat(`${roll.amount}${roll.isCrit ? '!' : ''}`, 'monster', 'crit')
          this.heroMp = 0
          break
        }
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
    let damage = rollIncoming(
      this.monster!.attack,
      100,
      stats.physDef,
      stats.tenacityPct,
      stats.termMods.damageTakenPct ?? 0,
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
      this.heroHp = Math.min(stats.maxHp, this.heroHp + Math.floor(damage * (stats.lifestealPct / 100)))
    }

    if (this.monsterHp <= 0) {
      this.killMonster()
      return
    }
    if (this.heroHp <= 0) this.heroDies()
  }

  private killMonster(): void {
    const monster = this.monster
    if (!monster) return
    const isBoss = monster.kind === 'boss'
    const gold = this.rollGold(monster.kind)
    const exp = Math.max(1, Math.floor(gold * data.monsters.xpPerGold))

    if (isBoss) {
      this.pendingBossKill = true
      this.pushLog(`击败「${monster.name}」！`, 'boss')
    } else {
      // 装备不再由怪物掉落：只能通过抽箱获取
      this.pendingKills.push({ monsterId: monster.templateId, gold, exp })
      this.pushLog(`击败 ${monster.name}，获得 ${gold} 金币`, 'loot')
    }

    this.monster = null
    this.monsterHp = 0
    this.monsterMaxHp = 0
    this.dots = []

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
    this.monster = null
    this.pushLog('英雄阵亡！小怪阶段进度重置', 'danger')
  }

  private revive(): void {
    const stats = this.stats
    this.heroHp = stats.maxHp
    this.heroMp = stats.maxMp
    this.shield = 0
    this.phase = 'mob'
    this.spawnTimer = this.spawnInterval
    this.pushLog('英雄已复活，生命值回满', 'system')
  }

  private rollGold(kind: 'normal' | 'elite' | 'boss'): number {
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
    this.phase = 'mob'
    this.spawnTimer = 0.6
    this.pushLog('开始自动战斗', 'system')
  }

  pause(): void {
    if (this.phase !== 'cleared') this.phase = 'idle'
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

  pushFloating(text: string, side: 'hero' | 'monster', tone: 'hero' | 'monster' | 'crit'): void {
    this.pushFloat(text, side, tone)
  }

  private pushFloat(text: string, side: 'hero' | 'monster', tone: 'hero' | 'monster' | 'crit'): void {
    this.floating.push({ id: nextId(), text, tone, side })
    if (this.floating.length > MAX_FLOAT) this.floating.splice(0, this.floating.length - MAX_FLOAT)
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
