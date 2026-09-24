import data from '@shared/schema'
import type { GatherNodeDef } from '@shared/schema'

import type {
  ChestRarityLuck,
  CraftOdds,
  CraftOddsSource,
  GameState,
  HeroStats,
  RarityId,
  StatBreakdown,
} from '@/game/types'

/**
 * 「概率 / 数值如何计算」的说明文案。
 *
 * 所有数字都从 `@shared/schema` 的配置读取，公式镜像后端服务（每个函数注释标注对应真源），
 * 避免前端展示与后端结算出现两套数字。
 */
export interface Explain {
  title: string
  /** 该属性的作用（一句话），面板说明气泡的「作用」段。 */
  usage?: string
  lines: string[]
}

const combat = data.combat as Record<string, any>

function pct(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`
}

function pctSmart(value: number): string {
  return pct(value, value > 0 && value < 0.01 ? 2 : 1)
}

function num(value: number, digits = 0): string {
  return value.toFixed(digits)
}

function threeAttrTier(level: number): { levelMin: number; levelMax: number; base: number; denominator: number } {
  const tiers = combat.levelTiers as Array<{ levelMin: number; levelMax: number; base: number; denominator: number }>
  return tiers.find((t) => level >= t.levelMin && level <= t.levelMax) ?? tiers[tiers.length - 1]
}

/** 箱子品阶概率分布。真源：后端 services/loot.py::rarity_weights + rarities.json.boxChance */
export function chestRarityExplain(tier: string, luck: number): Explain {
  const order = data.rarities.order as RarityId[]
  const base = order.map((r) => Number((data.rarities.byId[r].boxChance as Record<string, number>)[tier] ?? 0))
  const weights = order.map((_, i) => base[i] * (1 + luck * i))
  const total = weights.reduce((sum, w) => sum + w, 0) || 1
  return {
    title: '品阶概率如何计算',
    lines: [
      `基础概率：${order.map((r, i) => `${data.rarities.byId[r].name} ${pctSmart(base[i])}`).join(' / ')}`,
      `幸运系数 ${luck.toFixed(3)}（上限 ${data.chests.rarityLuck.luckMax}）：权重 = 基础概率 × (1 + 幸运 × 品阶序号)，普通=0 … 神话=5。`,
      `归一化后即上表概率：${order.map((r, i) => `${data.rarities.byId[r].name} ${pctSmart(weights[i] / total)}`).join(' / ')}`,
      '依据：服务端 loot.rarity_weights()，配置 shared/data/rarities.json 的 boxChance 与 chests.json 的 rarityLuck。',
    ],
  }
}

/** 抽箱品阶「幸运」来源与上限。真源：后端 services/drop_luck.py::chest_rarity_luck + luck_sources.luck_progress + chests.json.rarityLuck */
export function chestLuckExplain(info?: ChestRarityLuck | null): Explain {
  const cfg = data.chests.rarityLuck
  const lines = [
    '幸运进度 p = Σ 权重 × min(当前值 / 参考值, 1)；权重合计 = 1，只有全部来源拉满时 p = 1。',
    `luck 系数 = 上限 ${cfg.luckMax} × p；各来源参考值为其真实最大值（含太古词条），故「上限」只有全来源满才能达到。`,
  ]
  if (info) {
    const max = info.luckMax || 1
    lines.push(`当前 p = ${((info.luck / max) * 100).toFixed(1)}% → luck = ${info.luck.toFixed(3)}`)
    lines.push(...sourceLines(info.sources, CHEST_SOURCE_LABELS))
  } else {
    lines.push(
      ...Object.entries(cfg.sources).map(
        ([key, spec]) =>
          `${CHEST_SOURCE_LABELS[key] ?? key}：权重 ${(spec.weight * 100).toFixed(0)}%，参考值 ${spec.ref}`,
      ),
    )
  }
  lines.push('仅提升箱子的装备品阶抽取概率，不影响金币与经验（金币按地区封顶，无法刷取）。')
  lines.push('依据：服务端 drop_luck.chest_rarity_luck() / luck_sources.luck_progress()，配置 shared/data/chests.json 的 rarityLuck。')
  return { title: '品阶幸运如何计算', lines }
}

/** 保底规则。真源：后端 services/loot.py::draw_rarity + chests.json.pity */
export function pityExplain(): Explain {
  return {
    title: '保底如何触发',
    lines: [
      ...data.chests.pity.map(
        (p) =>
          `连续 ${p.count} 抽未出 ${data.rarities.byId[p.minRarity].name} 及以上 → 下一抽必出 ${data.rarities.byId[p.minRarity].name} 及以上。`,
      ),
      '计数按箱子类型分别累计；抽出对应品阶后该档计数归零。',
      '依据：服务端 loot.draw_rarity()，配置 shared/data/chests.json 的 pity。',
    ],
  }
}

/** 暴击 / 直击 / 信念。真源：后端 services/stats.py::convert_three_attrs + combat.json */
export function threeAttrExplain(
  key: 'critRate' | 'critDamage' | 'dhRate' | 'detBonus',
  level: number,
  value: number,
): Explain {
  const tier = threeAttrTier(level)
  const { base, denominator: denom } = tier
  const detBase = base + Number(combat.detBaseAdjust ?? 0)
  const scale = `等级段 Lv.${tier.levelMin}-${tier.levelMax}：基准 ${base}，缩放分母 ${denom}。`
  const source = '依据：服务端 stats.convert_three_attrs()，配置 shared/data/combat.json。'

  if (key === 'critRate') {
    const rate = Math.max(0, combat.critBaseRatePct + ((value - base) / denom) * combat.critRatePerDenomPct)
    return {
      title: '暴击率如何计算',
      lines: [
        `暴击率 = 基础 ${combat.critBaseRatePct}% + (暴击值 ${num(value)} − 基准 ${base}) / ${denom} × ${combat.critRatePerDenomPct}%`,
        `= ${rate.toFixed(2)}%`,
        scale,
        source,
      ],
    }
  }
  if (key === 'critDamage') {
    const dmg = Math.max(1, combat.critBaseMultiplierPct + ((value - base) / denom) * combat.critDamagePerDenomPct)
    return {
      title: '暴击伤害如何计算',
      lines: [
        `暴击伤害 = 基础 ${combat.critBaseMultiplierPct}% + (暴击值 ${num(value)} − 基准 ${base}) / ${denom} × ${combat.critDamagePerDenomPct}%`,
        `= ${dmg.toFixed(2)}%（暴击时伤害 ×${(dmg / 100).toFixed(3)}）`,
        scale,
        source,
      ],
    }
  }
  if (key === 'dhRate') {
    const rate = Math.max(0, ((value - base) / denom) * combat.directHitRateMaxPct)
    return {
      title: '直击率如何计算',
      lines: [
        `直击率 = (直击值 ${num(value)} − 基准 ${base}) / ${denom} × ${combat.directHitRateMaxPct}%`,
        `= ${rate.toFixed(2)}%（直击时伤害固定 ×${combat.directHitMultiplier}）`,
        scale,
        source,
      ],
    }
  }
  const bonus = Math.max(0, ((value - detBase) / denom) * combat.determinationPerDenomPct)
  return {
    title: '信念增伤如何计算',
    lines: [
      `信念增伤 = (信念值 ${num(value)} − 基准 ${detBase}) / ${denom} × ${combat.determinationPerDenomPct}%`,
      `= ${bonus.toFixed(2)}%（所有伤害恒定乘算，无概率判定）`,
      `信念基准 = 通用基准 ${base} ${combat.detBaseAdjust}（combat.json 的 detBaseAdjust）。`,
      scale,
      source,
    ],
  }
}

/** 闪避。真源：后端 services/stats.py::compute_stats + heroes.json.attributes.dodgePct */
export function dodgeExplain(agility: number, value: number): Explain {
  const spec = (data.heroes as any).attributes.dodgePct
  const dexCoef = Number(spec?.coef?.dex ?? 0)
  return {
    title: '闪避如何计算',
    lines: [
      `基础闪避 = 敏捷 ${num(agility)} × ${dexCoef}% 系数（含等级成长）`,
      `再叠加装备副属性「闪避」与词条加成，最终上限 ${spec?.cap}%。`,
      `当前面板闪避 = ${value.toFixed(2)}%。`,
      '依据：服务端 stats.compute_stats()，配置 shared/data/heroes.json 的 attributes.dodgePct。',
    ],
  }
}

/** 攻击速度 / 技能急速 / 命中率。真源：后端 services/stats.py::compute_stats + heroes.json */
export function heroRateExplain(key: 'attackSpeed' | 'haste' | 'hit', agility: number, value: number): Explain {
  const attrs = (data.heroes as any).attributes
  if (key === 'attackSpeed') {
    const spec = attrs.attackSpeedPct
    return {
      title: '攻击速度如何计算',
      lines: [
        `基础攻速 = 敏捷 ${num(agility)} × ${spec?.coef?.dex ?? 0}%（含等级成长）`,
        `叠加装备「攻速」副属性与词条，上限 ${spec?.cap}%，影响普攻频率。`,
        `当前面板攻速 = ${value.toFixed(2)}%。`,
        '依据：服务端 stats.compute_stats()，配置 shared/data/heroes.json 的 attributes.attackSpeedPct。',
      ],
    }
  }
  if (key === 'hit') {
    const spec = attrs.hitRatePct
    return {
      title: '命中率如何计算',
      lines: [
        `基础命中 = 敏捷 ${num(agility)} × ${spec?.coef?.dex ?? 0}%`,
        `叠加装备「命中」副属性，上限 ${spec?.cap}%；命中率不足时攻击可能 Miss（与直击无关）。`,
        `当前面板命中 = ${value.toFixed(2)}%。`,
        '依据：服务端 stats.compute_stats()，配置 shared/data/heroes.json 的 attributes.hitRatePct。',
      ],
    }
  }
  return {
    title: '技能急速如何计算',
    lines: [
      `技能急速来自装备「技能急速」副属性与冷却缩减词条，无基础值。`,
      `技能实际 CD = 基础 CD × (1 − 冷却缩减 − 技能急速)，最低 0.5 秒，缩减最多 70%。`,
      `当前面板技能急速 = ${value.toFixed(2)}%。`,
      '依据：服务端 stats.skill_cooldown()，配置 shared/data/heroes.json 与 combat.json。',
    ],
  }
}

/** 酒馆资质权重。真源：后端 services/recruiting.py::talent_weights + talents.json.talentWeights */
export function talentExplain(): Explain {
  const weights = data.talents.talentWeights as Record<string, number>
  const order = data.talents.order as RarityId[]
  return {
    title: '资质概率如何计算',
    lines: [
      `每次生成候选按固定权重抽取资质：${order
        .map((r) => `${data.talents.talents[r].name} ${pctSmart(weights[r] ?? 0)}`)
        .join(' / ')}`,
      `「太古属性」概率 ${pct(data.talents.ancientChance, 2)}；带太古属性的英雄必定为神话资质。`,
      '依据：服务端 recruiting.generate_candidate()，配置 shared/data/talents.json 的 talentWeights。',
    ],
  }
}

/** 太古保底。真源：后端 services/recruiting.py::roll_ancient + talents.json.ancientPityCount */
export function ancientPityExplain(count: number, threshold: number): Explain {
  return {
    title: '太古保底如何计算',
    lines: [
      `连续生成 ${threshold} 个候选未出太古时，下一个必定带太古属性。`,
      `常规概率为每个候选 ${pct(data.talents.ancientChance, 2)}；保底与随机取先到者，出太古后计数归零。`,
      `当前进度 ${count} / ${threshold}。`,
      '依据：服务端 recruiting.roll_ancient()，配置 shared/data/talents.json 的 ancientPityCount。',
    ],
  }
}

/** 招募费用。真源：后端 services/recruiting.py::recruit_cost + talents.json */
export function recruitCostExplain(level: number, talent: RarityId, cost: number): Explain {
  const coef = data.talents.talents[talent]?.recruitCoef ?? 1
  return {
    title: '招募费用如何计算',
    lines: [
      `招募费用 = 基础费用 ${data.talents.baseRecruitCost} × 资质系数 × (1 + 当前英雄等级 / 10)`,
      `= ${data.talents.baseRecruitCost} × ${coef}（${data.talents.talents[talent]?.name}）× (1 + ${level} / 10) = ${cost}`,
      '依据：服务端 recruiting.recruit_cost()，配置 shared/data/talents.json。',
    ],
  }
}

/** 特殊鱼（鱼王 / 鱼皇 / 困难鱼）。真源：后端 services/fishing.py::report_fish + fish.json.specials[].intuition */
export function fishChanceExplain(
  region: {
    specials: Array<{
      name: string
      kind: string
      weather?: string[]
      timeOfDay?: string[]
      intuition: { chance: number; requires: Array<{ fishId: string; count: number }> }
    }>
  },
  chanceBonusPct = 0,
): Explain {
  const factor = 1 + chanceBonusPct / 100
  const lines: string[] = [
    '仅在对应「捕鱼人之识」生效期间判定：按稀有度先判困难鱼、再鱼皇、再鱼王，均未命中则为普通鱼。',
  ]
  for (const s of region.specials) {
    const req = s.intuition.requires
      .map((r) => `${data.fishById[r.fishId]?.name ?? r.fishId}×${r.count}`)
      .join('、')
    const gate: string[] = []
    if (s.weather?.length) {
      gate.push(s.weather.map((w) => data.weather.types.find((t) => t.id === w)?.name ?? w).join('/'))
    }
    if (s.timeOfDay?.length) {
      gate.push(s.timeOfDay.map((t) => data.weather.timeOfDayNames[t] ?? t).join('/'))
    }
    lines.push(
      `${s.name}：${pct(s.intuition.chance, 3)} × (1 + 鱼识加成 ${chanceBonusPct.toFixed(0)}%) = ${pct(s.intuition.chance * factor, 3)}` +
        `；前置 ${req}${gate.length ? `；窗口 ${gate.join('、')}` : ''}`,
    )
  }
  lines.push('依据：服务端 fishing.report_fish()，配置 shared/data/fish.json 的 specials[].intuition。')
  return { title: '特殊鱼概率如何计算', lines }
}

/** 抽箱幸运来源 id → 中文名（chests.json.rarityLuck.sources）。 */
const CHEST_SOURCE_LABELS: Record<string, string> = {
  clearedRegions: '通关地区数',
  gearPct: '装备品阶幸运(%)',
  consumablePct: '抽箱品阶概率料理 / 秘药',
  coopClears: '远征通关（难度加权·首通）',
  raidClears: '高难通关（难度加权·首通）',
  egg: '彩蛋英雄被动',
}

/** 制造品阶来源 id → 中文名（recipes.json.rarityScaling.sources）。 */
const CRAFT_SOURCE_LABELS: Record<string, string> = {
  heroLevel: '英雄等级',
  clearedRegions: '通关地区数',
  prodLevel: '生产等级',
  gearPct: '专用装备品阶幸运(%)',
  consumablePct: '制造品阶概率料理 / 秘药',
  coopClears: '远征通关（难度加权·首通）',
  raidClears: '高难通关（难度加权·首通）',
}

/** 来源明细行：当前值 / 参考值 / 达标 / 权重。 */
function sourceLines(sources: CraftOddsSource[], labels: Record<string, string>): string[] {
  const fmtValue = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1))
  return sources.map(
    (s) =>
      `${labels[s.key] ?? s.key}：${fmtValue(s.value)} / ${fmtValue(s.ref)}（达标 ${(s.norm * 100).toFixed(0)}%，权重 ${(s.weight * 100).toFixed(0)}%）`,
  )
}

/**
 * 制造品阶。真源：后端 services/item_factory.py::craft_rarity_luck / craft_rarity_distribution
 * + recipes.json.equipment.rarityScaling。传服务端下发的 craft（含当前来源与最终概率）即展示当前玩家口径。
 */
export function craftRarityExplain(craft?: CraftOdds | null): Explain {
  const scaling = data.recipes.equipment.rarityScaling
  const base = data.recipes.equipment.rarityWeights as Record<string, number>
  const target = scaling.targetWeights as Record<string, number>
  const order = data.rarities.order as RarityId[]
  const nameOf = (r: RarityId) => data.rarities.byId[r].name

  if (!craft) {
    return {
      title: '制造品阶概率如何计算',
      lines: [
        `制造装备的品阶概率随进度提升，基准分布：${order
          .map((r) => `${nameOf(r)} ${pctSmart(base[r] ?? 0)}`)
          .join(' / ')}`,
        `幸运进度 t = Σ 权重 × min(当前值 / 参考值, 1)；权重合计 = 1，只有全部来源拉满时 t = 1 → 神话概率 = ${pct(scaling.mythicCap, 0)}（硬上限）。`,
        '依据：服务端 item_factory.craft_rarity_luck() / craft_rarity_distribution()，配置 shared/data/recipes.json 的 rarityScaling。',
      ],
    }
  }

  const lines = [
    `幸运进度 t = Σ 权重 × min(当前值 / 参考值, 1) = ${(craft.luck * 100).toFixed(1)}%`,
    ...sourceLines(craft.sources, CRAFT_SOURCE_LABELS),
    `分布 = 基准 ×(1 − t) + 目标 × t；全部来源满（t=1）时目标分布：${order
      .map((r) => `${nameOf(r)} ${pctSmart(target[r] ?? 0)}`)
      .join(' / ')}`,
    `当前各品阶概率：${order.map((r) => `${nameOf(r)} ${pctSmart(craft.odds[r] ?? 0)}`).join(' / ')}`,
    `神话概率 ${pctSmart(craft.odds.mythic ?? 0)}，硬上限 ${pct(craft.mythicCap, 0)}（永不超出）。`,
    '制造装备恒为「高品质」：属性区间上移且必带太古词条；「制造品质 +X%」提升稀有 / 太古词条判定。',
    '依据：服务端 item_factory.craft_rarity_luck() / craft_rarity_distribution()，配置 shared/data/recipes.json 的 rarityScaling。',
  ]
  return { title: '制造品阶概率如何计算', lines }
}

/** 附魔词条品质。真源：后端 services/item_factory.py::_roll_quality + economy.json.termQuality */
export function enchantQualityExplain(): Explain {
  const q = data.economy.termQuality
  const lines = [
    `每次附魔，每个词条独立判定品质：普通 ${pct(q.common, 1)} / 稀有 ${pct(q.rare, 1)} / 太古 ${pct(q.ancient, 1)}。`,
    '判定顺序为先太古、后稀有，二者互斥；多个词条可同时出现稀有与太古。',
  ]
  if (!data.economy.debuffQualityEnabled) {
    lines.push('Debuff 不参与稀有 / 太古判定，恒为普通（仅在随机范围内取值）。')
  }
  lines.push('稀有词条数值取该词条范围上限；太古词条数值 = 上限 × 1.25。')
  lines.push(
    `勾选「自动附魔至稀有 / 太古」时，每次消耗为普通附魔的 ${data.economy.enchant.autoUntilRareExtraCostMultiplier} 倍。`,
  )
  lines.push('依据：服务端 item_factory._roll_quality()，配置 shared/data/economy.json 的 termQuality。')
  return { title: '稀有 / 太古词条概率如何计算', lines }
}

/** 制造品质加成。真源：后端 services/item_factory.py::_roll_quality + economy.json.termQuality */
export function craftQualityExplain(bonusFraction: number): Explain {
  const q = data.economy.termQuality
  const bonus = Math.max(0, bonusFraction)
  const rare = q.rare * (1 + bonus)
  const ancient = q.ancient * (1 + bonus * 5)
  return {
    title: '制造品质加成如何计算',
    lines: [
      `制造品质来自专用装备与药水，用于提高稀有 / 太古词条的概率质量。`,
      `稀有词条概率 = 基础 ${pct(q.rare, 1)} × (1 + 制造品质 ${pct(bonus)}) = ${pct(rare, 2)}`,
      `太古词条概率 = 基础 ${pct(q.ancient, 1)} × (1 + 制造品质 × 5) = ${pct(ancient, 2)}`,
      '稀有 + 太古合计不超过 50%；制造装备另恒为「高品质」（属性区间上移、必带太古词条）。',
      '依据：服务端 item_factory._roll_quality()，配置 shared/data/economy.json 的 termQuality。',
    ],
  }
}

/** 采集产出。真源：后端 services/dohdol_util.py::roll_gather_yield + gather-nodes.json */
export function gatherYieldExplain(node: GatherNodeDef | null | undefined): Explain {
  const yields = (node?.yields ?? []).filter((y) => Math.max(0, y.weight) > 0)
  const total = yields.reduce((sum, y) => sum + Math.max(0, y.weight), 0) || 1
  const nameOf = (id: string) => data.materialById[id]?.name ?? id
  return {
    title: '采集产出概率如何计算',
    lines: [
      `每个采集点按权重随机产出一种材料：${yields
        .map((y) => `${nameOf(y.materialId)} ${pctSmart(y.weight / total)}`)
        .join(' / ')}`,
      `数量在 ${yields.map((y) => `${nameOf(y.materialId)} ${y.min}-${y.max}`).join(' / ')} 间随机，并按「产量加成」放大（采集等级每级 +${data.gatherNodes.yieldPerLevelPct}%，上限 +${data.gatherNodes.maxYieldLevelBonusPct}%）。`,
      '依据：服务端 dohdol_util.roll_gather_yield()，配置 shared/data/gather-nodes.json。',
    ],
  }
}

/** 精英怪出现概率。真源：后端 services/regions_util.py::elite_chance + monsters.json.eliteBaseChance */
export function eliteChanceExplain(bonusPct = 0): Explain {
  const base = data.monsters.eliteBaseChance
  const chance = Math.min(1, base + bonusPct / 100)
  return {
    title: '精英怪出现概率如何计算',
    lines: [
      `精英怪概率 = min(100%, 基础 ${pct(base, 1)} + 装备加成 ${bonusPct.toFixed(1)}%) = ${pct(chance, 1)}`,
      '精英怪金币与经验为普通怪的 2 倍。',
      '依据：服务端 regions_util.elite_chance()，配置 shared/data/monsters.json 的 eliteBaseChance。',
    ],
  }
}

/** 副本 BOSS 技能抽取。真源：shared/data/raids.json 的 bossSkillPool / bossSkillIntervalSeconds */
export function raidSkillExplain(poolSize: number): Explain {
  return {
    title: 'BOSS 技能如何选择',
    lines: [
      `BOSS 每 ${data.raids.balance.bossSkillIntervalSeconds} 秒从共享技能池中等概率随机释放 1 个技能。`,
      `当前技能池 ${poolSize} 个，每个被选中的概率 = 1 / ${poolSize} ≈ ${pct(poolSize ? 1 / poolSize : 0, 1)}。`,
      '依据：服务端副本结算，配置 shared/data/raids.json 的 bossSkillPool。',
    ],
  }
}

/** 市场手续费。真源：后端 services/market.py::fee_of + economy.json.market */
export function marketFeeExplain(): Explain {
  const m = data.economy.market
  const sample = 1000
  const fee = Math.floor(sample * m.feePct)
  return {
    title: '市场手续费如何计算',
    lines: [
      `成交时按整单总价抽取 ${pct(m.feePct, 0)} 手续费（向下取整），手续费直接销毁回收。`,
      `卖家实收 = 总价 − floor(总价 × ${pct(m.feePct, 0)})；例：总价 ${sample} → 手续费 ${fee}，卖家实收 ${sample - fee}。`,
      `上架即从背包 / 库存扣除进入托管；未售出 ${m.listingDays} 天自动退回。在售寄售单上限 ${m.maxActiveListings} 个。`,
      '依据：服务端 services/market.fee_of()，配置 shared/data/economy.json 的 market。',
    ],
  }
}

/** 装备词条扩展机制说明（受击 / 条件 / 成长 / 资源转换 / 累计 / 特殊）。真源：combat.json:equipEffects。 */
const EQUIP_EFFECTS = (combat.equipEffects ?? {}) as Record<string, any>

export function equipEffectExplain(stat: string): Explain | null {
  const proc = EQUIP_EFFECTS.proc ?? {}
  const cond = EQUIP_EFFECTS.conditional ?? {}
  const growth = EQUIP_EFFECTS.growth ?? {}
  const charge = EQUIP_EFFECTS.charge ?? {}
  const special = EQUIP_EFFECTS.special ?? {}
  const rows: Record<string, string[]> = {
    bleedProcPct: [`命中时按词条概率触发，${proc.bleed?.durationSec}s 内每秒造成攻击力 ${proc.bleed?.potencyPct}% 的持续伤害（不吃增伤）。`],
    defBreakProcPct: [`命中时按词条概率使目标防御 -${proc.defBreak?.defenseDownPct}%，持续 ${proc.defBreak?.durationSec}s；破防按期望覆盖率计入后端击杀额度模型。`],
    slowProcPct: [`命中时按词条概率使目标攻速 -${proc.slow?.attackSpeedDownPct}%（出手间隔变长），持续 ${proc.slow?.durationSec}s。`],
    stunProcPct: [`命中时按词条概率延长目标下次出手 ${proc.stun?.durationSec}s。`],
    reflectProcPct: [`受到攻击时按词条概率反弹该次伤害的 ${proc.reflect?.damagePct}%。`],
    vengeanceProcPct: [`受到攻击时按词条概率获得攻击 +${proc.vengeance?.attackBuffPct}%，持续 ${proc.vengeance?.durationSec}s。`],
    aegisProcPct: [`受到攻击时按词条概率获得最大生命 ${pct(Number(proc.aegis?.maxHpShieldPct ?? 0), 0)} 的护盾。`],
    resolveProcPct: [`受到攻击时按词条概率恢复 ${pct(Number(proc.resolve?.maxMpRestorePct ?? 0), 0)} 最大魔力。`],
    blockProcPct: ['受到攻击时按词条概率格挡，本次伤害减半。'],
    doubleAttackPct: ['普攻命中有概率追加一次普攻（附加普攻不再连锁触发连击）。'],
    lowHpAttackPct: [`生命低于 ${cond.lowHp?.hpThresholdPct}% 时攻击力提升词条值。`],
    openingDamagePct: [`战斗开始 ${cond.opening?.windowSec}s 内造成的伤害提升词条值。`],
    bossDamagePct: [`对精英与 BOSS 造成的伤害提升词条值（判定目标：${(cond.boss?.kinds ?? []).join(' / ')}）。`],
    lowMpRegenPct: [`魔力低于 ${cond.lowMp?.mpThresholdPct}% 时魔力恢复速度提升词条值。`],
    killStackAttackPct: [`每击杀一名敌人叠加 1 层（最多 ${growth.killStackAttackPct?.maxStacks} 层），每层攻击力提升词条值。`],
    hitStackSpeedPct: [`每次命中叠加 1 层（最多 ${growth.hitStackSpeedPct?.maxStacks} 层），每层攻击速度提升词条值。`],
    skillStackDamagePct: [`每次释放技能叠加 1 层（最多 ${growth.skillStackDamagePct?.maxStacks} 层），每层技能伤害提升词条值。`],
    hpToMpPct: ['每秒将最大生命的一部分（词条值%）转化为魔力，生命不足时不生效。'],
    mpSurgeDamagePct: ['技能伤害额外提升 当前魔力百分比 × 词条值%。'],
    killRestoreMpPct: ['击杀敌人恢复词条值% 的最大魔力。'],
    vitToAttackPct: ['体力值的一部分（词条值%）转化为攻击力。'],
    critToDetPct: ['暴击值的一部分（词条值%）转化为信念值。'],
    executePct: [`目标生命低于 ${special.execute?.hpThresholdPct}% 时对其伤害提升词条值。`],
    cheatDeathPct: ['受到致命伤害时按词条概率免死并保留 1 点生命（每场战斗 1 次）。'],
    reviveChancePct: [`死亡时按词条概率立即复活并回复 ${pct(Number(special.revive?.reviveHpPct ?? 0), 0)} 生命。`],
    chargeBlastPct: [`累计造成目标 ${charge.chargeBlast?.hpThresholdPct}% 最大生命的伤害后触发一次爆发（攻击力 × 词条值%）。`],
    chargeShieldPct: [`累计受到 ${charge.chargeShield?.hpThresholdPct}% 最大生命的伤害后获得护盾（最大生命 × 词条值%）。`],
    chargeHealPct: [`每累计释放 ${charge.chargeHeal?.castThreshold} 次技能恢复 最大生命 × 词条值%。`],
    berserkPct: ['攻击力提升词条值，同时按 cost 比例提高受到的伤害。'],
    glassCannonPct: ['造成的伤害提升词条值，同时按 cost 比例降低最大生命。'],
    recklessPct: ['技能伤害提升词条值，同时按 cost 比例提高受到的伤害。'],
  }
  const lines = rows[stat]
  if (!lines) return null
  return {
    title: '词条机制说明',
    lines: [
      ...lines,
      '触发概率 = 该词条当前数值（见上方数值范围）；效果量与阈值取自 shared/data/combat.json 的 equipEffects。',
      '依据：前端 core/battle.ts 与后端 combat_model.py 同源结算。',
    ],
  }
}

// ------------------------------------------------- 英雄面板属性：逐属性「如何计算 + 作用」

/** 面板属性 key（对应英雄页「面板属性」中的一行）。 */
export type StatKey =
  | 'maxHp'
  | 'maxMp'
  | 'hpRegen'
  | 'mpRegen'
  | 'attack'
  | 'magicAttack'
  | 'physDef'
  | 'magicDef'
  | 'critValue'
  | 'dhValue'
  | 'detValue'
  | 'critRate'
  | 'critDamage'
  | 'dhRate'
  | 'detBonus'
  | 'dodge'
  | 'attackSpeed'
  | 'haste'
  | 'hitRate'
  | 'lifesteal'
  | 'tenacity'
  | 'power'

/** `statExplain` 的上下文：拆解来自 `/game/state.statBreakdown`。 */
export interface StatExplainContext {
  breakdown?: StatBreakdown | null
  stats?: HeroStats | null
  hero?: { level?: number; agility?: number } | null
  powerAudit?: GameState['powerAudit']
}

const ATTR_LABEL: Record<string, string> = { str: '力量', dex: '敏捷', int: '智力', vit: '体力' }

/** base + Σ(coef × 核心属性总量)：有拆解时代入真实数值，否则退化为公式模板。 */
function coreFormula(coef: Record<string, number>, base: number, core: Record<string, number> | null): string {
  const terms = Object.entries(coef)
    .filter(([, c]) => c !== 0)
    .map(([a, c]) => (core ? `${num(c)} × ${ATTR_LABEL[a] ?? a} ${num(core[a] ?? 0)}` : `${num(c)} × ${ATTR_LABEL[a] ?? a}`))
  return [base ? num(base) : '', ...terms].filter(Boolean).join(' + ') || '0'
}

/** 按职业主属性过滤系数（镜像后端 `_resolve_coef`：byJobMainAttr 时只保留主属性项）。 */
function resolveCoef(coef: Record<string, number>, mainAttr: string | null, byJob: boolean): Record<string, number> {
  if (!byJob || !mainAttr) return { ...coef }
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(coef)) if (k === mainAttr) out[k] = v
  return out
}

/** 词条加成段：`攻击 +12% + 狂暴 +5%`；无则返回空串。 */
function modsText(mods: Record<string, number>, entries: Array<[string, string]>): string {
  return entries
    .filter(([stat]) => (mods[stat] ?? 0) !== 0)
    .map(([stat, label]) => `${label} +${num(mods[stat] ?? 0, 1)}%`)
    .join('、')
}

const RATE_USAGE: Record<string, string> = {
  critRate: '命中时触发暴击的概率。',
  critDamage: '暴击时造成的伤害倍率。',
  dhRate: '命中时触发直击的概率（直击伤害固定 ×1.25）。',
  detBonus: '对所有伤害的恒定乘算增伤，无概率判定。',
  dodge: '概率完全规避来袭攻击，使其不造成伤害。',
  attackSpeed: '提高普攻出手频率（也缩短技能公共冷却）。',
  haste: '缩短技能的实际冷却时间。',
  hitRate: '降低攻击被目标闪避（Miss）的概率。',
}

const LIFESTEAL_USAGE = '造成伤害时按比例回复自身生命。'
const TENACITY_USAGE = '按比例减少自身受到的伤害。'

function rateExplainFor(key: StatKey, level: number, agility: number, stats: HeroStats | null): Explain | null {
  const crit = stats?.critValue ?? 0
  const dh = stats?.dhValue ?? 0
  const det = stats?.detValue ?? 0
  switch (key) {
    case 'critRate':
      return threeAttrExplain('critRate', level, crit)
    case 'critDamage':
      return threeAttrExplain('critDamage', level, crit)
    case 'dhRate':
      return threeAttrExplain('dhRate', level, dh)
    case 'detBonus':
      return threeAttrExplain('detBonus', level, det)
    case 'dodge':
      return dodgeExplain(agility, stats?.dodgePct ?? 0)
    case 'attackSpeed':
      return heroRateExplain('attackSpeed', agility, stats?.attackSpeedPct ?? 0)
    case 'haste':
      return heroRateExplain('haste', agility, stats?.hastePct ?? 0)
    case 'hitRate':
      return heroRateExplain('hit', agility, stats?.hitRatePct ?? 0)
    default:
      return null
  }
}

/**
 * 面板属性「作用 + 如何计算」。数值一律取自后端下发的 `statBreakdown`（与结算同源），
 * 公式结构取自 `shared/data/heroes.json` / `combat.json`（镜像 `services/stats.py::compute_stats`）。
 */
export function statExplain(key: StatKey, ctx: StatExplainContext): Explain {
  const b = ctx.breakdown ?? null
  const s = ctx.stats ?? null
  const hero = ctx.hero ?? null
  const attrs = (data.heroes as any).attributes as Record<string, any>
  const level = b?.level ?? hero?.level ?? 1
  const agility = hero?.agility ?? 0
  const core = b?.core.total ?? null
  const lg = b?.levelGrowth ?? {}
  const ef = b?.equipFlat ?? {}
  const subs = b?.subs ?? {}
  const mods = b?.termMods ?? s?.termMods ?? {}
  const mainAttr = b?.mainAttr ?? s?.mainAttr ?? null
  const note = b ? null : '（拆解数据未就绪，数值以面板为准）'

  const finish = (title: string, usage: string, lines: string[]): Explain => ({
    title,
    usage,
    lines: [...lines.filter(Boolean), ...(note ? [note] : [])],
  })

  const rate = rateExplainFor(key, level, agility, s)
  if (rate) {
    return {
      ...rate,
      usage: RATE_USAGE[key],
      lines: [...rate.lines, ...(note ? [note] : [])],
    }
  }

  // 三属性原始值（暴击 / 直击 / 信念）：装备副属性 → 词条 → 主属性联动。
  const link = (data.combat as any).primaryLink?.[b?.bias ?? ''] ?? {}
  if (key === 'critValue' || key === 'dhValue' || key === 'detValue') {
    const map = {
      critValue: { sub: subs.crit, stat: 'critStatPct', label: '暴击', linkKey: 'crit', field: 'critValue', value: s?.critValue },
      dhValue: { sub: subs.dh, stat: 'dhStatPct', label: '直击', linkKey: 'dh', field: 'dhValue', value: s?.dhValue },
      detValue: { sub: subs.det, stat: 'detStatPct', label: '信念', linkKey: 'det', field: 'detValue', value: s?.detValue },
    }[key]
    const lines = [`装备 / 魔晶石「${map.label}」副属性 ${num(map.sub ?? 0)}`]
    if (mods[map.stat]) lines.push(`× (1 + ${map.label}值加成 ${num(mods[map.stat], 1)}%)`)
    if (link[map.linkKey]) lines.push(`× (1 + 主属性联动 ${num(link[map.linkKey] * 100, 1)}%)`)
    if (key === 'detValue' && mods.critToDetPct)
      lines.push(`+ 暴击转化：暴击值 ${num(s?.critValue ?? 0)} × ${num(mods.critToDetPct, 1)}%`)
    lines.push(`= ${num(map.value ?? 0)}`)
    const usage = {
      critValue: '换算暴击率与暴击伤害的原始值（越高越好）。',
      dhValue: '换算直击率的原始值（直击伤害固定 ×1.25）。',
      detValue: '换算全伤害恒定增伤的原始值。',
    }[key]
    return finish(`${map.label}值如何计算`, usage, lines)
  }

  if (key === 'maxHp') {
    const spec = attrs.maxHp
    return finish('生命值如何计算', '承受伤害的耐久度，归零即阵亡。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      lg.maxHp ? `等级成长 +${num(lg.maxHp)}（每级按自身三维 × 资质系数 ${num(b?.growthCoef ?? 0, 2)}）` : '',
      ef.hp ? `装备生命 +${num(ef.hp)}` : '',
      `生命加成词条：${modsText(mods, [['maxHpPct', '生命']]) || '无'}`,
      `= ${num(s?.maxHp ?? 0)}`,
    ])
  }

  if (key === 'maxMp') {
    const spec = attrs.maxMp
    return finish('魔法值如何计算', '释放技能的消耗资源；不足时只能普攻（普攻会回复少量魔法值）。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      lg.maxMp ? `等级成长 +${num(lg.maxMp)}` : '',
      `魔法加成词条：${modsText(mods, [['maxMpPct', '魔法']]) || '无'}`,
      `= ${num(s?.maxMp ?? 0)}`,
    ])
  }

  if (key === 'hpRegen') {
    const spec = attrs.hpRegen
    return finish('生命回复如何计算', '每秒自动回复的生命值。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      `装备 / 魔晶石回复 +${num(subs.regen ?? 0)}`,
      mods.hpRegenPct ? `× (1 + 回复加成 ${num(mods.hpRegenPct, 1)}%)` : '',
      `= ${num(s?.hpRegen ?? 0)} / 秒`,
    ])
  }

  if (key === 'mpRegen') {
    const spec = attrs.mpRegen
    return finish('魔力回复如何计算', '每秒自动回复的魔法值（技能续航的基础）。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      lg.mpRegen ? `等级成长 +${num(lg.mpRegen)}` : '',
      mods.mpRegenPct ? `× (1 + 回复加成 ${num(mods.mpRegenPct, 1)}%)，最低 0` : '',
      `= ${num(s?.mpRegen ?? 0)} / 秒`,
    ])
  }

  if (key === 'attack') {
    const spec = attrs.attack
    const coef = resolveCoef(spec.coef, mainAttr, Boolean(spec.byJobMainAttr))
    return finish('物理攻击如何计算', '物理职业普攻与技能的基础伤害来源。', [
      `面板基础 = ${coreFormula(coef, Number(spec.base ?? 0), core)}（仅计入职业主属性 ${ATTR_LABEL[mainAttr ?? ''] ?? '—'}）`,
      lg.attack ? `等级成长 +${num(lg.attack)}` : '',
      ef.attack ? `装备攻击 +${num(ef.attack)}` : '',
      `攻击加成词条：${modsText(mods, [['attackPct', '攻击'], ['berserkPct', '狂暴']]) || '无'}`,
      mods.vitToAttackPct ? `+ 体力转化：体力 ${num(core?.vit ?? 0)} × ${num(mods.vitToAttackPct, 1)}%` : '',
      `= ${num(s?.attack ?? 0)}`,
    ])
  }

  if (key === 'magicAttack') {
    const spec = attrs.magicAttack
    return finish('魔法攻击如何计算', '智力系职业普攻与技能的基础伤害来源。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      lg.magicAttack ? `等级成长 +${num(lg.magicAttack)}` : '',
      ef.magicAttack ? `装备魔攻 +${num(ef.magicAttack)}` : '',
      `× (1 + 攻击词条 ${num((mods.attackPct ?? 0) + (mods.berserkPct ?? 0), 1)}%)` +
        (mods.magicAttackPct ? ` × (1 + 魔攻词条 ${num(mods.magicAttackPct, 1)}%)` : ''),
      `= ${num(s?.magicAttack ?? 0)}`,
    ])
  }

  if (key === 'physDef') {
    const spec = attrs.physDef
    return finish('物理防御如何计算', '按比例减少受到的物理伤害。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      ef.physDef ? `装备物防 +${num(ef.physDef)}` : '',
      `物防加成词条：${modsText(mods, [['physDefPct', '物防']]) || '无'}`,
      `= ${num(s?.physDef ?? 0)}`,
    ])
  }

  if (key === 'magicDef') {
    const spec = attrs.magicDef
    return finish('魔法防御如何计算', '按比例减少受到的魔法伤害。', [
      `面板基础 = ${coreFormula(spec.coef, Number(spec.base ?? 0), core)}`,
      ef.magicDef ? `装备魔防 +${num(ef.magicDef)}` : '',
      `魔防加成词条：${modsText(mods, [['magicDefPct', '魔防']]) || '无'}`,
      `= ${num(s?.magicDef ?? 0)}`,
    ])
  }

  if (key === 'lifesteal') {
    return finish('吸血如何计算', LIFESTEAL_USAGE, [
      `装备 / 魔晶石「吸血」 ${num(subs.lifesteal ?? 0, 1)}%`,
      `+ 吸血词条 ${num(mods.lifestealPct ?? 0, 1)}%，无基础值`,
      `= ${num(s?.lifestealPct ?? 0, 1)}%`,
    ])
  }

  if (key === 'tenacity') {
    return finish('坚韧如何计算', TENACITY_USAGE, [
      `装备 / 魔晶石「坚韧」 ${num(subs.tenacity ?? 0, 1)}%`,
      `+ 守护词条 ${num(mods.guardPct ?? 0, 1)}%，无基础值`,
      `= ${num(s?.tenacityPct ?? 0, 1)}%`,
    ])
  }

  // key === 'power'
  const audit = ctx.powerAudit
  const groups = audit?.groups ?? { offense: 0, defense: 0, sustain: 0 }
  return finish('战力如何计算', '综合衡量英雄强度的分项加权分（进攻 / 防御 / 续航）。', [
    '战力 = Σ(各属性「软上限递减」后的有效值 × 权重)，分进攻 / 防御 / 续航三组求和。',
    '有效值 = 上限 × (1 − e^(−原始值 / 上限))：数值越高，边际收益越低。',
    '时长与重复次数类效果不计入战力。',
    `当前：进攻 ${Math.floor(groups.offense ?? 0)} + 防御 ${Math.floor(groups.defense ?? 0)} + 续航 ${Math.floor(groups.sustain ?? 0)}`,
  ])
}
