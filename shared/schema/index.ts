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

export interface TermDef {
  id: string
  name: string
  type: 'buff' | 'debuff'
  trigger: string
  stat: string
  range: [number, number]
  slots?: SlotId[]
  desc: string
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
  baseAttrs: BaseAttrEntry[]
  subAttrPool: AttrId[]
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
  requiredLevel: number
  requiredPower: number
  requiresAllSlots: boolean
  enrage: RaidEnrageDef | null
  bosses: RaidBossDef[]
  reward: {
    firstGold: number
    firstExp: number
    chestId: string
    boxCount: number
    repeatGold: number
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
  terms: TermDef[]
}

const jobsData = jobsJson as unknown as {
  gcd: number
  maxSkills: number
  skillPriorityOrder: number[]
  roles: Record<JobRole, { id: JobRole; name: string }>
  jobs: JobDef[]
}

const baseItemsDataRaw = baseItemsJson as unknown as {
  tiers: Array<{ index: number; name: string; levelReq: number; weaponAttack: number; defense: number; hp: number; mainAttr: number }>
  subAttrPools: Record<string, AttrId[]>
  baseAttrFloat: number
  subAttrFloat: number
  weaponFamilies: Array<{ weaponType: string; jobId: string; suffix: string; pool: string }>
  armorFamilies: Array<{ slot: SlotId; suffix: string; baseAttrs: Array<{ attr: BaseAttrId; ratio: number }> }>
  accessoryFamilies: Array<{ slot: SlotId; suffix: string; baseAttr: AttrId; pool: string }>
}

/** 基础属性 ID 到中文名 */
export const BASE_ATTR_NAMES: Record<BaseAttrId, string> = Object.fromEntries(
  subAttrData.baseAttributes.map((a) => [a.id, a.name]),
) as Record<BaseAttrId, string>

export const ATTR_NAMES: Record<string, string> = Object.fromEntries(
  subAttrData.attributes.map((a) => [a.id, a.name]),
)

/** 展开底材：武器族 × 档位、防具族 × 档位、饰品族 × 档位 */
export function expandBaseItems(): BaseItem[] {
  const d = baseItemsDataRaw
  const jobMainAttr = new Map(jobsData.jobs.map((j) => [j.id, j.mainAttr]))
  const out: BaseItem[] = []

  for (const fam of d.weaponFamilies) {
    const isMagical = jobMainAttr.get(fam.jobId) === 'int'
    for (const t of d.tiers) {
      out.push({
        id: `w_${fam.weaponType}_${t.index}`,
        name: `${t.name}${fam.suffix}`,
        category: 'weapon',
        slot: 'mainHand',
        weaponType: fam.weaponType,
        jobId: fam.jobId,
        levelReq: t.levelReq,
        tierIndex: t.index,
        tierName: t.name,
        baseAttrs: [{ attr: isMagical ? 'magicAttack' : 'attack', base: t.weaponAttack }],
        subAttrPool: d.subAttrPools[fam.pool],
      })
    }
  }

  for (const fam of d.armorFamilies) {
    for (const t of d.tiers) {
      out.push({
        id: `a_${fam.slot}_${t.index}`,
        name: `${t.name}${fam.suffix}`,
        category: 'armor',
        slot: fam.slot,
        levelReq: t.levelReq,
        tierIndex: t.index,
        tierName: t.name,
        baseAttrs: fam.baseAttrs.map((b) => ({
          attr: b.attr,
          base: b.attr === 'hp' ? t.hp * b.ratio : t.defense * b.ratio,
        })),
        subAttrPool: d.subAttrPools.armor,
      })
    }
  }

  for (const fam of d.accessoryFamilies) {
    for (const t of d.tiers) {
      out.push({
        id: `c_${fam.slot}_${t.index}`,
        name: `${t.name}${fam.suffix}`,
        category: 'accessory',
        slot: fam.slot,
        levelReq: t.levelReq,
        tierIndex: t.index,
        tierName: t.name,
        baseAttrs: [{ attr: fam.baseAttr, base: t.mainAttr }],
        subAttrPool: d.subAttrPools[fam.pool],
      })
    }
  }

  return out
}

const baseItems = expandBaseItems()

export const gameData = {
  rarities: { order: raritiesData.order, byId: raritiesData.rarities },
  slots: slotsData.slots,
  slotCategories: slotsData.categories,
  attributes: subAttrData.attributes,
  attributeById: Object.fromEntries(subAttrData.attributes.map((a) => [a.id, a])) as Record<AttrId, AttributeDef>,
  terms: termsData,
  jobs: jobsData,
  jobById: Object.fromEntries(jobsData.jobs.map((j) => [j.id, j])) as Record<string, JobDef>,
  baseItems,
  baseItemById: Object.fromEntries(baseItems.map((b) => [b.id, b])) as Record<string, BaseItem>,
  baseItemTiers: baseItemsDataRaw.tiers,
  baseAttrFloat: baseItemsDataRaw.baseAttrFloat,
  subAttrFloat: baseItemsDataRaw.subAttrFloat,
  monsters: monstersJson as unknown as {
    reference: Record<string, unknown>
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
      maxHitRatePenaltyPct: number
      maxDamageDealtPenaltyPct: number
      maxDamageTakenBonusPct: number
    }
  },
  raids: raidsJson as unknown as {
    balance: {
      powerScaleExponent: number
      attackScaleExponent: number
      refDpsMultiplier: Record<string, number>
    }
    raids: RaidDef[]
  },
  chests: chestsJson as unknown as { chests: ChestDef[]; pity: ChestPity[] },
  crafting: craftingJson as unknown as {
    requiredCount: number
    categories: Category[]
    routes: Array<{ from: RarityId; to: RarityId; fee: number }>
  },
  economy: economyJson as unknown as {
    sell: { basePrice: number; randomFloat: number; scoreHalf: number; attrBonusMax: number; autoSellRarities: RarityId[] }
    refine: { baseAttrFloat: number; subAttrFloat: number }
    enchant: { autoUntilRareExtraCostMultiplier: number }
    termQuality: Record<TermQuality, number>
    power: { weights: Record<string, number> }
  },
  talents: talentsJson as unknown as {
    order: RarityId[]
    baseRecruitCost: number
    refreshCost: number
    freeRefreshIntervalSec: number
    talents: Record<RarityId, TalentDef>
    biases: Record<string, TalentBias>
  },
  heroes: heroesJson as unknown as Record<string, any>,
  combat: combatJson as unknown as Record<string, any>,
  tutorial: tutorialJson as unknown as {
    required: boolean
    completionReward: { gold: number; chests: Array<{ chestId: string; count: number }> }
    steps: TutorialStep[]
  },
}

export type GameData = typeof gameData
export default gameData
