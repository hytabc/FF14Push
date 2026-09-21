/** 后端接口返回的数据结构。 */

export type RarityId = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'mythic'
export type Category = 'weapon' | 'armor' | 'accessory'
export type SlotId =
  | 'mainHand' | 'head' | 'body' | 'hands' | 'legs' | 'feet'
  | 'necklace' | 'earring' | 'bracelet' | 'ring1' | 'ring2'
export type TermQuality = 'common' | 'rare' | 'ancient'
/** 重造 / 附魔模式：彻底随机（现价，全部重掷）或基于当前（更贵，每条在当前值附近浮动）。 */
export type RerollMode = 'random' | 'basedOnCurrent'

export interface BaseAttrEntry {
  attr: string
  value: number
  /** 该属性在当前品阶/档位下的合法区间（服务端下发，用于详情展示「当前值【区间】」）。 */
  min?: number
  max?: number
}

export interface SubAttrEntry {
  attr: string
  value: number
  type: 'flat' | 'percent'
  /** 副属性品质：普通 / 稀有（取上限）/ 太古（上限 ×1.25）。 */
  quality?: TermQuality
  /** 该属性在当前品阶/档位下的合法区间（太古值可超过 max）。 */
  min?: number
  max?: number
}

/** 重掷结果面板中的单条涨跌记录。 */
export interface RerollChange {
  key: string
  name: string
  /** 属性/词条的数值变化方向：up=涨（绿）、down=降（红）、same=不变。 */
  direction: 'up' | 'down' | 'same'
  before: number | null
  after: number | null
  delta: number | null
}

/** 玩家自建的装备标签（命名 + 调色板颜色 id）。 */
export interface ItemTag {
  id: number
  name: string
  color: string
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
  refineCostBasedOnCurrent: number
  enchantCostBasedOnCurrent: number
  source: string
  weaponType: string | null
  jobId: string | null
  /** 制造装备恒为「高品质」：属性区间上移且必带太古词条。 */
  highQuality?: boolean
  /** 玩家给该装备贴的标签 id 列表。 */
  tagIds: number[]
  sellPriceMin: number
  sellPriceMax: number
}

// ------------------------------------------------------------- 生产 / 采集 DLC
export type DohDolJobKind = 'doh' | 'dol'

export interface MaterialStackItem {
  itemId: string
  kind: string
  count: number
  name: string
  materialKind?: string
  consumableKind?: string
  effects?: Array<{ stat: string; value: number }>
  desc?: string
  /** 出售单价（金币）。 */
  sell?: number
}

export interface ActiveConsumable {
  kind: string
  itemId: string
  name: string
  effects: Array<{ stat: string; value: number }>
  remainingSec: number
}

export interface RecipeInputView {
  itemId: string
  name: string
  count: number
  have: number
}

export interface RecipeView {
  id: string
  jobId: string
  requiredLevel: number
  unlocked: boolean
  craftSeconds: number
  xp: number
  inputs: RecipeInputView[]
  output: {
    kind: string
    itemId: string | null
    baseId: string | null
    name: string
    count: number
    quality: string | null
    supply: string
  }
  craftable: number
}

export interface TitleView {
  id: string
  name: string
  desc: string
  owned: boolean
}

export interface DohDolProgressView {
  kind: string
  name: string
  level: number
  exp: number
  expToNext: number
  levelCap: number
}

export interface DohDolState {
  progress: Record<string, DohDolProgressView>
  materials: MaterialStackItem[]
  consumables: MaterialStackItem[]
  active: ActiveConsumable[]
  recipes: RecipeView[]
  loadout: Record<string, Item>
  bonus: Record<string, number>
  titles: TitleView[]
  fishStats: {
    species: number
    count: number
    king: number
    kingTotal: number
    emperor: number
    emperorTotal: number
  }
}

/** 后台循环的单次动作节奏（服务端下发，用于客户端画进度条）。 */
export interface ActivityCycle {
  /** 单次动作耗时（秒）。 */
  seconds: number
  /** 尚未结算的剩余秒数（跨上报保留的余额）。 */
  credit: number
  /** 服务端计算 credit 的时刻（epoch 毫秒），用于半 RTT 校正。 */
  at: number
}

export interface GatherReportResponse {
  gained: Array<{ itemId: string; name: string; count: number }>
  actions: number
  xp: number
  level: { levelsGained: number; level: number; exp: number }
  cycle: ActivityCycle
}

export interface ProduceReportResponse {
  crafts: number
  recipeId: string
  materials: Array<{ itemId: string; name: string; count: number }>
  items: Item[]
  xp: number
  level: { levelsGained: number; level: number; exp: number }
  cycle: ActivityCycle
}

export interface FishCatch {
  id: string
  name: string
  kind: 'normal' | 'king' | 'emperor'
  size: number
  exp: number
}

export interface FishReportResponse {
  caught: FishCatch[]
  gained: Array<{ itemId: string; name: string; count: number }>
  casts: number
  xp: number
  level: { levelsGained: number; level: number; exp: number }
  insightRemainingSec: number
  newTitles: string[]
  cycle: ActivityCycle
}

/** 排行榜点击查看的玩家资料（只含当前已装备栏位，只读）。 */
export interface PlayerProfile {
  userId: number
  nickname: string
  username: string
  hero: Hero | null
  power: number
  loadout: Partial<Record<SlotId, Item>>
  /** 生产 / 采集专用装备（仅含已装备栏位，跨账号只读）。 */
  dohdolLoadout: Partial<Record<string, Item>>
}

/** 被自动出售的掉落物（未进入背包，仅用于提示）。 */
export interface AutoSoldItem {
  baseId: string
  name: string
  rarity: RarityId
  price: number
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
  /** 太古三维：值为 'str'|'dex'|'int'，null 表示无 */
  ancientAttr: 'str' | 'dex' | 'int' | null
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
  /** 副本 BOSS：共享技能 CD（秒），到点后从技能池随机抽一个释放。 */
  skillInterval?: number
  /** 高难副本：BOSS 自带抗性（削减受到的伤害 %）。 */
  resistancePct?: number
  raidId?: string
}

export interface BossSkill {
  id: string
  name: string
  /** @deprecated 副本 BOSS 已改为共享 CD（`MonsterStats.skillInterval`）+ 随机抽取，此字段不再使用。 */
  cd?: number
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
  /** 重刷（非首通）通关经验，高难副本更高。 */
  repeatExp: number
}

export interface RaidListEntry {
  id: string
  order: number
  difficulty: 'normal' | 'hard'
  name: string
  requiredLevel: number
  requiredPower: number
  requiresAllSlots: boolean
  minEquipRarity: RarityId
  topRarity: RarityId | null
  topRarityCount: number
  minAncientTermsPerItem: number
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
  penalty: import("./core/regions").LevelPenalty
  sessionId: number
  raidId: string
  name: string
  difficulty: 'normal' | 'hard'
  bosses: MonsterStats[]
  enrage: RaidEnrage | null
  reward: RaidReward
}

export interface RaidReportResponse {
  cleared: boolean
  firstClear: boolean
  gold: number
  goldGained: number
  /** 本次通关获得的经验（首通用 firstExp，重刷用 repeatExp）。 */
  expGained: number
  /** 高难宝箱：通关后待开启的数量与可自选装备种类。 */
  pendingChest?: { count: number; slots: string[] } | null
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
  /** BOSS 技能名（高难副本会实际发动）。 */
  skillNames: string[]
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
  material: { unlocked: number; total: number }
  fish: { unlocked: number; total: number }
}

export interface TavernCandidate {
  name: string
  talent: RarityId
  attrBias: string
  attrBiasLabel: string
  strength: number
  agility: number
  intellect: number
  /** 太古三维：值为 'str'|'dex'|'int'，null 表示无 */
  ancientAttr: 'str' | 'dex' | 'int' | null
  totalPoints: number
  recruitCost: number
  recommendedJobs: string[]
}

export interface GameState {
  user: { id: number; nickname: string; gold: number }
  hero: Hero
  power: number
  powerAudit?: { version: string; groups: Record<string, number>; contributions: Record<string, { raw: number; effective: number; contribution: number }> }
  expToNext: number
  recruitCost: number
  loadout: Partial<Record<SlotId, Item>>
  items: Item[]
  itemCounts: Record<RarityId, number>
  /** 玩家自建的装备标签列表。 */
  tags: ItemTag[]
  regionProgress: Record<string, RegionProgressEntry>
  currentRegion: CurrentRegion | null
  /** 已通关地区数。 */
  clearedRegions: number
  /** 品阶爆率倍率（随通关进度提升，仅影响装备品阶）。 */
  dropRateMultiplier: number
  pity: Record<string, PityEntry>
  skillStats: Record<string, number>
  codex: CodexProgress
  tutorial: { currentStep: number; completed: boolean; skipped: boolean }
  tavern: { candidate: TavernCandidate | null }
  settings: { autoSell: { enabled: boolean; rarities: RarityId[] } }
  dohdol: DohDolState
}

export interface BattleSessionStart {
  penalty: import("./core/regions").LevelPenalty
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
  autoSold: AutoSoldItem[]
  autoGold: number
  boss: {
    gold: number
    exp: number
    level: { levelsGained: number; exp: number; level: number }
    firstClear: boolean
    nextRegionId: number | null
    box: string | null
    items: Item[]
    autoSold: AutoSoldItem[]
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
  /** 登录账号：与昵称一起展示（昵称可重复，账号唯一）。 */
  username: string
  value: number
  payload: Record<string, unknown>
}
