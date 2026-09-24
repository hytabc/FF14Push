/**
 * 前后端共享的数据契约与加载器（TypeScript 端）。
 * `../data/*.json` 是唯一事实来源，后端 `loader.py` 读取同一批文件。
 */
import raritiesJson from '../data/rarities.json'
import slotsJson from '../data/slots.json'
import subAttributesJson from '../data/sub-attributes.json'
import termsJson from '../data/terms.json'
import jobsJson from '../data/jobs.json'
import baseItemsJson from '../data/base-items.json'
import exclusiveEquipmentJson from '../data/exclusive-equipment.json'
import worldbossJson from '../data/worldboss.json'
import monstersJson from '../data/monsters.json'
import bossesJson from '../data/bosses.json'
import regionsJson from '../data/regions.json'
import raidsJson from '../data/raids.json'
import chestsJson from '../data/chests.json'
import craftingJson from '../data/crafting.json'
import economyJson from '../data/economy.json'
import talentsJson from '../data/talents.json'
import heroesJson from '../data/heroes.json'
import combatJson from '../data/combat.json'
import tutorialJson from '../data/tutorial.json'
import tagsJson from '../data/tags.json'
import dohdolJobsJson from '../data/dohdol-jobs.json'
import dohdolLevelsJson from '../data/dohdol-levels.json'
import materialsJson from '../data/materials.json'
import gatherNodesJson from '../data/gather-nodes.json'
import dohdolEquipmentJson from '../data/dohdol-equipment.json'
import fishJson from '../data/fish.json'
import recipesJson from '../data/recipes.json'
import consumablesJson from '../data/consumables.json'
import titlesJson from '../data/titles.json'
import eggHeroesJson from '../data/egg-heroes.json'

export type RarityId = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'mythic'
export type Category = 'weapon' | 'armor' | 'accessory'
export type SlotId =
  | 'mainHand' | 'head' | 'body' | 'hands' | 'legs' | 'feet'
  | 'necklace' | 'earring' | 'bracelet' | 'ring1' | 'ring2'
export type AttrId =
  | 'str' | 'dex' | 'int' | 'vit' | 'crit' | 'dh' | 'det'
  | 'sks' | 'sps' | 'regen' | 'lifesteal' | 'dodge' | 'acc' | 'tenacity'
export type BaseAttrId = 'attack' | 'magicAttack' | 'physDef' | 'magicDef' | 'hp'
export type TermQuality = 'common' | 'rare' | 'ancient'
export type JobRole = 'tank' | 'healer' | 'melee' | 'physicalRanged' | 'magicalRanged'

export interface Rarity {
  id: RarityId
  name: string
  color: string
  hex: string
  multiplier: number
  termMin: number
  termMax: number
  subAttrMin: number
  subAttrMax: number
  debuffChance: number
  boxChance: { normal: number; advanced: number }
  sellCoef: number
  refineCost: number
  enchantCost: number
  tier: number
}

export interface SlotDef {
  id: SlotId
  name: string
  category: Category
  accepts: string[]
  order: number
}

export type TagColorId = keyof typeof tagsJson.colors

export interface TagColorDef {
  id: string
  name: string
  hex: string
}

/** 标签颜色调色板顺序（id 列表）。 */
export const TAG_COLOR_ORDER = tagsJson.order as TagColorId[]

export interface AttributeDef {
  id: AttrId
  name: string
  valueType: 'flat' | 'percent'
  role: 'primary' | 'offensive' | 'utility'
  sellsWeight: number
  rarityCoef: number
  ranges: Record<RarityId, [number, number]>
  desc?: string
}

/** 词条副作用（风险代价类）：落库时 value = round(主值 × ratio)，累加进 term_mods[stat]。 */
export interface TermCostDef {
  stat: string
  ratio: number
}

export interface TermDef {
  id: string
  name: string
  /** 词条类别（见 terms.json:categories）：attribute/onAttack/abnormal/... */
  category: string
  type: 'buff' | 'debuff'
  trigger: string
  stat: string
  range: [number, number]
  slots?: SlotId[]
  /** 风险代价类词条的副作用；desc 中的 {c} 为折算后的副作用值。 */
  cost?: TermCostDef
  desc: string
}

/** 生产/采集专用装备词条（slots 为专用栏位，stat 为生产加成键）。 */
export interface ProductionTermDef {
  id: string
  name: string
  category: string
  type: 'buff' | 'debuff'
  trigger: string
  stat: string
  range: [number, number]
  slots: string[]
  desc: string
}

/** 词条类别名表（id → 中文名）。 */
export interface TermCategoryDef {
  id: string
  name: string
}

export interface SkillEffect {
  type: string
  value?: number
  duration?: number
  maxPotency?: number
}

export interface SkillDef {
  id: string
  name: string
  cd: number
  mpCost: number
  potency: number
  damageType: 'physical' | 'magical'
  target: 'single' | 'aoe' | 'self'
  priority: 1 | 2 | 3
  effects: SkillEffect[]
}

export interface JobDef {
  id: string
  name: string
  enName: string
  role: JobRole
  weaponType: string
  mainAttr: 'str' | 'dex' | 'int'
  skills: SkillDef[]
}

export interface BaseAttrEntry {
  attr: BaseAttrId | AttrId
  base: number
}

export interface BaseItem {
  id: string
  name: string
  category: Category
  slot: SlotId
  weaponType?: string
  jobId?: string
  levelReq: number
  tierIndex: number
  tierName: string
  /** 副属性按档位缩放的系数（= levelReq / 95），生成装备时乘以副属性区间。 */
  tierScale: number
  baseAttrs: BaseAttrEntry[]
  subAttrPool: AttrId[]
  /** 变体 id（同档多套底材）。空串表示「基础型」，沿用 w_/a_/c_ 前缀 + 族 + 档位的旧 id。 */
  variantId?: string
  /** 世界BOSS 专属系列（绝境龙神）：不进入抽箱/合成/生产候选池，仅世界BOSS 掉落。 */
  exclusive?: boolean
}

export interface MonsterTemplate {
  id: string
  name: string
  examples: string[]
  multipliers: { hp: number; attack: number; defense: number; attackSpeed: number }
  goldMultiplier: number
  xpMultiplier: number
}

export interface RegionDef {
  id: number
  name: string
  chapter: number
  levelMin: number
  levelMax: number
  killsRequired: number
  baseGold: number
  spawnInterval: number
  bossName: string
  bossType: string
}

export interface RaidBossDef {
  id: string
  name: string
  type: string
  hpMultiplier: number
  attackMultiplier: number
  defenseMultiplier: number
  attackInterval: number
  resistancePct: number
}

export interface RaidEnrageDef {
  attackMultiplier: number
  damageReductionPct: number
  attackSpeedBonusPct: number
}

export interface RaidDef {
  id: string
  order: number
  name: string
  difficulty?: 'normal' | 'hard'
  /** 进入等级下限（普通副本为推荐值，绝* 为硬门槛）。 */
  requiredLevel: number
  /** 目标等级：BOSS 数值固定按此等级锚定，低于它会被等级压制。 */
  challengeLevel?: number
  /** 每个账号每天可获得奖励的通关次数（首通计入）。 */
  dailyRewardClears?: number
  requiredPower: number
  requiresAllSlots: boolean
  enrage: RaidEnrageDef | null
  bosses: RaidBossDef[]
  reward: {
    firstGold: number
    firstExp: number
    repeatGold: number
    repeatExp: number
    boxCount: number
    /** 普通副本：通关直接发放的宝箱；高难副本用 boxTier + slotChoice 自选装备种类。 */
    chestId?: string
    boxTier?: string
    slotChoice?: boolean
  }
}

export interface ChestDef {
  id: string
  name: string
  price: number
  category: Category
  tier: 'normal' | 'advanced'
  icon: string
}

export interface ChestPity {
  count: number
  minRarity: RarityId
}

export interface TalentDef {
  id: string
  name: string
  pointMin: number
  pointMax: number
  growthCoef: number
  recruitCoef: number
}

export interface TalentBias {
  id: string
  name: string
  weights: Record<'str' | 'dex' | 'int', number>
}

export interface EggHeroPassive {
  type: string
  value: number
}

export interface EggHeroDef {
  id: string
  name: string
  talent: RarityId
  attrBias: 'str' | 'dex' | 'int' | 'balanced'
  jobId: string | null
  replaceSkills: boolean
  skills: SkillDef[]
  passive?: EggHeroPassive
  /** 展示用说明文案 */
  desc?: string
}

export interface EggHeroesConfig {
  eggChance: number
  heroes: EggHeroDef[]
  byId: Record<string, EggHeroDef>
}

export interface BossTypeDef {
  id: string
  name: string
  skills: Array<Record<string, unknown> & { id: string; name: string; cd: number; desc: string }>
}

export interface TutorialStep {
  step: number
  key: string
  title: string
  action: string
  text: string
}

export type DohDolJobKind = 'doh' | 'dol'
export type DohDolCategory = 'doh_tool' | 'doh_gear' | 'dol_tool' | 'dol_gear'
export type MaterialKind = 'gather' | 'half' | 'fish'

export interface DohDolJobDef {
  id: string
  name: string
  enName: string
  kind: DohDolJobKind
  role: string
}

export interface MaterialDef {
  id: string
  name: string
  kind: MaterialKind
  jobId?: string
  regionId?: number
  tier?: number
  /** 出售单价（金币）；材料/鱼获可卖给系统。 */
  sell?: number
}

export interface GatherYield {
  materialId: string
  weight: number
  min: number
  max: number
}

export interface GatherNodeDef {
  regionId: number
  jobId: string
  levelReq: number
  yields: GatherYield[]
}

export interface DohDolSlotDef {
  id: string
  name: string
  category: DohDolCategory
  order: number
}

export interface DohDolItemDef {
  id: string
  name: string
  category: DohDolCategory
  slot: string
  kind: DohDolJobKind
  tierIndex: number
  levelReq: number
  bonus: Record<string, number>
}

export interface FishDef {
  id: string
  name: string
  weight?: number
  sizeMin: number
  sizeMax: number
  exp: number
  sell?: number
}

export interface KingFishDef {
  id: string
  name: string
  prereqFishIds: string[]
  insightSeconds: [number, number]
  chance: number
  sizeMin: number
  sizeMax: number
  exp: number
  sell?: number
}

export interface FishRegionDef {
  regionId: number
  name: string
  levelReq: number
  normal: FishDef[]
  king: KingFishDef
  emperor: KingFishDef
}

export interface RecipeInput {
  itemId: string
  count: number
}

export interface RecipeOutput {
  kind: 'material' | 'equipment' | 'consumable'
  itemId?: string
  baseId?: string
  count?: number
}

export interface RecipeDef {
  id: string
  jobId: string
  requiredLevel: number
  craftSeconds: number
  xp: number
  inputs: RecipeInput[]
  output: RecipeOutput
}

export interface ConsumableEffect {
  stat: string
  value: number
}

export interface ConsumableDef {
  id: string
  name: string
  kind: 'potion' | 'food'
  effects: ConsumableEffect[]
  desc: string
  sell?: number
}

export interface TitleDef {
  id: string
  name: string
  desc: string
  condition: { type: string }
}

const raritiesData = raritiesJson as unknown as {
  order: RarityId[]
  rarities: Record<RarityId, Rarity>
}

const slotsData = slotsJson as unknown as {
  slots: SlotDef[]
  categories: Record<Category, { id: Category; name: string; slotIds: SlotId[] }>
}

const subAttrData = subAttributesJson as unknown as {
  attributes: AttributeDef[]
  baseAttributes: Array<{ id: BaseAttrId; name: string }>
}

const termsData = termsJson as unknown as {
  qualityChances: Record<TermQuality, number>
  qualityRules: Record<TermQuality, { name: string; valueRule: string; border: string; sellValue: number }>
  debuffValue: Record<TermQuality, number>
  categories: TermCategoryDef[]
  terms: TermDef[]
}

const jobsData = jobsJson as unknown as {
  gcd: number
  maxSkills: number
  skillPriorityOrder: number[]
  roles: Record<JobRole, { id: JobRole; name: string }>
  jobs: JobDef[]
}

interface BaseItemVariant {
  id: string
  name: string
  minTier: number
  pool?: AttrId[]
  subAttrScale?: number
  baseAttr?: AttrId
}

const baseItemsDataRaw = baseItemsJson as unknown as {
  tiers: Array<{ index: number; name: string; levelReq: number; weaponAttack: number; defense: number; hp: number; mainAttr: number; subAttrScale: number }>
  subAttrPools: Record<string, AttrId[]>
  variants?: { weapon?: BaseItemVariant[]; armor?: BaseItemVariant[]; accessory?: BaseItemVariant[] }
  baseAttrFloat: number
  subAttrFloat: number
  weaponFamilies: Array<{ weaponType: string; jobId: string; suffix: string; pool: string }>
  armorFamilies: Array<{ slot: SlotId; suffix: string; baseAttrs: Array<{ attr: BaseAttrId; ratio: number }> }>
  accessoryFamilies: Array<{ slot: SlotId; suffix: string; baseAttr: AttrId; pool: string }>
}

/** 未定义 variants 时的兜底「基础型」变体。 */
const BASE_VARIANT: BaseItemVariant = { id: '', name: '', minTier: 0, subAttrScale: 1 }

/** 变体的副属性池：与族自身池求交后取用；交集为空则退回族自身池（基础型 pool 为空即此意）。 */
function variantPool(variant: BaseItemVariant, basePool: AttrId[]): AttrId[] {
  const wanted = (variant.pool ?? []).filter((a) => basePool.includes(a))
  return wanted.length ? wanted : [...basePool]
}

function variantIdSuffix(variant: BaseItemVariant): string {
  return variant.id ? `_${variant.id}` : ''
}

/** 基础属性 ID 到中文名 */
export const BASE_ATTR_NAMES: Record<BaseAttrId, string> = Object.fromEntries(
  subAttrData.baseAttributes.map((a) => [a.id, a.name]),
) as Record<BaseAttrId, string>

export const ATTR_NAMES: Record<string, string> = Object.fromEntries(
  subAttrData.attributes.map((a) => [a.id, a.name]),
)

/** 展开底材：武器/防具/饰品族 × 档位 × 变体（minTier ≤ 档位）。exclusive=true 时标记为世界BOSS 专属系列。 */
export function expandBaseItems(
  d: typeof baseItemsDataRaw = baseItemsDataRaw,
  exclusive = false,
): BaseItem[] {
  const jobMainAttr = new Map(jobsData.jobs.map((j) => [j.id, j.mainAttr]))
  const weaponVariants = d.variants?.weapon ?? [BASE_VARIANT]
  const armorVariants = d.variants?.armor ?? [BASE_VARIANT]
  const accessoryVariants = d.variants?.accessory ?? [BASE_VARIANT]
  const out: BaseItem[] = []

  for (const fam of d.weaponFamilies) {
    const isMagical = jobMainAttr.get(fam.jobId) === 'int'
    const basePool = d.subAttrPools[fam.pool]
    for (const t of d.tiers) {
      for (const v of weaponVariants) {
        if (v.minTier > t.index) continue
        out.push({
          id: `w_${fam.weaponType}${variantIdSuffix(v)}_${t.index}`,
          name: `${t.name}${v.name}${fam.suffix}`,
          category: 'weapon',
          slot: 'mainHand',
          weaponType: fam.weaponType,
          jobId: fam.jobId,
          levelReq: t.levelReq,
          tierIndex: t.index,
          tierName: t.name,
          tierScale: t.subAttrScale * (v.subAttrScale ?? 1),
          baseAttrs: [{ attr: isMagical ? 'magicAttack' : 'attack', base: t.weaponAttack }],
          subAttrPool: variantPool(v, basePool),
          variantId: v.id,
        })
      }
    }
  }

  for (const fam of d.armorFamilies) {
    const basePool = d.subAttrPools.armor
    for (const t of d.tiers) {
      for (const v of armorVariants) {
        if (v.minTier > t.index) continue
        out.push({
          id: `a_${fam.slot}${variantIdSuffix(v)}_${t.index}`,
          name: `${t.name}${v.name}${fam.suffix}`,
          category: 'armor',
          slot: fam.slot,
          levelReq: t.levelReq,
          tierIndex: t.index,
          tierName: t.name,
          tierScale: t.subAttrScale * (v.subAttrScale ?? 1),
          baseAttrs: fam.baseAttrs.map((b) => ({
            attr: b.attr,
            base: b.attr === 'hp' ? t.hp * b.ratio : t.defense * b.ratio,
          })),
          subAttrPool: variantPool(v, basePool),
          variantId: v.id,
        })
      }
    }
  }

  for (const fam of d.accessoryFamilies) {
    const basePool = d.subAttrPools[fam.pool]
    for (const t of d.tiers) {
      for (const v of accessoryVariants) {
        if (v.minTier > t.index) continue
        out.push({
          id: `c_${fam.slot}${variantIdSuffix(v)}_${t.index}`,
          name: `${t.name}${v.name}${fam.suffix}`,
          category: 'accessory',
          slot: fam.slot,
          levelReq: t.levelReq,
          tierIndex: t.index,
          tierName: t.name,
          tierScale: t.subAttrScale * (v.subAttrScale ?? 1),
          baseAttrs: [{ attr: v.baseAttr ?? fam.baseAttr, base: t.mainAttr }],
          subAttrPool: variantPool(v, basePool),
          variantId: v.id,
        })
      }
    }
  }

  return exclusive ? out.map((item) => ({ ...item, exclusive: true })) : out
}

const baseItems = expandBaseItems()
const exclusiveItems = expandBaseItems(
  exclusiveEquipmentJson as unknown as typeof baseItemsDataRaw,
  true,
)

const materialList: MaterialDef[] = [
  ...(materialsJson as unknown as { materials: MaterialDef[] }).materials,
]
for (const region of (fishJson as unknown as { regions: FishRegionDef[] }).regions) {
  for (const f of region.normal) {
    materialList.push({ id: f.id, name: f.name, kind: 'fish', regionId: region.regionId, sell: f.sell })
  }
  for (const f of [region.king, region.emperor]) {
    materialList.push({ id: f.id, name: f.name, kind: 'fish', regionId: region.regionId, sell: f.sell })
  }
}

export const gameData = {
  rarities: { order: raritiesData.order, byId: raritiesData.rarities },
  tagColors: {
    order: TAG_COLOR_ORDER,
    byId: tagsJson.colors as Record<TagColorId, TagColorDef>,
  },
  slots: slotsData.slots,
  slotCategories: slotsData.categories,
  attributes: subAttrData.attributes,
  attributeById: Object.fromEntries(subAttrData.attributes.map((a) => [a.id, a])) as Record<AttrId, AttributeDef>,
  terms: termsData,
  jobs: jobsData,
  jobById: Object.fromEntries(jobsData.jobs.map((j) => [j.id, j])) as Record<string, JobDef>,
  baseItems,
  baseItemById: Object.fromEntries([...baseItems, ...exclusiveItems].map((b) => [b.id, b])) as Record<string, BaseItem>,
  /** 世界BOSS 专属系列（绝境龙神）：不进入抽箱/合成/生产候选池。 */
  exclusiveItems,
  exclusiveItemById: Object.fromEntries(exclusiveItems.map((b) => [b.id, b])) as Record<string, BaseItem>,
  worldboss: worldbossJson as unknown as {
    version: string
    tickMs: number
    publishMs: number
    heartbeatSeconds: number
    disconnectSeconds: number
    leaseSeconds: number
    /** 阶段：按剩余血量占比自动进入，血量越低防御越厚、技能威力越高。 */
    phases: Array<{
      id: number
      name: string
      minHpRatio: number
      defenseMultiplier: number
      skillPotencyMultiplier: number
    }>
    boss: {
      id: string
      name: string
      maxHp: number
      attack: number
      attackIntervalSeconds: number
      respawnSeconds: number
      reviveSeconds: number
      skillIntervalSeconds: number
      skillPool: Array<{ id: string; name: string; effect: string; desc: string } & Record<string, unknown>>
    }
    rules: { heroSlots: number; levelRequirement: number; fullPowerLevel: number; weaknessFloor: number }
    reward: { minDamage: number; rankItems: Record<string, number>; defaultItems: number }
  },
  weaponFamilies: baseItemsDataRaw.weaponFamilies,
  baseItemTiers: baseItemsDataRaw.tiers,
  baseAttrFloat: baseItemsDataRaw.baseAttrFloat,
  subAttrFloat: baseItemsDataRaw.subAttrFloat,
  monsters: monstersJson as unknown as {
    reference: Record<string, unknown>
    regionHighLevelScale: {
      fromLevel: number
      hpPerLevel: number
      attackPerLevel: number
      /** Lv80 起血量 / 攻击 / 防御整体放大倍数。 */
      endgameFromLevel: number
      endgameMultiplier: number
    }
    monsterAttackInterval: number
    templates: MonsterTemplate[]
    eliteBaseChance: number
    xpPerGold: number
    equipmentDropChance: number
  },
  bosses: bossesJson as unknown as {
    hpMultiplierRange: [number, number]
    attackMultiplierRange: [number, number]
    defenseMultiplierRange: [number, number]
    attackInterval: number
    /** 单次命中对关底 BOSS 的伤害上限（占其最大生命 %），见 `bosses.json:maxHitDamagePct`。 */
    maxHitDamagePct: number
    reward: { goldMultiplierRange: [number, number]; xpMultiplierRange: [number, number]; boxCount: number }
    types: BossTypeDef[]
  },
  regions: regionsJson as unknown as {
    chapters: Array<{ id: number; name: string; regions: [number, number] }>
    regions: RegionDef[]
    goldFloat: number
    goldMultipliers: { normal: number; elite: number; boss: number }
    maxGoldBonus: number
    levelPenalty: {
      hitRatePenaltyPctPerLevel: number
      damageDealtPenaltyPctPerLevel: number
      damageTakenBonusPctPerLevel: number
      defenseIgnorePctPerLevel: number
      maxHitRatePenaltyPct: number
      maxDamageDealtPenaltyPct: number
      maxDamageTakenBonusPct: number
      maxDefenseIgnorePct: number
    }
  },
  raids: raidsJson as unknown as {
    balance: {
      bossSkillIntervalSeconds: number
      /** 默认每日奖励通关次数（副本可各自覆盖）。 */
      dailyRewardClears: number
    }
    /** 高难通关数计入品阶概率时的难度权重（仅首通、难度越高权重越高）。 */
    difficultyWeights: Record<string, number>
    /** 副本 BOSS 共享技能池：附加到每个副本 BOSS 上。 */
    bossSkillPool: unknown[]
    raids: RaidDef[]
  },
  chests: chestsJson as unknown as {
    chests: ChestDef[]
    pity: ChestPity[]
    /** 连抽档位；unlockCost>0 需账号一次性金币解锁。 */
    drawCounts: Array<{ count: number; unlockCost: number }>
    levelBands: Array<{ level: number; priceMultiplier: number }>
    dropRate: { perClearedRegion: number; maxMultiplier: number }
    /** 抽箱品阶概率的幸运来源：p = Σ weight × min(值/ref, 1)，luck = luckMax × p。 */
    rarityLuck: {
      luckMax: number
      sources: Record<string, { weight: number; ref: number }>
    }
  },
  crafting: craftingJson as unknown as {
    requiredCount: number
    categories: Category[]
    routes: Array<{ from: RarityId; to: RarityId; fee: number }>
  },
  economy: economyJson as unknown as {
    sell: { basePrice: number; randomFloat: number; scoreHalf: number; attrBonusMax: number; autoSellRarities: RarityId[] }
    /** 玩家间交易板：上架托管、整单买断成交，成交价抽 feePct 手续费；未售出 listingDays 天后退回。 */
    market: {
      feePct: number
      listingDays: number
      maxActiveListings: number
      maxStackQuantityPerListing: number
      minPrice: number
      maxPrice: number
    }
    /** 好友金币转账：转账方支付 amount，收款方实收 amount − floor(amount × feePct)。 */
    transfer: { feePct: number; minAmount: number; maxAmount: number; dailyLimit: number }
    refine: {
      baseAttrFloat: number
      subAttrFloat: number
      costGrowthPerRefine: number
      /** 等级价格系数 = 1 + (num / den) × (物品等级 − 1)：1 级 ×1、100 级 ×25/3 ≈ 8.33。 */
      costLevelGrowthNum: number
      costLevelGrowthDen: number
      basedOnCurrentCostMultiplier: number
      /** 「基于当前」浮动的下浮比例（新值 = 当前值 ×(1 − down)）。 */
      basedOnCurrentDownPct: number
      /** 「基于当前」浮动的上浮比例（新值 = 当前值 ×(1 + up)）。 */
      basedOnCurrentUpPct: number
      /** 「基于当前」重造时把一条普通 Buff 升为太古的概率。 */
      basedOnCurrentAncientUpgradeChance: number
    }
    enchant: {
      autoUntilRareExtraCostMultiplier: number
      /** 等级价格系数 = 1 + (num / den) × (物品等级 − 1)：与重造同一套等级曲线。 */
      costLevelGrowthNum: number
      costLevelGrowthDen: number
      basedOnCurrentCostMultiplier: number
      /** 「基于当前」浮动的下浮比例（新值 = 当前值 ×(1 − down)）。 */
      basedOnCurrentDownPct: number
      /** 「基于当前」浮动的上浮比例（新值 = 当前值 ×(1 + up)）。 */
      basedOnCurrentUpPct: number
      /** 「基于当前」附魔时把一条普通 Buff 升为太古的概率。 */
      basedOnCurrentAncientUpgradeChance: number
    }
    termQuality: Record<TermQuality, number>
    /** Debuff 是否参与稀有/太古品质判定（false = Debuff 恒为普通，仅在随机池内随机）。 */
    debuffQualityEnabled: boolean
    power: { weights: Record<string, number> }
  },
  talents: talentsJson as unknown as {
    order: RarityId[]
    talentWeights: Record<RarityId, number>
    baseRecruitCost: number
    refreshCost: number
    freeRefreshIntervalSec: number
    tenPullCost: number
    ancientChance: number
    ancientMultiplier: number
    ancientPityCount: number
    talents: Record<RarityId, TalentDef>
    biases: Record<string, TalentBias>
  },
  eggHeroes: (() => {
    const raw = eggHeroesJson as unknown as { eggChance: number; heroes: EggHeroDef[] }
    return {
      eggChance: raw.eggChance,
      heroes: raw.heroes,
      byId: Object.fromEntries(raw.heroes.map((h) => [h.id, h])) as Record<string, EggHeroDef>,
    }
  })(),
  heroes: heroesJson as unknown as Record<string, any>,
  combat: combatJson as unknown as Record<string, any>,
  tutorial: tutorialJson as unknown as {
    required: boolean
    completionReward: { gold: number; chests: Array<{ chestId: string; count: number }> }
    steps: TutorialStep[]
  },
  dohdolJobs: dohdolJobsJson as unknown as {
    kinds: Record<DohDolJobKind, { id: DohDolJobKind; name: string; enName: string }>
    jobs: DohDolJobDef[]
  },
  dohdolJobById: Object.fromEntries(
    (dohdolJobsJson as unknown as { jobs: DohDolJobDef[] }).jobs.map((j) => [j.id, j]),
  ) as Record<string, DohDolJobDef>,
  dohdolLevels: dohdolLevelsJson as unknown as {
    levelCap: number
    expCurve: { base: number; growth: number }
    kinds: Record<DohDolJobKind, { id: DohDolJobKind; name: string; desc: string }>
    actionXp: { gather: number; fish: number; craftBase: number }
  },
  materials: materialsJson as unknown as { materials: MaterialDef[] },
  materialById: Object.fromEntries(materialList.map((m) => [m.id, m])) as Record<string, MaterialDef>,
  gatherNodes: gatherNodesJson as unknown as {
    baseSecondsPerAction: number
    yieldPerLevelPct: number
    maxYieldLevelBonusPct: number
    nodes: GatherNodeDef[]
  },
  dohdolEquipment: dohdolEquipmentJson as unknown as {
    slots: DohDolSlotDef[]
    categories: Array<{ id: DohDolCategory; name: string; kind: DohDolJobKind }>
    bonusNames: Record<string, string>
    termCategories: TermCategoryDef[]
    terms: ProductionTermDef[]
    items: DohDolItemDef[]
  },
  dohdolItemById: Object.fromEntries(
    (dohdolEquipmentJson as unknown as { items: DohDolItemDef[] }).items.map((i) => [i.id, i]),
  ) as Record<string, DohDolItemDef>,
  fish: fishJson as unknown as {
    castSeconds: number
    insightBuffName: string
    regions: FishRegionDef[]
  },
  fishRegionById: Object.fromEntries(
    (fishJson as unknown as { regions: FishRegionDef[] }).regions.map((r) => [r.regionId, r]),
  ) as Record<number, FishRegionDef>,
  recipes: recipesJson as unknown as {
    equipment: {
      highQualityMultiplier: number
      guaranteedAncientTerms: number
      xpRarityMultiplier: Record<RarityId, number>
      rarityWeights: Record<RarityId, number>
      rarityScaling: {
        mythicCap: number
        sources: Record<string, { weight: number; ref: number }>
        targetWeights: Record<RarityId, number>
      }
    }
    recipes: RecipeDef[]
  },
  recipeById: Object.fromEntries(
    (recipesJson as unknown as { recipes: RecipeDef[] }).recipes.map((r) => [r.id, r]),
  ) as Record<string, RecipeDef>,
  consumables: consumablesJson as unknown as {
    kinds: Record<'potion' | 'food', { name: string; durationSec: number }>
    effectNames: Record<string, string>
    items: ConsumableDef[]
  },
  consumableById: Object.fromEntries(
    (consumablesJson as unknown as { items: ConsumableDef[] }).items.map((c) => [c.id, c]),
  ) as Record<string, ConsumableDef>,
  titles: titlesJson as unknown as { titles: TitleDef[] },
}

export type GameData = typeof gameData
export default gameData
