/**
 * 战斗职业素材索引：职业小人（FF14 官方立绘）与职业图标（FF14 彩色图标）。
 *
 * PNG 由 `scripts/fetch-job-assets.mjs` 下载并随仓库提交，这里用 glob 拿到资源 URL
 * （体积小，会被 Vite 内联成 data URI）。`adventurer` 等无对应职业的 id 返回 undefined，
 * 由调用方决定是否隐藏。
 */
const figureModules = import.meta.glob('../assets/jobs/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const iconModules = import.meta.glob('../assets/jobs/icons/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

/** 资源路径 → 职业 id（文件名即 `shared/data/jobs.json` 的 job.id）。 */
function byJobId(modules: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(modules).map(([path, url]) => [path.split('/').pop()!.replace(/\.png$/, ''), url]),
  )
}

const FIGURE_BY_JOB = byJobId(figureModules)
const ICON_BY_JOB = byJobId(iconModules)

/** 职业 id → 小人立绘 URL。 */
export function jobFigureUrl(jobId: string | null | undefined): string | undefined {
  return jobId ? FIGURE_BY_JOB[jobId] : undefined
}

/** 职业 id → 职业图标 URL。 */
export function jobIconUrl(jobId: string | null | undefined): string | undefined {
  return jobId ? ICON_BY_JOB[jobId] : undefined
}

/** 小人立绘原始尺寸（宽 × 高），用于按宽度等比推算高度。 */
export const JOB_FIGURE_RATIO = 60 / 52
