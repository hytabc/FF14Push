import data from '@shared/schema'

import type { Item, JobRole, RarityId, TermQuality } from '@/game/types'
import { RARITY_ORDER, attrName, categoryName, slotName } from '@/utils/format'

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

/** 生产/采集加成 id → 中文名（gatherYieldPct → 采集产量…）。 */
export const DOHDOL_BONUS_NAMES: Record<string, string> = data.dohdolEquipment.bonusNames

export function dohdolBonusName(attr: string): string {
  return DOHDOL_BONUS_NAMES[attr] ?? attr
}

export type SortKey = 'power' | 'rarity' | 'level' | 'name'

export const SORT_OPTIONS: { id: SortKey; label: string }[] = [
  { id: 'power', label: '按战力排序' },
  { id: 'rarity', label: '按品阶排序' },
  { id: 'level', label: '按等级需求排序' },
  { id: 'name', label: '按名称排序' },
]

/** 装备筛选状态；多选集合一律「命中任一（OR）」。装备页选择弹窗与背包共用。 */
export interface ItemFilterState {
  rarity: 'all' | RarityId
  category: string
  slot: string
  weaponType: string
  role: 'all' | JobRole
  levelMin: number | ''
  levelMax: number | ''
  subAttrs: Set<string>
  terms: Set<string>
  quality: Set<TermQuality>
  bonus: Set<string>
}

export function createItemFilters(): ItemFilterState {
  return {
    rarity: 'all',
    category: 'all',
    slot: 'all',
    weaponType: 'all',
    role: 'all',
    levelMin: '',
    levelMax: '',
    subAttrs: new Set(),
    terms: new Set(),
    quality: new Set(),
    bonus: new Set(),
  }
}

export function hasActiveFilters(f: ItemFilterState): boolean {
  return (
    f.rarity !== 'all' ||
    f.category !== 'all' ||
    f.slot !== 'all' ||
    f.weaponType !== 'all' ||
    f.role !== 'all' ||
    f.levelMin !== '' ||
    f.levelMax !== '' ||
    f.subAttrs.size > 0 ||
    f.terms.size > 0 ||
    f.quality.size > 0 ||
    f.bonus.size > 0
  )
}

export function resetFilters(f: ItemFilterState): void {
  Object.assign(f, createItemFilters())
}

export interface FilterOptionSets {
  slots: { id: string; label: string }[]
  categories: { id: string; label: string }[]
  weaponTypes: { id: string; label: string }[]
  subAttrs: { id: string; label: string }[]
  terms: { id: string; label: string }[]
  bonuses: { id: string; label: string }[]
}

/** 从候选池派生各筛选的可选项（只列出实际存在的值）。 */
export function filterOptionSets(items: Item[]): FilterOptionSets {
  const slots = new Set<string>()
  const categories = new Set<string>()
  const weaponTypes = new Set<string>()
  const subAttrs = new Set<string>()
  const terms = new Set<string>()
  const bonuses = new Set<string>()
  for (const item of items) {
    slots.add(item.equipSlots?.[0] ?? item.slot)
    categories.add(item.category)
    if (item.weaponType) weaponTypes.add(item.weaponType)
    for (const a of item.subAttrs ?? []) subAttrs.add(a.attr)
    for (const t of item.terms ?? []) terms.add(t.id)
    for (const a of item.baseAttrs ?? []) if (DOHDOL_BONUS_NAMES[a.attr]) bonuses.add(a.attr)
  }
  const byLabel = (id: string, label: string) => ({ id, label })
  const sortZh = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label, 'zh-Hans-CN')
  return {
    slots: [...slots].map((id) => byLabel(id, slotName(id))).sort(sortZh),
    categories: [...categories].map((id) => byLabel(id, categoryName(id))).sort(sortZh),
    weaponTypes: [...weaponTypes]
      .map((id) => byLabel(id, WEAPON_TYPE_LABELS[id] ?? id))
      .sort(sortZh),
    subAttrs: [...subAttrs].map((id) => byLabel(id, attrName(id))).sort(sortZh),
    terms: [...terms].map((id) => byLabel(id, TERM_BY_ID[id]?.name ?? id)).sort(sortZh),
    bonuses: [...bonuses].map((id) => byLabel(id, DOHDOL_BONUS_NAMES[id])).sort(sortZh),
  }
}

/** 按筛选状态筛选 + 排序，返回新数组（不改原数组）。 */
export function applyItemFilters(items: Item[], f: ItemFilterState, sort: SortKey): Item[] {
  const min = typeof f.levelMin === 'number' ? f.levelMin : null
  const max = typeof f.levelMax === 'number' ? f.levelMax : null
  const list = items.filter((i) => {
    if (f.rarity !== 'all' && i.rarity !== f.rarity) return false
    if (f.category !== 'all' && i.category !== f.category) return false
    if (f.slot !== 'all' && (i.equipSlots?.[0] ?? i.slot) !== f.slot) return false
    if (f.weaponType !== 'all' && i.weaponType !== f.weaponType) return false
    if (f.role !== 'all' && roleOfBaseId(i.baseId) !== f.role) return false
    if (min !== null && i.levelReq < min) return false
    if (max !== null && i.levelReq > max) return false
    if (f.subAttrs.size && !(i.subAttrs ?? []).some((a) => f.subAttrs.has(a.attr))) return false
    if (f.terms.size && !(i.terms ?? []).some((t) => f.terms.has(t.id))) return false
    if (
      f.quality.size &&
      !(
        (i.subAttrs ?? []).some((a) => f.quality.has(a.quality ?? 'common')) ||
        (i.terms ?? []).some((t) => f.quality.has(t.quality))
      )
    ) {
      return false
    }
    if (f.bonus.size && !(i.baseAttrs ?? []).some((a) => f.bonus.has(a.attr))) return false
    return true
  })

  const rarityIndex = (r: RarityId) => RARITY_ORDER.indexOf(r)
  return list.sort((a, b) => {
    if (sort === 'power') return b.score - a.score || rarityIndex(b.rarity) - rarityIndex(a.rarity)
    if (sort === 'rarity') return rarityIndex(b.rarity) - rarityIndex(a.rarity) || b.levelReq - a.levelReq
    if (sort === 'level') return b.levelReq - a.levelReq
    return a.name.localeCompare(b.name, 'zh-Hans-CN')
  })
}
