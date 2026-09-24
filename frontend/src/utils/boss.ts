/**
 * 世界BOSS 立绘索引：BOSS id（`shared/data/worldboss.json` 的 `boss.id`）→ 立绘 URL。
 *
 * PNG 由 `scripts/fetch-boss-asset.mjs` 下载并随仓库提交，这里用 glob 拿资源 URL
 * （体积小，会被 Vite 内联/打包），构建与 CI 都不需要联网。
 * 无对应素材时返回 undefined，由调用方决定兜底表现。
 */
const modules = import.meta.glob('../assets/boss/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

/** 资源路径 → BOSS id（文件名即 `worldboss.json` 的 `boss.id`）。 */
const FIGURE_BY_KEY: Record<string, string> = Object.fromEntries(
  Object.entries(modules).map(([path, url]) => [path.split('/').pop()!.replace(/\.png$/, ''), url]),
)

/** BOSS id → 立绘 URL。 */
export function bossFigureUrl(bossKey: string | null | undefined): string | undefined {
  return bossKey ? FIGURE_BY_KEY[bossKey] : undefined
}
