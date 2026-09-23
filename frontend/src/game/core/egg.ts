/** 彩蛋英雄：读取共享配置，向战斗引擎暴露技能集与被动。 */
import data from '@shared/schema'

import type { EggHeroDef } from '@shared/schema'
import type { SkillLike } from './combat'

export type { EggHeroDef }

export function eggDef(eggId: string | null | undefined): EggHeroDef | null {
  if (!eggId) return null
  return data.eggHeroes.byId[eggId] ?? null
}

/**
 * 彩蛋英雄在指定职业下生效的技能集。
 * jobId 为 null 表示任意职业；不匹配或未配置技能时返回 null。
 */
export function eggSkillSet(
  eggId: string | null | undefined,
  jobId: string,
): { skills: SkillLike[]; replace: boolean } | null {
  const egg = eggDef(eggId)
  if (!egg) return null
  if (egg.jobId && egg.jobId !== jobId) return null
  if (egg.skills.length === 0) return null
  return { skills: egg.skills as unknown as SkillLike[], replace: egg.replaceSkills }
}

/** 彩蛋英雄的抽奖幸运加成（装备品阶 luck 系数）。 */
export function eggLuckBonus(eggId: string | null | undefined): number {
  const egg = eggDef(eggId)
  if (!egg?.passive) return 0
  if (egg.passive.type !== 'chestLuckBonus') return 0
  return egg.passive.value
}

/** 彩蛋被动「战斗爽」：对战普通怪物时，威力恰为 100% 的技能威力加成（1 = 翻倍）。 */
export function eggNormalMobPotency100Bonus(eggId: string | null | undefined): number {
  const egg = eggDef(eggId)
  if (!egg?.passive) return 0
  if (egg.passive.type !== 'normalMobPotency100Bonus') return 0
  return Math.max(0, egg.passive.value)
}
