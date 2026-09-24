import data from '@shared/schema'
import type { TitleDef } from '@shared/schema'

/** 称号 id → 定义（名称 / 描述 / 条件 / 是否彩蛋）。 */
const TITLE_BY_ID: Record<string, TitleDef> = Object.fromEntries(
  data.titles.titles.map((t) => [t.id, t]),
)

export function titleName(id: string): string {
  return TITLE_BY_ID[id]?.name ?? id
}

export function titleDef(id: string): TitleDef | null {
  return TITLE_BY_ID[id] ?? null
}

/** 是否为彩蛋称号（低概率掉落，非确定性条件）。 */
export function isEggTitle(id: string): boolean {
  return Boolean(TITLE_BY_ID[id]?.egg)
}
