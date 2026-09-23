import type {
  BattleReportResponse,
  BattleSessionStart,
  CraftPlan,
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

export const api = {
  async register(username: string, password: string, nickname?: string) {
    return (await http.post<{ accessToken: string }>('/auth/register', { username, password, nickname })).data
  },

  async login(username: string, password: string) {
    return (await http.post<{ accessToken: string }>('/auth/login', { username, password })).data
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
      }>('/region')
    ).data
  },

  async enterRegion(regionId: number) {
    return (await http.post('/region/enter', { regionId })).data
  },

  async advanceRegion() {
    return (await http.post('/region/advance', {})).data
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
}
