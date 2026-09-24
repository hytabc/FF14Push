/** 后端接口返回的数据结构。 */

export type RarityId = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'mythic'
export type Category = 'weapon' | 'armor' | 'accessory'
export type JobRole = 'tank' | 'healer' | 'melee' | 'physicalRanged' | 'magicalRanged'
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
  /** 词条类别（见 terms.json / dohdol-equipment.json 的 categories 名表）。 */
  category?: string
  /** 风险代价类词条的副作用（value 已按 ratio 折算）。 */
  cost?: { stat: string; value: number; name: string }
}

export interface Item {
  equippedHeroId?: number | null
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
  /** 世界BOSS 专属系列（绝境龙神）：仅世界BOSS 掉落，重造/附魔代价远高。 */
  exclusive?: boolean
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
  /** 魔晶石：种类 / 属性 / 等级 / 加成值。 */
  materiaKind?: string
  stat?: string
  statName?: string
  level?: number
  value?: number
  /** 作物种子：产出类型（gold / heroLevel）。 */
  seedKind?: string
}

export interface ActiveConsumable {
  kind: string
  itemId: string
  name: string
  effects: Array<{ stat: string; value: number }>
  remainingSec: number
  /** 绝对到期时间（ISO 8601，服务端时钟），前端据此实时倒计时。 */
  expiresAt: string
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
  /** 解锁条件的结构化描述（后端 titles.json）。 */
  condition?: { type: string } & Record<string, unknown>
  /** 彩蛋称号：低概率掉落（挖宝下底 / 采集）。 */
  egg?: boolean
}

export interface DohDolProgressView {
  kind: string
  name: string
  level: number
  exp: number
  expToNext: number
  levelCap: number
}

/** 制造品阶概率的一项来源（展示用：当前值 / 参考值 / 归一值 / 权重）。 */
export interface CraftOddsSource {
  key: string
  value: number
  ref: number
  norm: number
  weight: number
}

/** 服务端结算的制造品阶概率分布（随进度提升）。 */
export interface CraftOdds {
  odds: Record<RarityId, number>
  luck: number
  mythicCap: number
  sources: CraftOddsSource[]
}

/** 抽箱品阶概率的幸运来源与上限（服务端结算，前端只展示）。 */
export interface ChestRarityLuck {
  luck: number
  luckMax: number
  sources: CraftOddsSource[]
}

export interface DohDolState {
  progress: Record<string, DohDolProgressView>
  materials: MaterialStackItem[]
  consumables: MaterialStackItem[]
  /** 魔晶石库存（挖宝产出）。 */
  materia?: MaterialStackItem[]
  /** 作物种子库存（挖宝产出）。 */
  seeds?: MaterialStackItem[]
  active: ActiveConsumable[]
  recipes: RecipeView[]
  loadout: Record<string, Item>
  bonus: Record<string, number>
  craft: CraftOdds
  titles: TitleView[]
  /** 佩戴中的称号 id（设置页最多一个）；null = 未佩戴。 */
  activeTitleId: string | null
  fishStats: {
    species: number
    count: number
    king: number
    kingTotal: number
    emperor: number
    emperorTotal: number
    /** 困难鱼（legend）种类数与总数。 */
    legend: number
    legendTotal: number
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

/** 经验加成的一项来源（专用装备固定加成 / 词条 / 药水食物）。 */
export interface ActivityExpSource {
  label: string
  pct: number
}

/** 生产 / 采集 / 钓鱼的经验结算明细。恒满足 base × rarityMultiplier × (1 + bonusPct/100) ≈ amount。 */
export interface ActivityExpBreakdown {
  /** 未加成的基础经验。 */
  base: number
  /** 品阶系数（生产装备才有，其它恒为 1）。 */
  rarityMultiplier: number
  /** 百分比加成合计。 */
  bonusPct: number
  /** 最终获得经验。 */
  amount: number
  sources: ActivityExpSource[]
}

/** 生产 / 采集日志条目（按结算轮次追加）。 */
export interface ActivityLogEntry {
  id: number
  text: string
  tone: 'loot' | 'exp' | 'system'
}

export interface GatherReportResponse {
  gained: Array<{ itemId: string; name: string; count: number }>
  actions: number
  xp: number
  xpBreakdown: ActivityExpBreakdown
  level: { levelsGained: number; level: number; exp: number }
  /** 本次极低概率掉落的彩蛋称号 id。 */
  newTitles: string[]
  cycle: ActivityCycle
}

export interface ProduceReportResponse {
  crafts: number
  recipeId: string
  materials: Array<{ itemId: string; name: string; count: number }>
  items: Item[]
  xp: number
  xpBreakdown: ActivityExpBreakdown
  level: { levelsGained: number; level: number; exp: number }
  /** 本次会话目标制造件数（null = 不限）。 */
  targetActions: number | null
  /** 本次会话已制造总件数。 */
  producedTotal: number
  /** 达到目标、服务端已自动结束会话。 */
  finished: boolean
  cycle: ActivityCycle
}

export interface FishCatch {
  id: string
  name: string
  kind: 'normal' | 'king' | 'emperor' | 'legend'
  /** 普通鱼档位（白 / 蓝 / 紫）；特殊鱼为 null。 */
  rarity?: 'white' | 'blue' | 'purple' | null
  size: number
  exp: number
}

/** 生效中的「捕鱼人之识」：每种直觉只绑定一条鱼。 */
export interface FishInsightView {
  fishId: string
  /** 该 BUFF 绑定的鱼名。 */
  name: string
  kind: 'king' | 'emperor' | 'legend'
  /** BUFF 名称（如「捕鱼人之识」「镜中之识」）。 */
  buffName: string
  remainingSec: number
  expiresAt: string
}

/** 当前钓场的天气 / 艾欧泽亚时间条件。 */
export interface FishConditionsView {
  weather: string
  weatherName: string
  weatherHex: string
  etHour: number
  etClock: string
  timeOfDay: string
  timeOfDayName: string
}

export interface FishReportResponse {
  caught: FishCatch[]
  gained: Array<{ itemId: string; name: string; count: number }>
  casts: number
  xp: number
  xpBreakdown: ActivityExpBreakdown
  level: { levelsGained: number; level: number; exp: number }
  /** 当前环境条件（天气 / ET）。 */
  conditions: FishConditionsView
  /** 本次生效中的「捕鱼人之识」列表（一鱼一 BUFF，各自倒计时）。 */
  insights: FishInsightView[]
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
  /** 累计在线时长（秒）。 */
  playSeconds: number
  loadout: Partial<Record<SlotId, Item>>
  /** 生产 / 采集专用装备（仅含已装备栏位，跨账号只读）。 */
  dohdolLoadout: Partial<Record<string, Item>>
  /** 该玩家佩戴中的称号 id；null = 未佩戴。 */
  activeTitleId: string | null
}

/** 被自动出售的掉落物（未进入背包，仅用于提示）。 */
export interface AutoSoldItem {
  baseId: string
  name: string
  rarity: RarityId
  price: number
}

/** 抽到时即被自动出售的抽奖物品：完整物品数据 + 成交价，用于播放动画与结果页展示。 */
export interface AutoSoldDrawItem extends Item {
  autoSold: true
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

/**
 * 面板属性拆解（`/game/state.statBreakdown`）：由后端 `compute_stats_with_breakdown` 下发，
 * 记录该英雄面板属性的中间聚合量，供「如何计算」说明代入真实数值。
 */
export interface StatBreakdown {
  level: number
  bias: string
  mainAttr: string
  jobId: string
  jobMatch: boolean
  /** 职业定位的攻防效率（jobs.json:roles）：attack / defense 为乘算系数，近战DPS 为基准 1.0。 */
  roleEfficiency?: { role: string | null; attack: number; defense: number }
  /** 资质成长系数（talents.growthCoef）。 */
  growthCoef: number
  /** 装备三维入核心属性的折算率（已含职业匹配加成）。 */
  biasRates: Record<string, number>
  /** 职业主属性匹配时装备主属性的额外加成（%）。 */
  jobMatchBonusPct: number
  /** 三维：英雄自身 / 装备折算后 / 合计。 */
  core: {
    hero: Record<string, number>
    equip: Record<string, number>
    total: Record<string, number>
  }
  /** 「base + Σ(coef × 核心属性总量) + 等级成长」后的裸面板值（含 cap，未叠加装备/词条）。 */
  panelBase: Record<string, number>
  /** panelBase 中来自等级成长的部分。 */
  levelGrowth: Record<string, number>
  /** 各属性上限（heroes.json 的 cap）。 */
  caps: Record<string, number>
  /** 装备直接提供的基础属性：hp / attack / magicAttack / physDef / magicDef。 */
  equipFlat: Record<string, number>
  /** 装备 + 魔晶石副属性合计：regen/dodge/sks/acc/sps/lifesteal/tenacity/crit/dh/det。 */
  subs: Record<string, number>
  /** 聚合词条修正（与 HeroStats.termMods 同源）。 */
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
  /** 彩蛋英雄 id，null 表示普通英雄 */
  eggId: string | null
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
  /** 目标等级：BOSS 数值固定按此等级锚定，低于它会被等级压制。 */
  challengeLevel: number
  requiredPower: number
  requiresAllSlots: boolean
  minEquipRarity: RarityId
  topRarity: RarityId | null
  topRarityCount: number
  minAncientTermsPerItem: number
  bossNames: string[]
  dualBoss: boolean
  reward: RaidReward
  /** 每个账号每天可获得奖励的通关次数（首通计入）。 */
  dailyRewardClears: number
  /** 当日已获得奖励的通关次数。 */
  rewardedToday: number
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
  /** 当日奖励次数已用尽：本次通关不产出金币/经验/宝箱（仅记录通关与用时）。 */
  rewardLimited?: boolean
  /** 当日剩余奖励通关次数。 */
  remainingToday?: number
  gold: number
  goldGained: number
  goldCalculation?: GoldCalculation
  /** 本次通关获得的经验（首通用 firstExp，重刷用 repeatExp）。 */
  expGained: number
  expCalculation?: ExpCalculation
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
  /** 彩蛋英雄 id，null/缺失表示普通英雄 */
  eggId?: string | null
  totalPoints: number
  recruitCost: number
  recommendedJobs: string[]
}

export interface GameState {
  /** 当前英雄低于账号最高等级时的战斗经验追赶加成。 */
  catchUpExpBonusPct?: number
  activeHeroId?: number | null
  heroes?: Hero[]
  /** 远征队（英雄名册）容量：当前席位数、上限与再开一席的金币价格（已达上限为 null）。 */
  roster?: { capacity: number; maxCapacity: number; expandCost: number | null }
  user: { id: number; nickname: string; gold: number; activeTitleId: string | null }
  hero: Hero
  power: number
  powerAudit?: { version: string; groups: Record<string, number>; contributions: Record<string, { raw: number; effective: number; contribution: number }> }
  /** 当前英雄的面板属性拆解（用于「如何计算」说明）。 */
  statBreakdown?: StatBreakdown
  expToNext: number
  recruitCost: number
  loadout: Partial<Record<SlotId, Item>>
  items: Item[]
  itemCounts: Record<RarityId, number>
  /** 玩家自建的装备标签列表。 */
  tags: ItemTag[]
  regionProgress: Record<string, RegionProgressEntry>
  currentRegion: CurrentRegion | null
  /** 地区战斗难度：当前等级、已解锁上限与最高等级。 */
  difficulty: { level: number; unlocked: number; maxLevel: number }
  /** 已通关地区数。 */
  clearedRegions: number
  /** 品阶爆率倍率（随通关进度提升，仅影响装备品阶）。 */
  dropRateMultiplier: number
  /** 抽箱品阶概率的幸运来源与上限（服务端结算）。 */
  chestRarityLuck?: ChestRarityLuck
  pity: Record<string, PityEntry>
  skillStats: Record<string, number>
  codex: CodexProgress
  tutorial: { currentStep: number; completed: boolean; skipped: boolean }
  tavern: { candidate: TavernCandidate | null }
  settings: { autoSell: { enabled: boolean; rarities: RarityId[] }; chestUnlocks?: number[] }
  dohdol: DohDolState
}

export interface BattleSessionStart {
  penalty: import("./core/regions").LevelPenalty
  sessionId: number
  regionId: number
  /** 地区战斗难度等级（0 = 当前各地区数值）。 */
  difficulty: number
  killsRequired: number
  spawnInterval: number
  boss: MonsterStats
  region: RegionDef
}

export interface BattleReportResponse {
  gold: number
  goldGained: number
  goldCalculation?: GoldCalculation
  expGained: number
  expCalculation?: ExpCalculation
  level: { levelsGained: number; exp: number; level: number }
  killCount: number
  killsRequired: number
  items: Item[]
  autoSold: AutoSoldItem[]
  autoGold: number
  boss: {
    gold: number
    goldCalculation?: GoldCalculation
    exp: number
    expCalculation?: ExpCalculation
    level: { levelsGained: number; exp: number; level: number }
    firstClear: boolean
    nextRegionId: number | null
    /** 通关当前难度最后一个地区时解锁的下一难度等级；否则 null。 */
    unlockedDifficulty: number | null
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

// ------------------------------------------------------------- 好友系统
/** 好友条目（好友列表与待处理申请共用）。 */
export interface FriendEntry {
  userId: number
  nickname: string
  username: string
  online: boolean
  /** 距上次在线秒数；从未在线为 null。 */
  lastSeenSecondsAgo: number | null
  /** 当前英雄等级；无英雄为 null。 */
  level: number | null
}

export interface FriendsData {
  /** 我的好友码（可复制分享）。 */
  friendCode: string
  /** 转账手续费比例（如 0.10）。 */
  feePct: number
  minAmount: number
  maxAmount: number
  dailyLimit: number
  /** 今日剩余可转账额度（近 24h 累计）。 */
  remainingToday: number
  friends: FriendEntry[]
  incoming: FriendEntry[]
  outgoing: FriendEntry[]
}

// ------------------------------------------------------------- 聊天室
/** 大厅消息（普通发言或管理员公告）。普通发言不保留记录，仅返回滚动窗口内的消息；公告长期保留并置顶。 */
export interface ChatMessage {
  id: number
  kind: 'normal' | 'announcement'
  text: string
  createdAt: string
  userId: number
  nickname: string
  /** 登录账号；管理员为空字符串（不回显管理员账号）。 */
  username: string
  isAdmin: boolean
}

export interface FriendTransferResult {
  gold: number
  amount: number
  fee: number
  net: number
  recipientNickname: string
  remainingToday: number
}


/** Server settlement basis already includes monster/reward multipliers and penalties. */
export interface ExpCalculation {
  base: number
  efficiencyBonus: number
  catchUpBonus: number
  totalBonusPct: number
}

/** 金币结算明细（与 ExpCalculation 同构）：结算基础 / 收益加成 / 药水加成。 */
export interface GoldCalculation {
  base: number
  penaltyBonus: number
  potionBonus: number
  totalBonusPct: number
}

// ------------------------------------------------------------- 市场交易板
/** 装备快照（上架时的属性/词条，供买家预览）。 */
export interface MarketEquipmentDetail {
  baseId: string
  name: string
  category: Category | string
  slot: string
  rarity: RarityId
  levelReq: number
  highQuality?: boolean
  baseAttrs: BaseAttrEntry[]
  subAttrs: SubAttrEntry[]
  terms: TermEntry[]
}

/** 一条寄售单。 */
export interface MarketListing {
  id: number
  /** equipment | material | potion | food */
  kind: string
  /** 装备 = 底材 id；堆叠 = 物品 id（用于解析图标）。 */
  itemKey: string
  name: string
  rarity: RarityId | null
  category: string | null
  slot: string | null
  levelReq: number | null
  /** 购买等级门槛类别：combat = 任一英雄达标 / doh / dol；无限制为 null。 */
  requiredKind?: 'combat' | 'doh' | 'dol' | null
  /** 当前玩家是否满足购买等级门槛（仅浏览列表返回；缺省视为满足）。 */
  levelMet?: boolean
  quantity: number
  /** 单价（装备即总价）。 */
  unitPrice: number
  /** 整单总价 = 单价 × 数量。 */
  totalPrice: number
  /** 上架时的系统回收价（参考）。 */
  referencePrice: number
  status: string
  sellerId: number
  sellerNickname: string | null
  /** 成交后回填的买家 id 与昵称（仅已售出记录有值）。 */
  buyerId?: number | null
  buyerNickname?: string | null
  createdAt: string | null
  expiresAt: string | null
  /** 仅装备：属性 / 词条明细。 */
  equipment?: MarketEquipmentDetail
}

/** 上架条目请求体。 */
export interface MarketListEntry {
  type: 'equipment' | 'stack'
  itemId?: number
  stackKind?: 'material' | 'potion' | 'food' | 'materia' | 'seed'
  stackItemId?: string
  count?: number
  unitPrice: number
}

/** 一条收购单（求购）：托管金币求购某堆叠物，卖家手动部分成交。 */
export interface MarketBuyOrder {
  id: number
  /** material | potion | food | materia | seed */
  kind: string
  itemKey: string
  name: string
  /** 求购总数 / 已成交数 / 剩余数。 */
  quantity: number
  filled: number
  remaining: number
  unitPrice: number
  /** 求购总数对应的托管金币。 */
  totalPrice: number
  /** 剩余部分对应的托管金币。 */
  remainingPrice: number
  /** 发布时的系统回收价（参考）。 */
  referencePrice: number
  /** active | filled | cancelled | expired */
  status: string
  buyerId: number
  buyerNickname: string | null
  createdAt: string | null
  expiresAt: string | null
  closedAt: string | null
}

/** 发布收购单请求体。 */
export interface BuyOrderCreateEntry {
  kind: 'material' | 'potion' | 'food' | 'materia' | 'seed'
  itemId: string
  quantity: number
  unitPrice: number
}

// ------------------------------------------------------------- 魔晶石镶嵌
/** 单件魔晶石（6 种 × 5 级）。 */
export interface MateriaDef {
  id: string
  name: string
  /** 种类 id（str / dex / int / crit / det / dh）。 */
  type: string
  stat: string
  statName: string
  level: number
  value: number
  sell: number
}

export interface MateriaSocketState {
  index: number
  /** 该孔位的镶嵌成功率。 */
  chance: number
  materia: MateriaDef | null
}

export interface MateriaSlotState {
  id: SlotId
  name: string
  category: string
  order: number
  sockets: MateriaSocketState[]
}

export interface MateriaStockEntry extends MateriaDef {
  count: number
}

export interface MateriaState {
  slots: MateriaSlotState[]
  socketsPerSlot: number
  successChance: number[]
  mergeFrom: number
  maxLevel: number
  stock: MateriaStockEntry[]
  bonus: Record<string, number>
  source: { note: string }
}

export interface MateriaSocketResult {
  success: boolean
  chance: number
  slot: string
  index: number
  materia: MateriaDef
  state: MateriaState
}

// ------------------------------------------------------------- 种田
export interface SeedView {
  id: string
  name: string
  desc: string
  yield: { type: string; amount?: number; levels?: number }
  count: number
}

export interface FarmPlotState {
  index: number
  locked: boolean
  seedId: string | null
  seedName: string | null
  /** 种植时刻（服务端 epoch 毫秒）。 */
  plantedAt: number | null
  /** 成熟时刻（服务端 epoch 毫秒）。 */
  matureAt: number | null
  /** 当前阶段（0 = 刚种下，stages = 成熟）。 */
  stage: number
  stages: number
  stageSeconds: number
  remainingMs: number
  ready: boolean
}

export interface FarmState {
  unlocked: number
  initialPlots: number
  maxPlots: number
  /** 下一次扩张价格；已满级为 null。 */
  expansionCost: number | null
  expansionCosts: number[]
  stages: number
  stageSeconds: number
  plots: FarmPlotState[]
  seeds: SeedView[]
  gold: number
}

export interface FarmHarvestResult {
  type: 'gold' | 'heroLevel'
  amount?: number
  gold?: number
  heroId?: number
  heroName?: string
  levelsGained?: number
  level?: number
  noEffect?: boolean
}

// ------------------------------------------------------------- 挖宝
export interface TreasureConfig {
  entryCost: number
  floors: number
  doors: number
  correctChance: number
  sourceRegionId: number
  goldMultiplier: number
  expMultiplier: number
  finalBonusGold: number
  specialEventChance: number
  cardMin: number
  cardMax: number
  maxGuesses: number
  rewardIncreasePerGuess: number
  tieIsLoss: boolean
  rewardWeights: Record<string, number>
  rewardsPerFloor: { base: number; perFloor: number }
  stackQtyPerFloor: { base: number; perFloor: number }
  potionTierByFloor: number[]
  materiaLevelByFloor: number[][]
}

export interface TreasureRunState {
  runId: number
  floor: number
  status: 'fighting' | 'cleared' | 'ended'
  multiplier: number
  card: number | null
  guessesUsed: number
  maxGuesses: number
  eventActive: boolean
  chestOpened: boolean
  endedReason: string | null
  /** 待挑战的怪物（仅 fighting 时有值）。 */
  boss: MonsterStats | null
}

export interface TreasureEvent {
  card: number
  maxGuesses: number
  rewardIncreasePerGuess: number
}

export interface TreasureReward {
  kind: 'gold' | 'exp' | 'potion' | 'materia' | 'seed' | 'bonusGold'
  amount?: number
  itemId?: string
  name?: string
  count?: number
  level?: number
  stat?: string
  statName?: string
  value?: number
  tier?: number
}

export interface TreasureChestResult {
  floor: number
  multiplier: number
  rewards: TreasureReward[]
  gold: number
  goldGained: number
  expGained: number
  level: { levelsGained: number; level: number; exp: number } | null
  bonusGold: number
  completed: boolean
  /** 通关第 5 层（下底）时极低概率掉落的彩蛋称号 id。 */
  newTitles: string[]
  run: TreasureRunState
}

export interface TreasureGambleResult {
  previousCard: number
  card: number
  result: 'win' | 'lose' | 'tie'
  multiplier: number
  guessesUsed: number
  guessesLeft: number
  cleared: boolean
  finished: boolean
  run: TreasureRunState
}

