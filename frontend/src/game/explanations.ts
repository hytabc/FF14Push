import data from '@shared/schema'
import type { GatherNodeDef } from '@shared/schema'

import type { CraftOdds, RarityId } from '@/game/types'

/**
 * 「概率 / 数值如何计算」的说明文案。
 *
 * 所有数字都从 `@shared/schema` 的配置读取，公式镜像后端服务（每个函数注释标注对应真源），
 * 避免前端展示与后端结算出现两套数字。
 */
export interface Explain {
  title: string
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
      `爆率加成 ${luck.toFixed(3)}：权重 = 基础概率 × (1 + 爆率加成 × 品阶序号)，普通=0 … 神话=5。`,
      `归一化后即上表概率：${order.map((r, i) => `${data.rarities.byId[r].name} ${pctSmart(weights[i] / total)}`).join(' / ')}`,
      '依据：服务端 loot.rarity_weights()，配置 shared/data/rarities.json 的 boxChance。',
    ],
  }
}

/** 品阶爆率倍率。真源：后端 services/loot.py::drop_rate_multiplier + chests.json.dropRate */
export function chestLuckExplain(multiplier: number, clearedRegions: number): Explain {
  const cfg = data.chests.dropRate
  return {
    title: '品阶爆率倍率如何计算',
    lines: [
      `倍率 = min(上限 ${cfg.maxMultiplier}, 1 + 每地区加成 ${cfg.perClearedRegion} × 已通关地区数)`,
      `= min(${cfg.maxMultiplier}, 1 + ${cfg.perClearedRegion} × ${clearedRegions}) = ${multiplier.toFixed(3)}`,
      '仅提升箱子的装备品阶抽取概率，不影响金币与经验（金币按地区封顶，无法刷取）。',
      '依据：服务端 loot.drop_rate_multiplier()，配置 shared/data/chests.json 的 dropRate。',
    ],
  }
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

/** 鱼王 / 鱼皇。真源：后端 services/fishing.py::report_fish + fish.json.king/emperor.chance */
export function fishChanceExplain(region: {
  king: { name: string; chance: number; prereqFishIds: string[] }
  emperor: { name: string; chance: number; prereqFishIds: string[] }
}, chanceBonusPct = 0): Explain {
  const factor = 1 + chanceBonusPct / 100
  return {
    title: '鱼王 / 鱼皇概率如何计算',
    lines: [
      '仅在「捕鱼人之识」生效期间判定：先判鱼王、再判鱼皇，都未命中则为普通鱼。',
      `鱼王 ${region.king.name}：${pct(region.king.chance, 1)} × (1 + 鱼识加成 ${chanceBonusPct.toFixed(0)}%) = ${pct(region.king.chance * factor, 2)}`,
      `鱼皇 ${region.emperor.name}：${pct(region.emperor.chance, 1)} × (1 + 鱼识加成 ${chanceBonusPct.toFixed(0)}%) = ${pct(region.emperor.chance * factor, 2)}`,
      `前置普通鱼：鱼王需 ${region.king.prereqFishIds.length} 种、鱼皇需 ${region.emperor.prereqFishIds.length} 种。`,
      '依据：服务端 fishing.report_fish()，配置 shared/data/fish.json 的 king / emperor.chance。',
    ],
  }
}

const CRAFT_SOURCE_LABELS: Record<string, string> = {
  heroLevel: '英雄等级',
  clearedRegions: '通关地区数',
  prodLevel: '生产等级',
  gearPct: '专用装备品阶幸运(%)',
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
  const fmtValue = (v: number) => (Number.isInteger(v) ? v.toFixed(0) : v.toFixed(1))

  if (!craft) {
    return {
      title: '制造品阶概率如何计算',
      lines: [
        `制造装备的品阶概率随进度提升，基准分布：${order
          .map((r) => `${nameOf(r)} ${pctSmart(base[r] ?? 0)}`)
          .join(' / ')}`,
        `四项来源（英雄等级 / 通关地区数 / 生产等级 / 专用装备品阶幸运）全部拉满时，神话概率 = ${pct(scaling.mythicCap, 0)}（硬上限）。`,
        '依据：服务端 item_factory.craft_rarity_luck() / craft_rarity_distribution()，配置 shared/data/recipes.json 的 rarityScaling。',
      ],
    }
  }

  const lines = [
    `幸运进度 t = Σ 权重 × min(当前值 / 参考值, 1) = ${(craft.luck * 100).toFixed(1)}%`,
    ...craft.sources.map(
      (s) =>
        `${CRAFT_SOURCE_LABELS[s.key] ?? s.key}：${fmtValue(s.value)} / ${fmtValue(s.ref)}（达标 ${(s.norm * 100).toFixed(0)}%，权重 ${(s.weight * 100).toFixed(0)}%）`,
    ),
    `分布 = 基准 ×(1 − t) + 目标 × t；四项全满（t=1）时目标分布：${order
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
