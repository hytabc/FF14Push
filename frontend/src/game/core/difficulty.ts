/**
 * 战斗难度等级。必须与后端 `services/difficulty.py` 保持一致。
 *
 * 怪物数值按「加法」叠加：难度 N 的乘数 = 1 + 单级加成 × N。
 * 玩家攻击/防御按「乘法」叠加：0.85^N / 0.9^N。难度 0 时全部为 1（等于当前各地区数值）。
 */
import data from '@shared/schema'

import type { HeroStats } from '../types'

const DIFF = (data.combat as Record<string, any>).difficulty as {
  maxLevel: number
  playerAttackMultiplierPerLevel: number
  playerDefenseMultiplierPerLevel: number
  monsterHpBonusPerLevel: number
  monsterAttackBonusPerLevel: number
  monsterDefenseBonusPerLevel: number
  monsterGoldBonusPerLevel: number
  monsterExpBonusPerLevel: number
}

export const maxDifficultyLevel = DIFF.maxLevel

export function clampDifficulty(level: number): number {
  if (!Number.isFinite(level)) return 0
  return Math.max(0, Math.min(maxDifficultyLevel, Math.floor(level)))
}

export function playerAttackMultiplier(level: number): number {
  return DIFF.playerAttackMultiplierPerLevel ** Math.max(0, Math.floor(level))
}

export function playerDefenseMultiplier(level: number): number {
  return DIFF.playerDefenseMultiplierPerLevel ** Math.max(0, Math.floor(level))
}

export function monsterHpMultiplier(level: number): number {
  return 1 + DIFF.monsterHpBonusPerLevel * Math.max(0, Math.floor(level))
}

export function monsterAttackMultiplier(level: number): number {
  return 1 + DIFF.monsterAttackBonusPerLevel * Math.max(0, Math.floor(level))
}

export function monsterDefenseMultiplier(level: number): number {
  return 1 + DIFF.monsterDefenseBonusPerLevel * Math.max(0, Math.floor(level))
}

export function monsterGoldMultiplier(level: number): number {
  return 1 + DIFF.monsterGoldBonusPerLevel * Math.max(0, Math.floor(level))
}

export function monsterExpMultiplier(level: number): number {
  return 1 + DIFF.monsterExpBonusPerLevel * Math.max(0, Math.floor(level))
}

export function monsterMultipliers(level: number): { hp: number; attack: number; defense: number } {
  return {
    hp: monsterHpMultiplier(level),
    attack: monsterAttackMultiplier(level),
    defense: monsterDefenseMultiplier(level),
  }
}

/** 按难度缩放玩家攻击/防御（物理 + 魔法），不改动生命 / 其它属性。 */
export function scalePlayerStats(stats: HeroStats, level: number): HeroStats {
  const lv = Math.max(0, Math.floor(level))
  if (lv === 0) return stats
  const atk = playerAttackMultiplier(lv)
  const def = playerDefenseMultiplier(lv)
  return {
    ...stats,
    attack: stats.attack * atk,
    magicAttack: stats.magicAttack * atk,
    physDef: stats.physDef * def,
    magicDef: stats.magicDef * def,
  }
}
