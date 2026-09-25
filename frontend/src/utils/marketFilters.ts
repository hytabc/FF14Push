import type { RarityId } from '@/game/types'

/**
 * 市场寄售浏览的筛选状态。
 *
 * 这里全部是「标量」维度，直接下推到 `/market/listings`（服务端筛选 + 分页），
 * 因此不像背包那样做客户端纯函数过滤：候选集合是整张市场表，前端拿不到全量。
 */
export interface MarketFilterState {
  /** 名称关键字（服务端 ILIKE 子串匹配）。 */
  q: string
  rarity: 'all' | RarityId
  category: string
  slot: string
  levelMin: number | ''
  levelMax: number | ''
  priceMin: number | ''
  priceMax: number | ''
}

export function createMarketFilters(): MarketFilterState {
  return {
    q: '',
    rarity: 'all',
    category: 'all',
    slot: 'all',
    levelMin: '',
    levelMax: '',
    priceMin: '',
    priceMax: '',
  }
}

export function hasMarketFilters(f: MarketFilterState): boolean {
  return (
    f.q.trim() !== '' ||
    f.rarity !== 'all' ||
    f.category !== 'all' ||
    f.slot !== 'all' ||
    f.levelMin !== '' ||
    f.levelMax !== '' ||
    f.priceMin !== '' ||
    f.priceMax !== ''
  )
}

export function resetMarketFilters(f: MarketFilterState): void {
  Object.assign(f, createMarketFilters())
}

/** 与筛选状态无关的分页 / 品类上下文。 */
export interface MarketPageBase {
  kind: string
  sort: string
  page: number
  pageSize: number
}

/**
 * 组装 `api.marketListings` 的查询参数：`'all'` / `''` 一律省略，
 * 数值区间转成数字（注意 0 是合法价格，不能被当成空值丢掉）。
 * 后端对 level>=1 / price>=0 有校验，这里先挡掉越界输入，避免无谓的 422。
 */
export function marketQueryParams(f: MarketFilterState, base: MarketPageBase) {
  const price = (v: number | '') => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : undefined)
  const level = (v: number | '') => (typeof v === 'number' && Number.isFinite(v) && v >= 1 ? v : undefined)
  return {
    kind: base.kind,
    sort: base.sort,
    page: base.page,
    pageSize: base.pageSize,
    q: f.q.trim() || undefined,
    rarity: f.rarity === 'all' ? undefined : f.rarity,
    category: f.category === 'all' ? undefined : f.category,
    slot: f.slot === 'all' ? undefined : f.slot,
    levelMin: level(f.levelMin),
    levelMax: level(f.levelMax),
    priceMin: price(f.priceMin),
    priceMax: price(f.priceMax),
  }
}
