import type { FishEntryKind, FishRarityTier } from '@/utils/icons'

/**
 * 鱼获图鉴的分维度筛选（纯函数，便于单测锁定语义）。
 *
 * 与 `itemFilters.ts` 同一定位：组件只持有 `FishFilterState`，过滤逻辑全部在这里。
 */
export interface FishFilterEntry {
  kind?: string | null
  rarity?: string | null
  regionId?: number | null
  weather?: string[] | null
  timeOfDay?: string[] | null
  requires?: Array<{ fishId: string; count: number }> | null
  sizeMin?: number | null
  sizeMax?: number | null
}

export interface FishFilterState {
  /** 钓场（地区 id）。 */
  regionId: number | 'all'
  /** 鱼种类：普通鱼 / 鱼王 / 鱼皇 / 困难鱼。 */
  kind: FishEntryKind | 'all'
  /** 品质（档位）：白鱼 / 蓝鱼 / 紫鱼；仅普通鱼有。 */
  rarity: FishRarityTier | 'all'
  /** 天气门槛（多选，任一命中）。 */
  weather: Set<string>
  /** 时段门槛（多选，任一命中）。 */
  timeOfDay: Set<string>
  /** 直觉前置：全部 / 需要前置 / 无需前置。 */
  requires: 'all' | 'has' | 'none'
  /** 尺寸下限（cm），'' 表示不限。 */
  sizeMin: number | ''
  /** 尺寸上限（cm），'' 表示不限。 */
  sizeMax: number | ''
  /** 只看此刻就能钓起的鱼（判定由调用方注入，见 `applyFishFilters` 的第三个参数）。 */
  catchableOnly: boolean
}

export function createFishFilters(): FishFilterState {
  return {
    regionId: 'all',
    kind: 'all',
    rarity: 'all',
    weather: new Set(),
    timeOfDay: new Set(),
    requires: 'all',
    sizeMin: '',
    sizeMax: '',
    catchableOnly: false,
  }
}

/** 是否设置了任何筛选（用于显示「重置」）。 */
export function hasFishFilters(f: FishFilterState): boolean {
  return (
    f.regionId !== 'all' ||
    f.kind !== 'all' ||
    f.rarity !== 'all' ||
    f.weather.size > 0 ||
    f.timeOfDay.size > 0 ||
    f.requires !== 'all' ||
    f.sizeMin !== '' ||
    f.sizeMax !== '' ||
    f.catchableOnly
  )
}

/** 是否带直觉前置（钓齐计数型前置才开启的特殊鱼）。 */
function hasRequires(entry: FishFilterEntry): boolean {
  return Array.isArray(entry.requires) && entry.requires.length > 0
}

/**
 * 天气 / 时段这类「条件门槛」的多选匹配：**严格匹配**。
 *
 * 未选任何项时不过滤；选了以后只保留把该条件列为要求的条目 —— 没有门槛（随时可钓）的鱼
 * 不算命中，否则筛「小雨」时几乎全部普通鱼都会留下，筛选就失去意义。
 */
function matchesStrictGate(values: unknown, picked: Set<string>): boolean {
  if (picked.size === 0) return true
  return Array.isArray(values) && values.some((value) => picked.has(String(value)))
}

/**
 * 按筛选条件过滤鱼获条目。
 *
 * - 天气 / 时段：严格匹配（见 `matchesStrictGate`）。
 * - 品质：只适用于普通鱼 —— 鱼王 / 鱼皇 / 困难鱼的 `rarity` 为 `null`，选具体品质时被排除。
 * - 尺寸：按**区间相交**判定。输入 `[min, max]` 时保留「可钓尺寸范围与该区间有交集」的鱼，
 *   因此「只看能钓到 ≥ min cm 的鱼」符合直觉，而不是要求整段范围被包含。
 * - 尺寸字段缺失时不参与该维度判定（不因此被排除）。
 * - `catchableOnly`：由调用方通过 `isCatchable` 注入「此刻是否可钓」的判定（本模块不依赖
 *   天气 / 玩家进度，保持可独立单测）；不传该谓词时此开关不生效。
 */
export function applyFishFilters<T extends FishFilterEntry>(
  entries: T[],
  f: FishFilterState,
  isCatchable?: (entry: T) => boolean,
): T[] {
  const sizeMin = typeof f.sizeMin === 'number' ? f.sizeMin : null
  const sizeMax = typeof f.sizeMax === 'number' ? f.sizeMax : null

  return entries.filter((entry) => {
    if (f.regionId !== 'all' && entry.regionId !== f.regionId) return false
    if (f.kind !== 'all' && entry.kind !== f.kind) return false
    if (f.rarity !== 'all' && entry.rarity !== f.rarity) return false
    if (!matchesStrictGate(entry.weather, f.weather)) return false
    if (!matchesStrictGate(entry.timeOfDay, f.timeOfDay)) return false
    if (f.requires === 'has' && !hasRequires(entry)) return false
    if (f.requires === 'none' && hasRequires(entry)) return false
    if (f.catchableOnly && isCatchable && !isCatchable(entry)) return false

    const lo = typeof entry.sizeMin === 'number' ? entry.sizeMin : null
    const hi = typeof entry.sizeMax === 'number' ? entry.sizeMax : null
    if (sizeMin !== null && hi !== null && hi < sizeMin) return false
    if (sizeMax !== null && lo !== null && lo > sizeMax) return false

    return true
  })
}

/** 条目里实际出现过的取值，用于只列出有内容的筛选项（顺序由调用方按配置决定）。 */
export function presentFishValues<T extends FishFilterEntry>(entries: T[]) {
  const regions = new Set<number>()
  const kinds = new Set<string>()
  const rarities = new Set<string>()
  const weather = new Set<string>()
  const timeOfDay = new Set<string>()

  for (const entry of entries) {
    if (typeof entry.regionId === 'number') regions.add(entry.regionId)
    if (entry.kind) kinds.add(String(entry.kind))
    if (entry.rarity) rarities.add(String(entry.rarity))
    for (const w of entry.weather ?? []) weather.add(String(w))
    for (const t of entry.timeOfDay ?? []) timeOfDay.add(String(t))
  }

  return { regions, kinds, rarities, weather, timeOfDay }
}
