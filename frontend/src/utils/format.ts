import data, { ATTR_NAMES, BASE_ATTR_NAMES } from '@shared/schema'

import type { RarityId, TermEntry, TermQuality } from '@/game/types'

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

/** 词条显示名：太古用 🌟 标记（替代文字），稀有保留文字后缀。 */
export function termLabel(term: TermEntry): string {
  if (term.quality === 'ancient') return `${term.name}🌟`
  if (term.quality === 'rare') return `${term.name}（稀有）`
  return term.name
}

export function termQualityClass(quality: TermQuality): string {
  return {
    common: 'border-term-common/40 text-ink-200',
    rare: 'border-term-rare text-term-rare',
    ancient: 'border-term-ancient text-term-ancient',
  }[quality]
}

/**
 * 属性 id → 中文名。
 * 饰品底材用的是副属性 id（str/dex/int/vit），武器与防具用的是底材属性 id（attack/physDef…），
 * 因此两张表要互相兜底，否则会回落成英文 id。
 */
export function attrName(attrId: string): string {
  return ATTR_NAMES[attrId] ?? BASE_ATTR_NAMES[attrId as keyof typeof BASE_ATTR_NAMES] ?? attrId
}

export function baseAttrName(attrId: string): string {
  return BASE_ATTR_NAMES[attrId as keyof typeof BASE_ATTR_NAMES] ?? ATTR_NAMES[attrId] ?? attrId
}

export function attrSuffix(attrId: string): string {
  const def = (data.attributeById as Record<string, { valueType: string } | undefined>)[attrId]
  return def?.valueType === 'percent' ? '%' : ''
}

export function slotName(slot: string): string {
  return data.slots.find((s) => s.id === slot)?.name ?? slot
}

/** 底材 slot（自选装备种类）→ 中文名。 */
const BASE_SLOT_NAMES: Record<string, string> = {
  mainHand: '武器',
  head: '头盔',
  body: '铠甲',
  hands: '手甲',
  legs: '护腿',
  feet: '战靴',
  necklace: '项链',
  earring: '耳环',
  bracelet: '手镯',
  ring: '戒指',
}

export function baseSlotName(slot: string): string {
  return BASE_SLOT_NAMES[slot] ?? slotName(slot)
}

export function jobName(jobId: string): string {
  if (jobId === 'adventurer') return '冒险者'
  return data.jobById[jobId]?.name ?? jobId
}

export function categoryName(category: string): string {
  return { weapon: '武器', armor: '防具', accessory: '饰品' }[category] ?? category
}

function durationSuffix(seconds: number): string {
  return seconds > 0 ? `（${seconds}s）` : ''
}

/** 技能效果的中文label。覆盖 jobs.json 中出现的全部 effects[].type。 */
const SKILL_EFFECT_LABELS: Record<string, (pct: number, seconds: number) => string> = {
  heal: (pct) => `回复生命 ${pct}%`,
  healOverTime: (pct, seconds) => `持续回复 ${pct}%${durationSuffix(seconds)}`,
  fullHeal: () => '生命全满',
  shield: (pct, seconds) => `获得护盾 ${pct}%${durationSuffix(seconds)}`,
  dot: (pct, seconds) => `持续伤害 ${pct}%${durationSuffix(seconds)}`,
  stun: (_pct, seconds) => `眩晕${durationSuffix(seconds)}`,
  mpRestore: (pct) => `回复魔力 ${pct}%`,
  mpDumpPotency: () => '消耗全部魔力提升威力',
  cdReduceAll: (pct) => `全部技能冷却 −${pct}%`,
  attackBuff: (pct, seconds) => `攻击力 +${pct}%${durationSuffix(seconds)}`,
  critRateBuff: (pct, seconds) => `暴击率 +${pct}%${durationSuffix(seconds)}`,
  attackSpeedBuff: (pct, seconds) => `攻击速度 +${pct}%${durationSuffix(seconds)}`,
  allDamageBuff: (pct, seconds) => `全伤害 +${pct}%${durationSuffix(seconds)}`,
  damageReduction: (pct, seconds) => `受到伤害 −${pct}%${durationSuffix(seconds)}`,
}

/** 技能效果 → 中文说明；未知类型不暴露原始英文枚举。 */
export function skillEffectLabel(effect: { type?: unknown; value?: unknown; duration?: unknown }): string {
  const builder = SKILL_EFFECT_LABELS[String(effect?.type ?? '')]
  if (!builder) return '未知效果'
  const pct = Math.round(Number(effect.value ?? 0) * 100)
  const seconds = Math.round(Number(effect.duration ?? 0))
  return builder(pct, seconds)
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
