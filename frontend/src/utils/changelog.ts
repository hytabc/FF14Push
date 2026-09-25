/**
 * 根目录 `CHANGELOG.md` 的轻量解析（纯函数，便于单测）。
 *
 * 约定格式（见根目录 CHANGELOG.md）：
 *   ## V1.0.1 — 2026-09-25
 *   - 一条更新概要
 * 仅识别 `## Vx.y.z` 版本标题行与 `- ` / `* ` 条目行，说明段落与空行一律忽略。
 */

export interface ChangelogEntry {
  /** 形如 `1.0.1`（不含前缀 V）。 */
  version: string
  /** 版本标题里的日期文本，未写时为 undefined。 */
  date?: string
  /** 该版本下的更新条目文本，按出现顺序。 */
  items: string[]
}

const VERSION_HEADING = /^##\s+V?(\d+\.\d+\.\d+)\s*(?:[—–-]\s*(.+?))?\s*$/
const ITEM = /^\s*[-*]\s+(.+?)\s*$/

/** 解析更新日志文本；无法识别任何版本时返回空数组。 */
export function parseChangelog(raw: string): ChangelogEntry[] {
  const entries: ChangelogEntry[] = []
  let current: ChangelogEntry | null = null

  for (const line of raw.split(/\r?\n/)) {
    const heading = VERSION_HEADING.exec(line)
    if (heading) {
      current = { version: heading[1], date: heading[2] || undefined, items: [] }
      entries.push(current)
      continue
    }
    if (!current) continue
    const item = ITEM.exec(line)
    if (item) current.items.push(item[1])
  }

  return entries
}
