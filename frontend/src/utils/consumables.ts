import data from '@shared/schema'

/** Shared definitions store chest luck as a ratio; other effects use percentage values. */
export function consumableBonus(itemId?: string | null): string {
  const item = itemId ? data.consumableById[itemId] : undefined
  if (!item) return ''
  const effects = item.effects.map(({ stat, value }) => {
    const percent = Number((stat === 'chestLuck' ? value * 100 : value).toFixed(2))
    return (data.consumables.effectNames[stat] ?? stat) + ' ' + (percent >= 0 ? '+' : '') + percent + '%'
  })
  return effects.join(' · ') + ' · 持续 ' + data.consumables.kinds[item.kind].durationSec + ' 秒'
}
