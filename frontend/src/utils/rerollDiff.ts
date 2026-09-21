import { attrName, baseAttrName, termLabel } from '@/utils/format'
import type { Item, RerollChange } from '@/game/types'

export type RerollKind = 'refine' | 'enchant'

const EPS = 1e-9

function direction(before: number | null, after: number | null): RerollChange['direction'] {
  if (before == null || after == null) return after != null ? 'up' : 'down'
  if (after > before + EPS) return 'up'
  if (after < before - EPS) return 'down'
  return 'same'
}

interface AttrGroup {
  key: string
  prev: Item['baseAttrs']
  next: Item['baseAttrs']
  label: (attr: string) => string
}

/**
 * 重造 / 附魔前后的逐条涨跌。
 * 属性按 attr 匹配、词条按 id 匹配；仅存在于 after 的条目视为新增、仅存在于 before 的视为消失。
 * direction 表示「对玩家是好是坏」：up=涨（绿）、down=降（红）。
 */
export function diffReroll(kind: RerollKind, before: Item, after: Item): RerollChange[] {
  const out: RerollChange[] = []

  if (kind === 'enchant') {
    const prev = new Map(before.terms.map((t) => [t.id, t]))
    const next = new Map(after.terms.map((t) => [t.id, t]))
    for (const [id, term] of next) {
      const old = prev.get(id)
      const beforeValue = old ? old.value : null
      out.push({
        key: `t_${id}`,
        name: termLabel(term),
        // 新增 Debuff 视为变差（红），新增 Buff 视为变好（绿）
        direction: beforeValue == null ? (term.type === 'debuff' ? 'down' : 'up') : direction(beforeValue, term.value),
        before: beforeValue,
        after: term.value,
        delta: beforeValue == null ? null : term.value - beforeValue,
      })
    }
    for (const [id, term] of prev) {
      if (next.has(id)) continue
      out.push({
        key: `t_${id}`,
        name: termLabel(term),
        // 失去 Buff 变差（红），失去 Debuff 变好（绿）
        direction: term.type === 'debuff' ? 'up' : 'down',
        before: term.value,
        after: null,
        delta: null,
      })
    }
    return out
  }

  const groups: AttrGroup[] = [
    { key: 'b', prev: before.baseAttrs, next: after.baseAttrs, label: baseAttrName },
    { key: 's', prev: before.subAttrs, next: after.subAttrs, label: attrName },
  ]
  for (const group of groups) {
    const prev = new Map(group.prev.map((e) => [e.attr, e.value]))
    const next = new Map(group.next.map((e) => [e.attr, e.value]))
    for (const [attr, value] of next) {
      const beforeValue = prev.has(attr) ? (prev.get(attr) as number) : null
      out.push({
        key: `${group.key}_${attr}`,
        name: group.label(attr),
        direction: direction(beforeValue, value),
        before: beforeValue,
        after: value,
        delta: beforeValue == null ? null : value - beforeValue,
      })
    }
    for (const [attr, value] of prev) {
      if (next.has(attr)) continue
      out.push({
        key: `${group.key}_${attr}`,
        name: group.label(attr),
        direction: 'down',
        before: value,
        after: null,
        delta: null,
      })
    }
  }
  return out
}
