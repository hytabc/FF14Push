import data from '@shared/schema'
import type { FishEntryKind as FishEntryKindShared, FishRarity } from '@shared/schema'

import type { RarityId } from '@/game/types'

/**
 * 物品像素图标索引：物品 id（战斗底材 baseId / 采集材料 itemId / 专用装备 baseId /
 * 消耗品 itemId / 鱼获 id）→ 资源 URL。
 *
 * PNG 由 `scripts/gen-icons.mjs` 生成，单张仅约 130 字节，
 * 远低于 Vite 默认的 assetsInlineLimit（4096），因此会被内联成 data URI，
 * 页面批量渲染物品时不会产生任何图片请求。
 */
const modules = import.meta.glob('../assets/icons/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const ICON_BY_BASE_ID: Record<string, string> = Object.fromEntries(
  Object.entries(modules).map(([path, url]) => [path.split('/').pop()!.replace(/\.png$/, ''), url]),
)

export const ICON_BASE_IDS = Object.keys(ICON_BY_BASE_ID)

export function itemIconUrl(baseId: string): string | undefined {
  return ICON_BY_BASE_ID[baseId]
}

/** 物品 id → 中文名，逐级回退（战斗底材 → 材料/半成品/鱼 → 专用装备 → 消耗品 → 魔晶石/种子），绝不直接把 id 抛给玩家。 */
export function itemIconName(baseId: string): string {
  return (
    data.baseItemById[baseId]?.name ??
    data.materialById[baseId]?.name ??
    data.dohdolItemById[baseId]?.name ??
    data.consumableById[baseId]?.name ??
    data.materiaById[baseId]?.name ??
    data.seedById[baseId]?.name ??
    baseId
  )
}

/** 鱼获类别与普通鱼档位（与 @shared/schema 同源）。 */
export type FishEntryKind = FishEntryKindShared
export type FishRarityTier = FishRarity

/** 鱼获稀有度：普通鱼 / 鱼王 / 鱼皇 / 困难鱼，用于图标光晕色调。 */
export function fishKindRarity(kind: FishEntryKind): RarityId {
  if (kind === 'legend') return 'mythic'
  if (kind === 'emperor') return 'mythic'
  if (kind === 'king') return 'legendary'
  return 'common'
}

/** 普通鱼档位（白 / 蓝 / 紫）；特殊鱼或无记录时回落 white。 */
export function fishRarityTier(fishId: string): FishRarityTier {
  return data.fishById[fishId]?.rarity ?? 'white'
}

/** 由鱼获 id 推断图标光晕：普通鱼按档位，特殊鱼按类别。 */
export function fishRarity(fishId: string): RarityId {
  const info = data.fishById[fishId]
  if (!info) return 'common'
  if (info.kind !== 'normal') return fishKindRarity(info.kind)
  return info.rarity === 'purple' ? 'rare' : info.rarity === 'blue' ? 'uncommon' : 'common'
}

/** 由鱼获 id 推断种类（普通 f{r}_{n} / 鱼王 k{r} / 鱼皇 e{r} / 困难鱼 l…）。 */
export function fishKindFromId(id: string): FishEntryKind {
  return data.fishById[id]?.kind ?? 'normal'
}
