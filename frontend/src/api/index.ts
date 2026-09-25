import type {
  BattleReportResponse,
  BattleSessionStart,
  ChatMessage,
  CraftPlan,
  FriendTransferResult,
  FriendsData,
  GameState,
  Item,
  ItemTag,
  PlayerProfile,
  RankingEntry,
  RegionListEntry,
  RerollMode,
  SlotId,
  TutorialState,
} from '@/game/types'

import { http } from './client'

export interface KillPayload {
  monsterId: string
  gold: number
  exp: number
}

export interface AdminOnlineDevice {
  deviceId: string
  firstIp: string | null
  lastIp: string | null
  lastSeenSecondsAgo: number | null
}

export interface AdminOnlineAccount {
  id: number
  username: string
  nickname: string
  level: number | null
  gold: number
  banned: boolean
  isAdmin: boolean
  online: boolean
  lastSeenSecondsAgo: number | null
  regIp: string | null
  lastIp: string | null
  ips: string[]
  devices: AdminOnlineDevice[]
}

export interface AdminOnlineGroup {
  id: number
  onlineCount: number
  sharedDevices: { deviceId: string; accountIds: number[] }[]
  sharedIps: { ip: string; accountIds: number[] }[]
  accounts: AdminOnlineAccount[]
}

export interface AdminOnlineOverview {
  serverTime: string
  windowSeconds: number
  onlineCount: number
  totalAccounts: number
  groups: AdminOnlineGroup[]
}

export const api = {
  async register(username: string, password: string, nickname?: string) {
    return (await http.post<{ accessToken: string }>('/auth/register', { username, password, nickname })).data
  },

  async login(username: string, password: string) {
    return (await http.post<{ accessToken: string }>('/auth/login', { username, password })).data
  },

  /** 登出：服务端推进会话纪元，使本账号所有端的令牌立即失效。 */
  async logout() {
    return (await http.post<{ ok: boolean }>('/auth/logout')).data
  },

  async me() {
    return (
      await http.get<{
        id: number
        username: string
        nickname: string
        gold: number
        hasHero: boolean
        isAdmin: boolean
        friendCode: string
      }>('/auth/me')
    ).data
  },

  async changeNickname(nickname: string) {
    return (await http.post<{ nickname: string; message: string }>('/auth/change-nickname', { nickname })).data
  },

  async changePassword(currentPassword: string, newPassword: string, confirmPassword: string) {
    return (await http.post<{ ok: boolean; message: string }>('/auth/change-password', {
      currentPassword,
      newPassword,
      confirmPassword,
    })).data
  },

  async state() {
    return (await http.get<GameState>('/game/state')).data
  },

  async startBattle(regionId: number) {
    return (await http.post<BattleSessionStart>('/battle/session/start', { regionId })).data
  },

  async reportBattle(payload: {
    sessionId: number
    regionId: number
    elapsedMs: number
    kills: KillPayload[]
    skillCasts: Array<{ skillId: string; count: number }>
    killCount: number
    bossKilled: boolean
    died: boolean
    bossFightMs?: number
  }) {
    return (await http.post<BattleReportResponse>('/battle/session/report', payload)).data
  },

  async stopBattle(sessionId: number) {
    return (await http.post<{ ok: boolean; message: string }>('/battle/session/stop', { sessionId })).data
  },

  async reportDeath() {
    return (await http.post<{ ok: boolean; killCount: number; message: string }>('/battle/death')).data
  },

  async equip(itemId: number, slot: SlotId) {
    return (await http.post<{ item: Item }>('/inventory/equip', { itemId, slot })).data
  },

  async unequip(slot: SlotId) {
    return (await http.post('/inventory/unequip', { slot })).data
  },

  async sell(itemIds: number[]) {
    return (await http.post<{ gold: number; goldGained: number }>('/inventory/sell', { itemIds })).data
  },

  async tags() {
    return (await http.get<{ tags: ItemTag[] }>('/tags')).data
  },

  async createTag(name: string, color: string) {
    return (await http.post<{ tag: ItemTag }>('/tags', { name, color })).data
  },

  async updateTag(id: number, patch: { name?: string; color?: string }) {
    return (await http.post<{ tag: ItemTag }>(`/tags/${id}`, patch)).data
  },

  async deleteTag(id: number) {
    return (await http.delete<{ ok: boolean }>(`/tags/${id}`)).data
  },

  async setItemTags(itemId: number, tagIds: number[]) {
    return (await http.post<{ item: Item }>('/inventory/tags', { itemId, tagIds })).data
  },

  async openChest(chestId: string, count: number, level?: number) {
    return (
      await http.post<{
        gold: number
        cost: number
        items: Item[]
        autoSold: import('@/game/types').AutoSoldDrawItem[]
        autoGold: number
        pity: { sinceRare: number; sinceEpic: number; sinceLegendary: number }
      }>('/chest/open', { chestId, count, level })
    ).data
  },

  /** 一次性金币解锁连抽档位（如 50 / 100 连）。账号级，解锁后所有箱子通用。 */
  async unlockChestDraw(count: number) {
    return (
      await http.post<{ gold: number; count: number; unlocked: number[] }>('/chest/unlock', { count })
    ).data
  },

  async craftPreview(category: string, auto = true) {
    return (await http.post<{ plan: CraftPlan; gold: number; required: number }>('/economy/craft/preview', { category, auto })).data
  },

  async craft(category: string, auto = true) {
    return (
      await http.post<{ gold: number; fee: number; consumed: number; produced: Item[] }>('/economy/craft', {
        category,
        auto,
      })
    ).data
  },

  async refine(itemId: number, mode: RerollMode = 'random', times = 1) {
    return (
      await http.post<{ gold: number; cost: number; times: number; before: Item; after: Item }>(
        '/economy/refine',
        { itemId, mode, times },
      )
    ).data
  },

  async enchant(itemId: number, autoUntilRare = false, maxAttempts = 100, mode: RerollMode = 'random', times = 1) {
    return (
      await http.post<{
        gold: number
        cost: number
        attempts: number
        times?: number
        hit?: boolean
        before: Item
        after: Item
      }>('/economy/enchant', { itemId, autoUntilRare, maxAttempts, mode, times })
    ).data
  },

  async regions() {
    return (
      await http.get<{
        chapters: Array<{ id: number; name: string; regionIds: number[] }>
        regions: RegionListEntry[]
        currentRegionId: number
        killCount: number
        difficulty: { level: number; unlocked: number; maxLevel: number }
      }>('/region')
    ).data
  },

  async enterRegion(regionId: number) {
    return (await http.post('/region/enter', { regionId })).data
  },

  async advanceRegion() {
    return (await http.post('/region/advance', {})).data
  },

  /** 切换地区战斗难度（仅限已解锁范围）。 */
  async setDifficulty(level: number) {
    return (
      await http.post<{ difficulty: number; unlocked: number; maxLevel: number; currentRegionId: number }>(
        '/battle/difficulty',
        { level },
      )
    ).data
  },

  async tavern() {
    return (
      await http.get<{
        candidate: import('@/game/types').TavernCandidate
        recruitCost: number
        refreshCost: number
        tenPullCost: number
        multiCandidates: import('@/game/types').TavernCandidate[]
        ancientPity: { count: number; threshold: number }
        freeRefreshIntervalSec: number
        freeRefreshAvailable: boolean
        nextFreeRefreshAt: string | null
        currentHero: Record<string, unknown> | null
      }>('/tavern')
    ).data
  },

  async tavernRefresh(useGold: boolean) {
    return (await http.post('/tavern/refresh', { useGold })).data
  },

  async tavernRecruit(confirm: boolean) {
    return (await http.post('/tavern/recruit', { confirm })).data
  },

  async tavernDismiss(heroId: number) {
    return (await http.post('/tavern/dismiss', { heroId })).data
  },

  async tavernTenPull() {
    return (
      await http.post<{
        gold: number
        cost: number
        tenPullCost: number
        candidates: import('@/game/types').TavernCandidate[]
        ancientPity: { count: number; threshold: number }
      }>('/tavern/ten-pull', {})
    ).data
  },

  async tavernTenPullRecruit(index: number, confirm = true) {
    return (await http.post('/tavern/ten-pull/recruit', { index, confirm })).data
  },

  async tavernTenPullClear() {
    return (await http.post<{ ok: boolean; message: string }>('/tavern/ten-pull/clear', {})).data
  },

  async codex(category: 'equipment' | 'monster' | 'term' | 'material' | 'fish') {
    return (
      await http.get<{
        category: string
        progress: import('@/game/types').CodexProgress
        entries: Array<Record<string, unknown>>
      }>('/codex', { params: { category } })
    ).data
  },

  async ranking(board: string, page = 1, dungeon?: string) {
    return (
      await http.get<{
        board: string
        boards: string[]
        page: number
        entries: RankingEntry[]
        me: { rank: number; value: number } | null
        loggedIn: boolean
        dungeon?: string
        dungeons?: { id: string; name: string; difficulty: string }[]
      }>('/ranking', { params: { board, page, dungeon } })
    ).data
  },

  async rankingRefresh() {
    return (await http.post('/ranking/refresh', {})).data
  },

  async playerProfile(userId: number) {
    return (await http.get<PlayerProfile>(`/ranking/players/${userId}`)).data
  },

  // ---------------------------------------------------------------- 世界BOSS（全服共享血量）
  async worldbossState() {
    return (await http.get<import('@/game/worldboss').WorldBossState>('/worldboss/state')).data
  },

  async worldbossLeaderboard(page = 1) {
    return (
      await http.get<import('@/game/worldboss').WorldBossLeaderboard>('/worldboss/leaderboard', {
        params: { page },
      })
    ).data
  },

  async worldbossEnter(heroIds: number[]) {
    return (
      await http.post<import('@/game/worldboss').WorldBossState>('/worldboss/enter', { heroIds })
    ).data
  },

  async worldbossLeave() {
    return (await http.post('/worldboss/leave', {})).data
  },

  async worldbossHeartbeat() {
    return (await http.post('/worldboss/heartbeat', {})).data
  },

  /** 上报本地模拟的伤害增量（服务端按理论上限夹取，见 `game/core/worldboss.ts`）。 */
  async worldbossReport(payload: {
    reportSeq: number
    damage: number
    perHero: Array<{ heroId: number; damage: number }>
    elapsedMs?: number
  }) {
    return (
      await http.post<import('@/game/worldboss').WorldBossReportResult>('/worldboss/report', payload)
    ).data
  },

  async worldbossClaim(cycle?: number) {
    return (
      await http.post<import('@/game/worldboss').WorldBossReceipt>(
        '/worldboss/claim',
        {},
        { params: cycle ? { cycle } : undefined },
      )
    ).data
  },

  async worldbossTicket() {
    return (await http.post<{ ticket: string }>('/worldboss/ticket', {})).data
  },

  // ---------------------------------------------------------------- 好友系统
  async friends() {
    return (await http.get<FriendsData>('/friends')).data
  },

  async friendHeartbeat() {
    return (
      await http.get<{
        serverTime: string
        heartbeatSeconds: number
        onlineSeconds: number
        /** 同一设备并发在线超限时本账号被暂停（前端据此停掉战斗 / 采集循环）。 */
        blocked: boolean
        maxOnline: number
      }>('/friends/heartbeat')
    ).data
  },

  async friendRequest(code: string) {
    return (await http.post<{ status: string; message: string }>('/friends/request', { code })).data
  },

  async friendAccept(userId: number) {
    return (await http.post<{ status: string; message: string }>('/friends/accept', { userId })).data
  },

  async friendReject(userId: number) {
    return (await http.post<{ status: string; message: string }>('/friends/reject', { userId })).data
  },

  async friendRemove(userId: number) {
    return (await http.post<{ status: string; message: string }>('/friends/remove', { userId })).data
  },

  async friendTransfer(userId: number, amount: number) {
    return (await http.post<FriendTransferResult>('/friends/transfer', { userId, amount })).data
  },

  // ---------------------------------------------------------------- 聊天室
  async chatMessages() {
    return (
      await http.get<{ messages: ChatMessage[]; announcements: ChatMessage[]; serverTime: string }>(
        '/chat/messages',
      )
    ).data
  },

  async chatSend(text: string) {
    return (await http.post<{ message: ChatMessage }>('/chat/messages', { text })).data
  },

  async chatAnnounce(text: string) {
    return (await http.post<{ message: ChatMessage }>('/chat/announce', { text })).data
  },

  async tutorial() {
    return (await http.get<TutorialState>('/tutorial')).data
  },

  async tutorialStep(step: number) {
    return (await http.post<TutorialState>('/tutorial/step', { step })).data
  },

  async tutorialComplete() {
    return (await http.post<TutorialState & { granted: boolean; goldGained?: number; items?: Item[]; message?: string }>('/tutorial/complete', {})).data
  },

  async tutorialSkip() {
    return (await http.post<TutorialState & { message: string }>('/tutorial/skip', {})).data
  },

  async tutorialRestart() {
    return (await http.post<TutorialState & { message: string }>('/tutorial/restart', {})).data
  },

  async setAutoSell(enabled: boolean, rarities: string[]) {
    return (await http.post('/settings/auto-sell', { enabled, rarities })).data
  },

  /** 佩戴称号（设置页最多一个）；titleId 传 null 取消佩戴。 */
  async setActiveTitle(titleId: string | null) {
    return (
      await http.post<{ ok: boolean; activeTitleId: string | null; message?: string }>(
        '/settings/active-title',
        { titleId },
      )
    ).data
  },

  async redeemState() {
    return (await http.get<{ enabled: boolean; canRedeem: boolean; rewardGold: number }>('/redeem')).data
  },

  async redeem(code: string) {
    return (
      await http.post<{ ok: boolean; gold: number; goldGained: number; message: string }>('/redeem', { code })
    ).data
  },

  async raidList() {
    return (
      await http.get<{
        raids: import('@/game/types').RaidListEntry[]
        level: number
        power: number
        chest: { count: number; slots: string[] }
      }>('/raid')
    ).data
  },

  async raidChestClaim(slot: string) {
    return (
      await http.post<{
        gold: number
        count: number
        slot: string
        items: Item[]
        autoSold: Array<{ name: string; rarity: string; price: number }>
        autoGold: number
        pendingChest: number
      }>('/raid/chest/claim', { slot })
    ).data
  },

  async raidStart(raidId: string) {
    return (await http.post<import('@/game/types').RaidSessionStart>('/raid/session/start', { raidId })).data
  },

  async raidReport(payload: {
    mechanismFailures?: string[]
    sessionId: number
    raidId: string
    cleared: boolean
    died: boolean
    elapsedMs: number
    fightMs?: number
  }) {
    return (
      await http.post<import('@/game/types').RaidReportResponse>('/raid/session/report', payload)
    ).data
  },

  async raidStop(sessionId: number) {
    return (await http.post<{ ok: boolean; message: string }>('/raid/session/stop', { sessionId })).data
  },

  async adminUsers(query = '', limit = 20) {
    return (
      await http.get<{
        users: Array<{
          id: number
          username: string
          nickname: string
          gold: number
          level: number | null
          hasHero: boolean
          isAdmin: boolean
          banned: boolean
        }>
      }>('/admin/users', { params: { query, limit } })
    ).data
  },

  async adminResetPassword(userId: number, newPassword: string) {
    return (await http.post<{ ok: boolean; message: string }>('/admin/reset-password', { userId, newPassword })).data
  },

  async adminBanUser(userId: number, banned: boolean) {
    return (await http.post<{ ok: boolean; banned: boolean; message: string }>('/admin/ban', { userId, banned })).data
  },

  /** 在线玩家列表 + 按设备 / IP 的关联分组（反多开排查，仅管理员）。 */
  async adminOnline() {
    return (await http.get<AdminOnlineOverview>('/admin/online')).data
  },

  // ---------------------------------------------------------------- 生产 / 采集 DLC
  async dohdolState() {
    return (await http.get<import('@/game/types').DohDolState>('/dohdol/state')).data
  },

  async gatherStart(jobId: string, regionId: number) {
    return (
      await http.post<{
        sessionId: number
        jobId: string
        regionId: number
        cycle: import('@/game/types').ActivityCycle
      }>('/gather/session/start', { jobId, regionId })
    ).data
  },

  async gatherReport(sessionId: number) {
    return (await http.post<import('@/game/types').GatherReportResponse>('/gather/session/report', { sessionId })).data
  },

  async gatherStop(sessionId: number) {
    return (await http.post<{ ok: boolean; message: string }>('/gather/session/stop', { sessionId })).data
  },

  /** count=null 表示「制作全部」（按当前材料上限）。 */
  async produceStart(jobId: string, recipeId: string, count: number | null = null) {
    return (
      await http.post<{
        sessionId: number
        jobId: string
        recipeId: string
        targetActions: number
        cycle: import('@/game/types').ActivityCycle
      }>('/produce/session/start', { jobId, recipeId, count })
    ).data
  },

  async produceReport(sessionId: number) {
    return (await http.post<import('@/game/types').ProduceReportResponse>('/produce/session/report', { sessionId })).data
  },

  async produceStop(sessionId: number) {
    return (await http.post<{ ok: boolean; message: string }>('/produce/session/stop', { sessionId })).data
  },

  async fishStart(regionId: number) {
    return (
      await http.post<{
        sessionId: number
        regionId: number
        conditions: import('@/game/types').FishConditionsView
        cycle: import('@/game/types').ActivityCycle
      }>('/fish/session/start', { regionId })
    ).data
  },

  async fishReport(sessionId: number) {
    return (await http.post<import('@/game/types').FishReportResponse>('/fish/session/report', { sessionId })).data
  },

  async fishStop(sessionId: number) {
    return (await http.post<{ ok: boolean; message: string }>('/fish/session/stop', { sessionId })).data
  },

  async consume(itemId: string) {
    return (await http.post<{ kind: string; name: string; durationSec: number; active: import('@/game/types').ActiveConsumable[] }>('/consumable/use', { itemId })).data
  },

  async dohdolEquip(itemId: number, slot: string) {
    return (await http.post<{ ok: boolean; slot: string; itemId: number }>('/dohdol/equip', { itemId, slot })).data
  },

  async dohdolUnequip(slot: string) {
    return (await http.post<{ ok: boolean; slot: string }>('/dohdol/unequip', { slot })).data
  },

  async sellStack(kind: string, itemId: string, count: number) {
    return (
      await http.post<{
        gold: number
        goldGained: number
        unitPrice: number
        count: number
        itemId: string
        name: string
      }>('/dohdol/sell', { kind, itemId, count })
    ).data
  },

  // ---------------------------------------------------------------- 市场交易板
  async marketListings(params: {
    kind?: string
    rarity?: string
    category?: string
    q?: string
    sort?: string
    page?: number
    pageSize?: number
  } = {}) {
    return (
      await http.get<{
        listings: import('@/game/types').MarketListing[]
        total: number
        page: number
        pageSize: number
        feePct: number
        listingDays: number
        maxActiveListings: number
      }>('/market/listings', { params })
    ).data
  },

  async marketMine() {
    return (
      await http.get<{
        active: import('@/game/types').MarketListing[]
        closed: import('@/game/types').MarketListing[]
        activeCount: number
        maxActiveListings: number
        feePct: number
      }>('/market/mine')
    ).data
  },

  /** 上架：装备（type=equipment）与堆叠物（type=stack）可混合提交。 */
  async marketList(entries: import('@/game/types').MarketListEntry[]) {
    return (
      await http.post<{
        gold: number
        listings: import('@/game/types').MarketListing[]
        activeCount: number
      }>('/market/list', { entries })
    ).data
  },

  async marketBuy(listingId: number) {
    return (
      await http.post<{
        gold: number
        total: number
        fee: number
        sellerGold: number
        item: Item | null
      }>('/market/buy', { listingId })
    ).data
  },

  async marketCancel(listingId: number) {
    return (await http.post<{ gold: number; message: string }>('/market/cancel', { listingId })).data
  },

  /** 浏览他人发布的收购单。 */
  async marketBuyOrders(
    params: { kind?: string; sort?: string; page?: number; pageSize?: number } = {},
  ) {
    return (
      await http.get<{
        orders: import('@/game/types').MarketBuyOrder[]
        total: number
        page: number
        pageSize: number
        feePct: number
        listingDays: number
        maxActiveBuyOrders: number
      }>('/market/buy-orders', { params })
    ).data
  },

  async marketBuyOrdersMine() {
    return (
      await http.get<{
        active: import('@/game/types').MarketBuyOrder[]
        closed: import('@/game/types').MarketBuyOrder[]
        activeCount: number
        maxActiveBuyOrders: number
        feePct: number
      }>('/market/buy-orders/mine')
    ).data
  },

  /** 发布收购单：托管 unitPrice × quantity 金币。 */
  async marketBuyOrderCreate(entry: import('@/game/types').BuyOrderCreateEntry) {
    return (
      await http.post<{ gold: number; order: import('@/game/types').MarketBuyOrder }>(
        '/market/buy-orders',
        entry,
      )
    ).data
  },

  async marketBuyOrderCancel(orderId: number) {
    return (
      await http.post<{ gold: number; refund: number; message: string }>(
        '/market/buy-orders/cancel',
        { orderId },
      )
    ).data
  },

  /** 卖给收购单：按 count 部分 / 全部成交。 */
  async marketBuyOrderFill(orderId: number, count: number) {
    return (
      await http.post<{
        gold: number
        count: number
        total: number
        fee: number
        remaining: number
        status: string
      }>('/market/buy-orders/fill', { orderId, count })
    ).data
  },

  // ---------------------------------------------------------------- 挖宝
  async treasureState() {
    return (
      await http.get<{
        config: import('@/game/types').TreasureConfig
        run: import('@/game/types').TreasureRunState | null
      }>('/treasure/state')
    ).data
  },

  async treasureStart() {
    return (
      await http.post<{
        cost: number
        gold: number
        run: import('@/game/types').TreasureRunState
      }>('/treasure/start', {})
    ).data
  },

  async treasureFloorClear(runId: number, elapsedMs = 0) {
    return (
      await http.post<{
        event: import('@/game/types').TreasureEvent | null
        run: import('@/game/types').TreasureRunState
      }>('/treasure/floor/clear', { runId, elapsedMs })
    ).data
  },

  async treasureGamble(runId: number, guess: 'high' | 'low') {
    return (
      await http.post<import('@/game/types').TreasureGambleResult>('/treasure/gamble', {
        runId,
        guess,
      })
    ).data
  },

  async treasureGambleStop(runId: number) {
    return (
      await http.post<{ run: import('@/game/types').TreasureRunState }>('/treasure/gamble/stop', {
        runId,
      })
    ).data
  },

  async treasureChestOpen(runId: number) {
    return (
      await http.post<import('@/game/types').TreasureChestResult>('/treasure/chest/open', { runId })
    ).data
  },

  async treasureDoor(runId: number, door: number) {
    return (
      await http.post<{
        correct: boolean
        door: number
        run: import('@/game/types').TreasureRunState
      }>('/treasure/door/choose', { runId, door })
    ).data
  },

  async treasureRetry(runId: number) {
    return (
      await http.post<{ run: import('@/game/types').TreasureRunState }>('/treasure/retry', { runId })
    ).data
  },

  async treasureAbandon(runId: number) {
    return (
      await http.post<{ run: import('@/game/types').TreasureRunState }>('/treasure/abandon', {
        runId,
      })
    ).data
  },

  // ---------------------------------------------------------------- 魔晶石镶嵌
  async materiaState() {
    return (await http.get<import('@/game/types').MateriaState>('/materia/state')).data
  },

  async materiaSocket(slot: string, index: number, materiaId: string) {
    return (
      await http.post<import('@/game/types').MateriaSocketResult>('/materia/socket', {
        slot,
        index,
        materiaId,
      })
    ).data
  },

  async materiaRemove(slot: string, index: number) {
    return (
      await http.post<{
        removed: import('@/game/types').MateriaDef
        slot: string
        index: number
        state: import('@/game/types').MateriaState
      }>('/materia/remove', { slot, index })
    ).data
  },

  async materiaMerge(materiaId: string) {
    return (
      await http.post<{
        consumed: string
        count: number
        produced: import('@/game/types').MateriaDef
        state: import('@/game/types').MateriaState
      }>('/materia/merge', { materiaId })
    ).data
  },

  // ---------------------------------------------------------------- 种田
  async farmState() {
    return (await http.get<import('@/game/types').FarmState>('/farm/state')).data
  },

  async farmExpand() {
    return (
      await http.post<{ cost: number; state: import('@/game/types').FarmState }>('/farm/expand', {})
    ).data
  },

  async farmPlant(plotIndex: number, seedId: string) {
    return (
      await http.post<{ state: import('@/game/types').FarmState }>('/farm/plant', {
        plotIndex,
        seedId,
      })
    ).data
  },

  async farmHarvest(plotIndex: number, heroId?: number | null, confirm = false) {
    return (
      await http.post<{
        result: import('@/game/types').FarmHarvestResult
        state: import('@/game/types').FarmState
      }>('/farm/harvest', { plotIndex, heroId: heroId ?? null, confirm })
    ).data
  },
}
