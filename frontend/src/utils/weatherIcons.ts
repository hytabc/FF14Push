/**
 * 天气图标索引：天气 id（`shared/data/weather.json` 的 `types[].id`）→ 资源 URL。
 *
 * PNG 为《最终幻想14》官方天气图标，由 `scripts/fetch-weather-assets.mjs` 下载并随仓库提交
 * （单张约 2.4 KB，低于 Vite 默认 assetsInlineLimit，会被内联成 data URI）。
 */
const modules = import.meta.glob('../assets/weather/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const URL_BY_ID: Record<string, string> = Object.fromEntries(
  Object.entries(modules).map(([path, url]) => [path.split('/').pop()!.replace(/\.png$/, ''), url]),
)

export const WEATHER_ICON_IDS = Object.keys(URL_BY_ID)

export function weatherIconUrl(weatherId: string): string | undefined {
  return URL_BY_ID[weatherId]
}
