import data from '@shared/schema'

/**
 * 装备像素图标索引：baseId → 资源 URL。
 *
 * PNG 由 `scripts/gen-icons.mjs` 生成，单张仅约 130 字节，
 * 远低于 Vite 默认的 assetsInlineLimit（4096），因此会被内联成 data URI，
 * 页面批量渲染装备时不会产生任何图片请求。
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

export function itemIconName(baseId: string): string {
  return data.baseItemById[baseId]?.name ?? baseId
}
