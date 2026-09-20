import data, { ATTR_NAMES, BASE_ATTR_NAMES } from '@shared/schema'

import type { RarityId, TermQuality } from '@/game/types'

export const RARITY_ORDER = data.rarities.order as RarityId[]

const RARITY_CLASS: Record<RarityId, string> = {
  common: 'text-rarity-common border-rarity-common/50',
  uncommon: 'text-rarity-uncommon border-rarity-uncommon/50',
  rare: 'text-rarity-rare border-rarity-rare/50',
  epic: 'text-rarity-epic border-rarity-epic/50',
  legendary: 'text-rarity-legendary border-rarity-legendary/50',
  mythic: 'text-rarity-mythic border-rarity-mythic/50',
}

const RARITY_BG: Record<RarityId, string> = {
  common: 'bg-rarity-common/10',
  uncommon: 'bg-rarity-uncommon/10',
  rare: 'bg-rarity-rare/10',
  epic: 'bg-rarity-epic/12',
  legendary: 'bg-rarity-legendary/12',
  mythic: 'bg-rarity-mythic/14',
}

const RARITY_HEX: Record<RarityId, string> = {
  common: '#d8d8d8',
  uncommon: '#3fc46a',
  rare: '#3f7fe0',
  epic: '#a855f7',
  legendary: '#f97316',
  mythic: '#ef4444',
}

export function rarityName(rarity: RarityId): string {
  return data.rarities.byId[rarity]?.name ?? rarity
}

export function rarityClass(rarity: RarityId): string {
  return RARITY_CLASS[rarity] ?? RARITY_CLASS.common
}

export function rarityBg(rarity: RarityId): string {
  return RARITY_BG[rarity] ?? RARITY_BG.common
}

export function rarityHex(rarity: RarityId): string {
  return RARITY_HEX[rarity] ?? RARITY_HEX.common
}

export function termQualityName(quality: TermQuality): string {
  return { common: '普通', rare: '稀有', ancient: '太古' }[quality] ?? quality
}

export function termQualityClass(quality: TermQuality): string {
  return {
    common: 'border-term-common/40 text-ink-200',
    rare: 'border-term-rare text-term-rare',
    ancient: 'border-term-ancient text-term-ancient',
  }[quality]
}

export function attrName(attrId: string): string {
  return ATTR_NAMES[attrId] ?? baseAttrName(attrId)
}

export function baseAttrName(attrId: string): string {
  return BASE_ATTR_NAMES[attrId as keyof typeof BASE_ATTR_NAMES] ?? attrId
}

export function attrSuffix(attrId: string): string {
  const def = (data.attributeById as Record<string, { valueType: string } | undefined>)[attrId]
  return def?.valueType === 'percent' ? '%' : ''
}

export function slotName(slot: string): string {
  return data.slots.find((s) => s.id === slot)?.name ?? slot
}

export function jobName(jobId: string): string {
  if (jobId === 'adventurer') return '冒险者'
  return data.jobById[jobId]?.name ?? jobId
}

export function categoryName(category: string): string {
  return { weapon: '武器', armor: '防具', accessory: '饰品' }[category] ?? category
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)} 万`
  return Math.round(value).toString()
}

export function formatPercent(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`
}

export function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}
