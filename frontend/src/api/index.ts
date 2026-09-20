import type {
  BattleReportResponse,
  BattleSessionStart,
  CraftPlan,
  GameState,
  Item,
  RankingEntry,
  RegionListEntry,
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
      await http.get<{ id: number; username: string; nickname: string; gold: number; hasHero: boolean }>('/auth/me')
    ).data
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

  async openChest(chestId: string, count: number) {
    return (
      await http.post<{
        gold: number
        cost: number
        items: Item[]
        autoSold: Array<{ name: string; rarity: string; price: number }>
        pity: { sinceRare: number; sinceEpic: number; sinceLegendary: number }
      }>('/chest/open', { chestId, count })
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

  async refine(itemId: number) {
    return (await http.post<{ gold: number; cost: number; before: Item; after: Item }>('/economy/refine', { itemId })).data
  },

  async enchant(itemId: number, autoUntilRare = false, maxAttempts = 100) {
    return (
      await http.post<{
        gold: number
        cost: number
        attempts: number
        hit?: boolean
        before: Item
        after: Item
      }>('/economy/enchant', { itemId, autoUntilRare, maxAttempts })
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
        freeRefreshIntervalSec: number
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

  async tavernDismiss() {
    return (await http.post('/tavern/dismiss', {})).data
  },

  async codex(category: 'equipment' | 'monster' | 'term') {
    return (
      await http.get<{
        category: string
        progress: import('@/game/types').CodexProgress
        entries: Array<Record<string, unknown>>
      }>('/codex', { params: { category } })
    ).data
  },

  async ranking(board: string, page = 1) {
    return (
      await http.get<{
        board: string
        boards: string[]
        page: number
        entries: RankingEntry[]
        me: { rank: number; value: number } | null
        loggedIn: boolean
      }>('/ranking', { params: { board, page } })
    ).data
  },

  async rankingRefresh() {
    return (await http.post('/ranking/refresh', {})).data
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
}
