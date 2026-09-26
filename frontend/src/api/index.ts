import type {
  BattleReportResponse,
  BattleSessionStart,
  ChatMessage,
  CraftPlan,
  FriendTransferResult,
  FriendsData,
  GameState,
  ImportedSequence,
  Item,
  ItemTag,
  PlayerProfile,
  RankingEntry,
  RegionListEntry,
  RerollMode,
  SavedSequence,
  SlotId,
  TutorialState,
} from '@/game/types'
import type { SequenceLoopMode, SequenceStep } from '@/game/core/sequence'

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
    return (
      await http.post<{ item: Item; unequipped?: { id: number; name: string }[] }>('/inventory/equip', {
        itemId,
        slot,
      })
    ).data
  },

  async unequip(slot: SlotId) {
    return (await http.post('/inventory/unequip', { slot })).data
  },

  /** 一键最强预览：保留主手武器，列出各栏位将更换的装备。 */
  async autoEquipPreview(includeEquipped: boolean) {
    return (
      await http.post<{
        jobId: string
        role: string
        weapon: Item | null
        changes: Array<{ slot: SlotId; current: Item | null; next: Item }>
        fromOthers: number
      }>('/inventory/auto-equip/preview', { includeEquipped })
    ).data
  },

  /** 一键最强：把符合职能、战力最高的装备一键装备到当前英雄（武器保持不变）。 */
  async autoEquip(includeEquipped: boolean) {
    return (
      await http.post<{
        stats: import('@/game/types').HeroStats
        equipped: Array<{ slot: SlotId; item: Item }>
        changes: Array<{ slot: SlotId; item: Item }>
        fromOthers: number
      }>('/inventory/auto-equip', { includeEquipped })
    ).data
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

  async sequences() {
    return (await http.get<{ sequences: SavedSequence[] }>('/sequences')).data
  },

  async saveSequence(payload: {
    name: string
    steps: SequenceStep[]
    loopMode: SequenceLoopMode
    loopTotal: number
  }) {
    return (await http.post<{ sequence: SavedSequence }>('/sequences', payload)).data
  },

  async overwriteSequence(
    id: number,
    payload: { name?: string; steps: SequenceStep[]; loopMode: SequenceLoopMode; loopTotal: number },
  ) {
    return (await http.post<{ sequence: SavedSequence }>(`/sequences/${id}`, payload)).data
  },

  async deleteSequence(id: number) {
    return (await http.delete<{ ok: boolean }>(`/sequences/${id}`)).data
  },

  async importBlueprint(code: string) {
    return (await http.get<{ sequence: ImportedSequence }>(`/sequences/blueprint/${code}`)).data
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

  async refine(itemId: number, mode: RerollMode = 'random', times = 1, useCard = false) {
    return (
      await http.post<{
        gold: number
        cost: number
        times: number
        useCard?: boolean
        cardsCost?: number
        cardsLeft?: number
        before: Item
        after: Item
      }>('/economy/refine', { itemId, mode, times, useCard })
    ).data
  },

  async enchant(
    itemId: number,
    autoUntilRare = false,
    maxAttempts = 100,
    mode: RerollMode = 'random',
    times = 1,
    useCard = false,
  ) {
    return (
      await http.post<{
        gold: number
        cost: number
        attempts: number
        times?: number
        hit?: boolean
        useCard?: boolean
        cardsCost?: number
        cardsLeft?: number
        before: Item
        after: Item
      }>('/economy/enchant', { itemId, autoUntilRare, maxAttempts, mode, times, useCard })
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

  /** 补偿公示：管理员发放金币的记录（公开只读，含事由）。 */
  async compensationRecords(page = 1) {
    return (
      await http.get<{
        page: number
        pageSize: number
        total: number
        records: Array<{
          id: number
          userId: number
          nickname: string
          amount: number
          note: string
          createdAt: string | null
        }>
      }>('/grants', { params: { page } })
    ).data
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

  /** 自动卖鱼：按鱼的档位（normal / king / emperor / legend）选择要自动出售的鱼。 */
  async setAutoSellFish(enabled: boolean, kinds: string[]) {
    return (await http.post<{ ok?: boolean; enabled: boolean; kinds: string[]; message?: string }>(
      '/settings/auto-sell-fish',
      { enabled, kinds },
    )).data
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

  /** 给指定玩家发放金币补偿（管理员）。金额与事由会记入公开的「补偿公示」。 */
  async adminGrantGold(userId: number, amount: number, reason = '') {
    return (
      await http.post<{ ok: boolean; gold: number; message: string }>('/admin/grant-gold', {
        userId,
        amount,
        reason,
      })
    ).data
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

  // --------------------------------------------------------------- 重建伊修加德
  async ishgardState() {
    return (await http.get<import('@/game/types').IshgardState>('/ishgard/state')).data
  },

  async ishgardLeaderboard(page = 1, pageSize = 50) {
    return (
      await http.get<{
        page: number
        pageSize: number
        entries: import('@/game/types').IshgardLeaderboardEntry[]
        me: { rank: number; points: number }
      }>('/ishgard/leaderboard', { params: { page, pageSize } })
    ).data
  },

  async ishgardGatherStart(jobId: string) {
    return (
      await http.post<{
        sessionId: number
        jobId: string
        stage: number
        cycle: import('@/game/types').ActivityCycle
      }>('/ishgard/gather/session/start', { jobId })
    ).data
  },

  async ishgardGatherReport(sessionId: number) {
    return (await http.post<import('@/game/types').IshgardGatherReport>('/ishgard/gather/session/report', { sessionId })).data
  },

  async ishgardGatherStop(sessionId: number) {
    return (await http.post('/ishgard/gather/session/stop', { sessionId })).data
  },

  async ishgardFishStart() {
    return (
      await http.post<{
        sessionId: number
        stage: number
        cycle: import('@/game/types').ActivityCycle
      }>('/ishgard/fish/session/start', {})
    ).data
  },

  async ishgardFishReport(sessionId: number) {
    return (await http.post<import('@/game/types').IshgardGatherReport>('/ishgard/fish/session/report', { sessionId })).data
  },

  async ishgardFishStop(sessionId: number) {
    return (await http.post('/ishgard/fish/session/stop', { sessionId })).data
  },

  async ishgardProduceStart(jobId: string, recipeId: string, count: number | null = null) {
    return (
      await http.post<{
        sessionId: number
        jobId: string
        recipeId: string
        targetActions: number
        stage: number
        cycle: import('@/game/types').ActivityCycle
      }>('/ishgard/produce/session/start', { jobId, recipeId, count })
    ).data
  },

  async ishgardProduceReport(sessionId: number) {
    return (await http.post<import('@/game/types').IshgardProduceReport>('/ishgard/produce/session/report', { sessionId })).data
  },

  async ishgardProduceStop(sessionId: number) {
    return (await http.post('/ishgard/produce/session/stop', { sessionId })).data
  },

  async ishgardSubmit(itemId: string, count = 1) {
    return (await http.post<import('@/game/types').IshgardSubmitResult>('/ishgard/submit', { itemId, count })).data
  },

  async ishgardSell(itemId: string, count = 1) {
    return (await http.post<{ gold: number; itemId: string; count: number }>('/ishgard/sell', { itemId, count })).data
  },

  async ishgardToolClaim(kind: 'doh' | 'dol') {
    return (await http.post<import('@/game/types').IshgardToolView>('/ishgard/tool/claim', { kind })).data
  },

  async ishgardToolUpgrade(kind: 'doh' | 'dol') {
    return (await http.post<import('@/game/types').IshgardToolView>('/ishgard/tool/upgrade', { kind })).data
  },

  async ishgardToolEnchant(kind: 'doh' | 'dol') {
    return (await http.post<import('@/game/types').IshgardToolView>('/ishgard/tool/enchant', { kind })).data
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
    slot?: string
    q?: string
    levelMin?: number
    levelMax?: number
    priceMin?: number
    priceMax?: number
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

  // ---------------------------------------------------------------- 死者宫殿
  async palaceState() {
    return (
      await http.get<{
        config: import('@/game/types').PalaceConfig
        profile: import('@/game/types').PalaceProfile
        run: import('@/game/types').PalaceRunState | null
      }>('/palace/state')
    ).data
  },

  async palaceStart() {
    return (
      await http.post<{
        profile: import('@/game/types').PalaceProfile
        run: import('@/game/types').PalaceRunState
      }>('/palace/start', {})
    ).data
  },

  async palaceChooseHero(index: number) {
    return (
      await http.post<{ run: import('@/game/types').PalaceRunState }>('/palace/hero/choose', {
        index,
      })
    ).data
  },

  async palaceChooseWeapon(index: number) {
    return (
      await http.post<{ run: import('@/game/types').PalaceRunState }>('/palace/weapon/choose', {
        index,
      })
    ).data
  },

  async palaceEnterNode(nodeId: string) {
    return (
      await http.post<{
        run: import('@/game/types').PalaceRunState
        context: import('@/game/types').PalaceNodeContext
      }>('/palace/node/enter', { nodeId })
    ).data
  },

  async palaceClearNode(nodeId: string, elapsedMs: number, result: 'win' | 'lose' = 'win') {
    return (
      await http.post<{
        run: import('@/game/types').PalaceRunState
        profile: import('@/game/types').PalaceProfile
        gold: number
        exp: number
        level: { levelsGained: number; level: number; exp: number } | null
        bossReward: {
          floor: number
          growthPoints: number
          flameCrest: number
          glassPumpkin: number
          completed: boolean
          newTitles: string[]
        } | null
      }>('/palace/node/clear', { nodeId, elapsedMs, result })
    ).data
  },

  async palaceClaimReward(index: number) {
    return (
      await http.post<{
        granted: Record<string, unknown>
        run: import('@/game/types').PalaceRunState
      }>('/palace/reward/claim', { index })
    ).data
  },

  async palaceEventChoose(nodeId: string, choiceIndex: number) {
    return (
      await http.post<{
        results: Array<Record<string, unknown>>
        run: import('@/game/types').PalaceRunState
        profile: import('@/game/types').PalaceProfile
      }>('/palace/event/choose', { nodeId, choiceIndex })
    ).data
  },

  async palaceShopBuy(nodeId: string, offerIndex: number) {
    return (
      await http.post<{
        granted: Record<string, unknown>
        run: import('@/game/types').PalaceRunState
      }>('/palace/shop/buy', { nodeId, offerIndex })
    ).data
  },

  async palaceEquip(index: number) {
    return (
      await http.post<{ run: import('@/game/types').PalaceRunState }>('/palace/equip', { index })
    ).data
  },

  async palaceAbandon() {
    return (
      await http.post<{ run: import('@/game/types').PalaceRunState }>('/palace/abandon', {})
    ).data
  },

  async palaceGrowth() {
    return (await http.get<import('@/game/types').PalaceGrowthView>('/palace/growth')).data
  },

  async palaceGrowthUnlock(nodeId: string) {
    return (
      await http.post<{
        unlocked: string
        view: import('@/game/types').PalaceGrowthView
      }>('/palace/growth/unlock', { nodeId })
    ).data
  },

  async palaceExchange() {
    return (await http.get<import('@/game/types').PalaceExchangeView>('/palace/exchange')).data
  },

  async palaceExchangeBuy(exchangeId: string, count = 1) {
    return (
      await http.post<{
        granted: Array<Record<string, unknown>>
        view: import('@/game/types').PalaceExchangeView
      }>('/palace/exchange', { exchangeId, count })
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
