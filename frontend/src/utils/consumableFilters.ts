import data from '@shared/schema'

import type { MaterialStackItem } from '@/game/types'

/**
 * 背包 / 生产页「药水 / 食物」的筛选与排序（纯函数，便于单测锁定语义）。
 *
 * 与 `itemFilters.ts` / `fishFilters.ts` 同一定位：组件只持有 `ConsumableFilterState`，
 * 过滤与排序逻辑全部在这里。默认排序把**相同类型**的消耗品聚在一起（药水 → 食物，
 * 组内按加成效果归类，再按 I/II/III 档位排列）。
 */
export type ConsumableSortKey = 'group' | 'count' | 'name'

export const CONSUMABLE_SORT_OPTIONS: { id: ConsumableSortKey; label: string }[] = [
  { id: 'group', label: '按类型分组' },
  { id: 'count', label: '按数量排序' },
  { id: 'name', label: '按名称排序' },
]

export type ConsumableKindFilter = 'all' | 'potion' | 'food'

export interface ConsumableFilterState {
  /** 药水 / 食物分类。 */
  kind: ConsumableKindFilter
  /** 加成效果（`effects[0].stat`），'all' 表示不限。 */
  effect: string
  /** 名称搜索关键字。 */
  search: string
}

export function createConsumableFilters(): ConsumableFilterState {
  return { kind: 'all', effect: 'all', search: '' }
}

/** 是否设置了任何筛选（用于显示「清除筛选」）。 */
export function hasActiveConsumableFilters(f: ConsumableFilterState): boolean {
  return f.kind !== 'all' || f.effect !== 'all' || f.search.trim() !== ''
}

/** 消耗品分类：优先取定义，回退到 stack 自带字段。 */
function kindOf(item: MaterialStackItem): string {
  return data.consumableById[item.itemId]?.kind ?? item.consumableKind ?? item.kind
}

function effectsOf(item: MaterialStackItem): { stat: string; value: number }[] {
  return data.consumableById[item.itemId]?.effects ?? item.effects ?? []
}

/** 分组主效果 = `effects[0].stat`（无定义时为空串）。 */
export function consumableEffectKey(item: MaterialStackItem): string {
  return effectsOf(item)[0]?.stat ?? ''
}

/** 档位：id 尾缀数字（I/II/III → 1/2/3），无尾缀视为第 1 档。 */
export function consumableTier(itemId: string): number {
  const matched = /(\d+)$/.exec(itemId)
  return matched ? Number(matched[1]) : 1
}

const KIND_ORDER: Record<string, number> = { potion: 0, food: 1 }
const EFFECT_ORDER: string[] = Object.keys(data.consumables.effectNames)

function effectRank(item: MaterialStackItem): number {
  const index = EFFECT_ORDER.indexOf(consumableEffectKey(item))
  return index < 0 ? EFFECT_ORDER.length : index
}

/** 加成效果可选项（只列出候选池中实际作为主效果出现的，顺序按配置）。 */
export function consumableEffectOptions(items: MaterialStackItem[]): { id: string; label: string }[] {
  const present = new Set(items.map(consumableEffectKey).filter(Boolean))
  return EFFECT_ORDER.filter((stat) => present.has(stat)).map((stat) => ({
    id: stat,
    label: data.consumables.effectNames[stat] ?? stat,
  }))
}

/** 按筛选状态过滤 + 排序，返回新数组（不改原数组）。 */
export function applyConsumableFilters(
  items: MaterialStackItem[],
  f: ConsumableFilterState,
  sort: ConsumableSortKey,
): MaterialStackItem[] {
  const search = f.search.trim().toLowerCase()
  const list = items.filter((item) => {
    if (f.kind !== 'all' && kindOf(item) !== f.kind) return false
    if (f.effect !== 'all' && !effectsOf(item).some((e) => e.stat === f.effect)) return false
    if (search && !item.name.toLowerCase().includes(search)) return false
    return true
  })

  const byName = (a: MaterialStackItem, b: MaterialStackItem) => a.name.localeCompare(b.name, 'zh-Hans-CN')

  return list.sort((a, b) => {
    if (sort === 'count') return b.count - a.count || byName(a, b)
    if (sort === 'name') return byName(a, b)

    // group（默认）：分类 → 主效果 → 档位 → 数量 → 名称，把同类型消耗品聚在一起。
    const kindDiff = (KIND_ORDER[kindOf(a)] ?? 9) - (KIND_ORDER[kindOf(b)] ?? 9)
    if (kindDiff) return kindDiff
    const effectDiff = effectRank(a) - effectRank(b)
    if (effectDiff) return effectDiff
    const tierDiff = consumableTier(a.itemId) - consumableTier(b.itemId)
    if (tierDiff) return tierDiff
    if (b.count !== a.count) return b.count - a.count
    return byName(a, b)
  })
}
