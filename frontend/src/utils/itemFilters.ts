import data from '@shared/schema'

import type { JobRole, TermQuality } from '@/game/types'

/** 装备分组：战斗 / 生产 / 采集（生产采集专用装备底材见 dohdol-equipment）。 */
export type EquipGroup = 'combat' | 'doh' | 'dol'

const DEDICATED_GROUP: Record<string, EquipGroup> = {
  doh_tool: 'doh',
  doh_gear: 'doh',
  dol_tool: 'dol',
  dol_gear: 'dol',
}

export const EQUIP_GROUP_LABEL: Record<EquipGroup, string> = { combat: '战斗', doh: '生产', dol: '采集' }

/** 装备大类 → 图鉴分组；战斗大类（weapon/armor/accessory）归 combat。 */
export function equipGroup(category: string): EquipGroup {
  return DEDICATED_GROUP[category] ?? 'combat'
}

/** 防具/饰品的职能词缀（variantId）→ 战斗职能的近似归属；基础/精准/制敌型视为通用（null）。 */
const VARIANT_ROLE: Record<string, JobRole> = {
  str: 'melee',
  dex: 'physicalRanged',
  int: 'magicalRanged',
  tank: 'tank',
  vit: 'tank',
  bal: 'healer',
}

/** 底材 → 战斗职能：武器按 jobId 精确取，防具/饰品按职能词缀近似，无法判断返回 null。 */
export function roleOfBaseId(baseId: string | null | undefined): JobRole | null {
  const base = baseId ? data.baseItemById[baseId] : undefined
  if (!base) return null
  if (base.jobId) return data.jobById[base.jobId]?.role ?? null
  return VARIANT_ROLE[base.variantId ?? ''] ?? null
}

/** 战斗职能 id → 中文（坦克/治疗/近战DPS…）。 */
export const ROLE_LABELS: Record<string, string> = Object.fromEntries(
  Object.values(data.jobs.roles).map((r) => [r.id, r.name]),
)

/** 武器种类 id → 中文（长剑/长枪/法杖…）。 */
export const WEAPON_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  data.weaponFamilies.map((w) => [w.weaponType, w.suffix]),
)

export const TERM_QUALITY_LABELS: Record<TermQuality, string> = { common: '普通', rare: '稀有', ancient: '太古' }

interface TermLike {
  id: string
  name: string
  type: string
  slots?: readonly string[]
}

/** 词条 id → 定义（战斗 + 生产/采集，两池 id 互不重复）。 */
export const TERM_BY_ID: Record<string, TermLike> = Object.fromEntries(
  [...data.terms.terms, ...data.dohdolEquipment.terms].map((t) => [t.id, t as TermLike]),
)

/** 某部位在指定分组下「可能 roll 出」的词条 id 列表（无 slots 限制的词条对所有部位生效）。 */
export function possibleTermIds(slot: string, group: EquipGroup): string[] {
  const pool: readonly TermLike[] = group === 'combat' ? data.terms.terms : data.dohdolEquipment.terms
  return pool.filter((t) => !t.slots || t.slots.includes(slot)).map((t) => t.id)
}
