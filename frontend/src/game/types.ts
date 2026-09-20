/** 后端接口返回的数据结构。 */

export type RarityId = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'mythic'
export type Category = 'weapon' | 'armor' | 'accessory'
export type SlotId =
  | 'mainHand' | 'head' | 'body' | 'hands' | 'legs' | 'feet'
  | 'necklace' | 'earring' | 'bracelet' | 'ring1' | 'ring2'
export type TermQuality = 'common' | 'rare' | 'ancient'

export interface BaseAttrEntry {
  attr: string
  value: number
}

export interface SubAttrEntry {
  attr: string
  value: number
  type: 'flat' | 'percent'
}

export interface TermEntry {
  id: string
  name: string
  type: 'buff' | 'debuff'
  stat: string
  trigger: string
  value: number
  quality: TermQuality
  desc: string
}

export interface Item {
  id: number
  baseId: string
  name: string
  category: Category
  slot: string
  equipSlots: SlotId[]
  rarity: RarityId
  levelReq: number
  score: number
  baseAttrs: BaseAttrEntry[]
  subAttrs: SubAttrEntry[]
  terms: TermEntry[]
  equippedSlot: SlotId | null
  refineCount: number
  enchantCount: number
  refineCost: number
  enchantCost: number
  source: string
  weaponType: string | null
  jobId: string | null
  sellPriceMin: number
  sellPriceMax: number
}

export interface HeroStats {
  level: number
  jobId: string
  mainAttr: 'str' | 'dex' | 'int'
  maxHp: number
  maxMp: number
  hpRegen: number
  mpRegen: number
  attack: number
  magicAttack: number
  physDef: number
  magicDef: number
  dodgePct: number
  attackSpeedPct: number
  hitRatePct: number
  hastePct: number
  lifestealPct: number
  tenacityPct: number
  critValue: number
  dhValue: number
  detValue: number
  critRatePct: number
  critDamagePct: number
  dhRatePct: number
  detBonusPct: number
  termMods: Record<string, number>
}

export interface Hero {
  id: number | null
  name: string
  level: number
  exp: number
  talent: RarityId
  talentName: string
  attrBias: 'str' | 'dex' | 'int' | 'balanced'
  strength: number
  agility: number
  intellect: number
  currentRegionId: number | null
  regionKillCount: number
  isInitial: boolean
  jobId: string
  stats: HeroStats
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

export interface MonsterStats {
  id: string
  regionId: number
  name: string
  templateId: string
  kind: 'normal' | 'elite' | 'boss'
  hp: number
  attack: number
  defense: number
  attackInterval: number
  level: number
  bossType?: string
  skills?: BossSkill[]
  /** 高难副本：BOSS 自带抗性（削减受到的伤害 %）。 */
  resistancePct?: number
  raidId?: string
}

export interface BossSkill {
  id: string
  name: string
  cd: number
  effect: string
  potency?: number
  desc: string
  duration?: number
  chargeSeconds?: number
  hpThreshold?: number
  attackBuff?: number
  damageReduce?: number
  attackSpeedDebuff?: number
  damageType?: string
}

export interface CurrentRegion extends RegionDef {
  killsRequired: number
  spawnInterval: number
  boss: MonsterStats
  monsters: MonsterStats[]
}

export interface RegionProgressEntry {
  regionId: number
  unlocked: boolean
  cleared: boolean
  clearedAt: string | null
  bestClearMs: number | null
}

/** 高难副本：一方阵亡后对存活 BOSS 施加的狂暴加成。 */
export interface RaidEnrage {
  attackMultiplier: number
  damageReductionPct: number
  attackSpeedBonusPct: number
}

export interface RaidReward {
  firstGold: number
  firstExp: number
  chestId: string
  boxCount: number
  repeatGold: number
}

export interface RaidListEntry {
  id: string
  order: number
  name: string
  requiredLevel: number
  requiredPower: number
  requiresAllSlots: boolean
  bossNames: string[]
  dualBoss: boolean
  reward: RaidReward
  eligible: boolean
  blockedReason: string | null
  cleared: boolean
  clearCount: number
  bestClearMs: number | null
}

export interface RaidSessionStart {
  sessionId: number
  raidId: string
  name: string
  bosses: MonsterStats[]
  enrage: RaidEnrage | null
  reward: RaidReward
}

export interface RaidReportResponse {
  cleared: boolean
  firstClear: boolean
  gold: number
  goldGained: number
  items: Item[]
  autoSold: Array<{ name: string; rarity: string; price: number }>
  autoGold: number
  fightMs: number
  message: string
  level?: { levelsGained: number; exp: number; level: number }
}

/** 副本战斗面板用的单个 BOSS 状态。 */
export interface RaidBossEntry {
  id: string
  name: string
  hp: number
  maxHp: number
  hpPct: number
  enraged: boolean
  isTarget: boolean
}

export interface RegionListEntry extends RegionDef {
  killsRequired: number
  spawnInterval: number
  unlocked: boolean
  cleared: boolean
  bestClearMs: number | null
  recommendedLevel: number
  lockedHint: string
  isCurrent: boolean
}

export interface PityEntry {
  sinceRare: number
  sinceEpic: number
  sinceLegendary: number
}

export interface ChestDef {
  id: string
  name: string
  price: number
  category: Category
  tier: 'normal' | 'advanced'
  icon: string
}

export interface TutorialStep {
  step: number
  key: string
  title: string
  action: string
  text: string
}

export interface TutorialState {
  currentStep: number
  totalSteps: number
  completed: boolean
  skipped: boolean
  rewarded: boolean
  steps: TutorialStep[]
}

export interface CodexProgress {
  equipment: { unlocked: number; total: number }
  monster: { unlocked: number; total: number }
  term: { unlocked: number; total: number }
}

export interface TavernCandidate {
  name: string
  talent: RarityId
  attrBias: string
  attrBiasLabel: string
  strength: number
  agility: number
  intellect: number
  totalPoints: number
  recruitCost: number
  recommendedJobs: string[]
}

export interface GameState {
  user: { id: number; nickname: string; gold: number }
  hero: Hero
  power: number
  expToNext: number
  recruitCost: number
  loadout: Partial<Record<SlotId, Item>>
  items: Item[]
  itemCounts: Record<RarityId, number>
  regionProgress: Record<string, RegionProgressEntry>
  currentRegion: CurrentRegion | null
  pity: Record<string, PityEntry>
  skillStats: Record<string, number>
  codex: CodexProgress
  tutorial: { currentStep: number; completed: boolean; skipped: boolean }
  tavern: { candidate: TavernCandidate | null }
  settings: { autoSell: { enabled: boolean; rarities: RarityId[] } }
}

export interface BattleSessionStart {
  sessionId: number
  regionId: number
  killsRequired: number
  spawnInterval: number
  boss: MonsterStats
  region: RegionDef
}

export interface BattleReportResponse {
  gold: number
  goldGained: number
  expGained: number
  level: { levelsGained: number; exp: number; level: number }
  killCount: number
  killsRequired: number
  items: Item[]
  autoSold: Array<{ baseId: string; name: string; rarity: RarityId; price: number }>
  autoGold: number
  boss: {
    gold: number
    exp: number
    level: { levelsGained: number; exp: number; level: number }
    firstClear: boolean
    nextRegionId: number | null
    box: string | null
    items: Item[]
    autoSold: unknown[]
    bossName: string
  } | null
  warnings: string[]
}

export interface CraftStep {
  from: RarityId
  to: RarityId
  available: number
  crafts: number
  fee: number
  totalFee: number
}

export interface CraftPlan {
  steps: CraftStep[]
  totalFee: number
  delta: Record<string, number>
  produced: Record<string, number>
  counts: Record<string, number>
}

export interface RankingEntry {
  rank: number
  userId: number
  nickname: string
  value: number
  payload: Record<string, unknown>
}
