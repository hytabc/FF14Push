import data, { ATTR_NAMES, BASE_ATTR_NAMES } from '@shared/schema'

import type { RarityId, TermEntry, TermQuality } from '@/game/types'

export const RARITY_ORDER = data.rarities.order as RarityId[]

/** 生产/采集专用装备加成 id → 中文名。 */
const DOHDOL_BONUS_NAMES: Record<string, string> = data.dohdolEquipment.bonusNames

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

/** 词条 id → 数值区间（战斗词条 + 生产/采集词条，两个池的 id 互不重复）。 */
const TERM_RANGE_BY_ID: Record<string, readonly [number, number]> = Object.fromEntries(
  [...data.terms.terms, ...data.dohdolEquipment.terms].map((t) => [t.id, t.range] as const),
)

/** 词条数值的上下限区间；未知词条返回 null。 */
export function termRange(termId: string): readonly [number, number] | null {
  return TERM_RANGE_BY_ID[termId] ?? null
}

export function termQualityClass(quality: TermQuality): string {
  return {
    common: 'border-term-common/40 text-ink-200',
    rare: 'border-term-rare text-term-rare',
    ancient: 'border-term-ancient text-term-ancient',
  }[quality]
}

/** 副属性品质 → 文本色：普通天蓝，稀有/太古金色（太古更亮 + 发光）。 */
export function subAttrQualityClass(quality?: TermQuality): string {
  if (quality === 'ancient') return 'text-term-ancient term-ancient-glow'
  if (quality === 'rare') return 'text-term-rare'
  return 'text-sky-300'
}

/** 属性区间展示：`【下限-上限】`（与数值同精度，缺省时返回空串）。 */
export function attrRangeLabel(min?: number, max?: number, digits = 0): string {
  if (min == null || max == null) return ''
  return `【${min.toFixed(digits)}-${max.toFixed(digits)}】`
}

const TAG_COLOR_FALLBACK = { name: '灰', hex: '#9ca3af' }

function tagColorById(colorId: string): { name: string; hex: string } {
  const byId = data.tagColors.byId as Record<string, { name: string; hex: string } | undefined>
  return byId[colorId] ?? TAG_COLOR_FALLBACK
}

/** 标签颜色 id → 颜色 hex（未知回退灰色）。 */
export function tagColorHex(colorId: string): string {
  return tagColorById(colorId).hex
}

/** 标签颜色 id → 中文名。 */
export function tagColorName(colorId: string): string {
  return tagColorById(colorId).name
}

/** 调色板顺序（新建标签时的颜色选择器）。 */
export const TAG_COLORS = data.tagColors.order.map((id) => {
  const { name, hex } = tagColorById(id)
  return { id, name, hex }
})

/**
 * 属性 id → 中文名。
 * 饰品底材用的是副属性 id（str/dex/int/vit），武器与防具用的是底材属性 id（attack/physDef…），
 * 因此两张表要互相兜底，否则会回落成英文 id。
 */
export function attrName(attrId: string): string {
  return (
    ATTR_NAMES[attrId] ??
    BASE_ATTR_NAMES[attrId as keyof typeof BASE_ATTR_NAMES] ??
    DOHDOL_BONUS_NAMES[attrId] ??
    attrId
  )
}

export function baseAttrName(attrId: string): string {
  return (
    BASE_ATTR_NAMES[attrId as keyof typeof BASE_ATTR_NAMES] ??
    ATTR_NAMES[attrId] ??
    DOHDOL_BONUS_NAMES[attrId] ??
    attrId
  )
}

export function attrSuffix(attrId: string): string {
  const def = (data.attributeById as Record<string, { valueType: string } | undefined>)[attrId]
  return def?.valueType === 'percent' ? '%' : ''
}

export function slotName(slot: string): string {
  return (
    data.slots.find((s) => s.id === slot)?.name ??
    data.dohdolEquipment.slots.find((s) => s.id === slot)?.name ??
    slot
  )
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
  return data.jobById[jobId]?.name ?? data.dohdolJobById[jobId]?.name ?? jobId
}

export function categoryName(category: string): string {
  return (
    { weapon: '武器', armor: '防具', accessory: '饰品' }[category] ??
    data.dohdolEquipment.categories.find((c) => c.id === category)?.name ??
    category
  )
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
  skillDamageBuff: (pct, seconds) => `技能威力 +${pct}%${durationSuffix(seconds)}`,
  immunity: (pct) => `免疫下 ${Math.round(pct / 100)} 次伤害`,
  doublePowerCharges: (pct) => `接下来 ${Math.round(pct / 100)} 次技能威力翻倍`,
  doubleRewardCharges: (pct) => `接下来 ${Math.round(pct / 100)} 个怪物经验/金币翻倍`,
  mpCostHalveCharges: (pct) => `接下来 ${Math.round(pct / 100)} 次技能魔力消耗减半`,
  cdResetAll: () => '恢复全部技能冷却时间',
  healingBuff: (pct, seconds) => `治疗量 +${pct}%${durationSuffix(seconds)}`,
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

/** 累计时长（秒）→「3天5小时」「5小时12分」「12分34秒」（用于累计在线时长）。 */
export function formatPlaytime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (days > 0) return `${days}天${hours}小时`
  if (hours > 0) return `${hours}小时${minutes}分`
  if (minutes > 0) return `${minutes}分${secs}秒`
  return `${secs}秒`
}
