import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api, type KillPayload } from '@/api'
import { toApiError } from '@/api/client'
import { BattleSimulator } from '@/game/core/battle'
import type { Category, GameState, Item, SlotId } from '@/game/types'

import { useAuthStore } from './auth'
import { useToastStore } from './toast'

const TICK_MS = 100
const REPORT_MS = 1500

export interface BossResult {
  bossName: string
  gold: number
  exp: number
  firstClear: boolean
  nextRegionId: number | null
  box: string | null
  items: Item[]
}

export const useGameStore = defineStore('game', () => {
  const auth = useAuthStore()
  const toast = useToastStore()

  const state = ref<GameState | null>(null)
  const loading = ref(false)
  const sim = shallowRef<BattleSimulator | null>(null)
  const sessionId = ref<number | null>(null)
  const running = ref(false)
  const logVersion = ref(0)
  const bossResult = ref<BossResult | null>(null)
  const lastError = ref<string | null>(null)

  let rafId = 0
  let lastTs = 0
  let reportAccum = 0
  let reporting = false
  let generation = 0

  const loggedIn = computed(() => auth.isLoggedIn)
  const hero = computed(() => state.value?.hero ?? null)
  const gold = computed(() => state.value?.user.gold ?? 0)
  const items = computed(() => state.value?.items ?? [])
  const loadout = computed(() => state.value?.loadout ?? {})
  const isRunning = computed(() => running.value && sim.value !== null)
  const battleLog = computed(() => {
    logVersion.value
    return sim.value?.log ?? []
  })
  const floating = computed(() => {
    logVersion.value
    return sim.value?.floating ?? []
  })

  function pushError(e: unknown) {
    const err = toApiError(e)
    lastError.value = err.message
    toast.push(err.message, 'error')
    if (err.status === 401) auth.logout()
  }

  async function loadState() {
    if (!auth.isLoggedIn) return
    loading.value = true
    try {
      state.value = await api.state()
    } catch (e) {
      pushError(e)
    } finally {
      loading.value = false
    }
  }

  /** 装备变更后重新计算面板并同步给模拟器。 */
  async function refreshAfterGearChange() {
    await loadState()
    if (sim.value && state.value) {
      sim.value.updateStats(state.value.hero.stats)
    }
  }

  // ---------- 战斗循环 ----------

  async function startBattle(regionId?: number) {
    if (!state.value) return
    const target = regionId ?? state.value.hero.currentRegionId ?? 1
    try {
      const session = await api.startBattle(target)
      sessionId.value = session.sessionId
      sim.value = new BattleSimulator({
        stats: state.value.hero.stats,
        regionId: target,
        killsRequired: session.killsRequired,
        spawnInterval: session.spawnInterval,
        killCount: 0,
      })
      sim.value.start()
      running.value = true
      logVersion.value += 1
      reportAccum = 0
      startLoop()
    } catch (e) {
      pushError(e)
    }
  }

  async function stopBattle(silent = false) {
    running.value = false
    stopLoop()
    sim.value?.pause()
    if (sessionId.value !== null) {
      const id = sessionId.value
      sessionId.value = null
      try {
        const res = await api.stopBattle(id)
        if (!silent) toast.push(res.message, 'info')
      } catch {
        /* 会话可能已结束，忽略 */
      }
    }
  }

  function startLoop() {
    if (rafId) return
    lastTs = performance.now()
    const step = (ts: number) => {
      const dtMs = Math.min(400, ts - lastTs)
      lastTs = ts
      const dt = dtMs / 1000

      if (sim.value && running.value) {
        sim.value.tick(dt)
        sim.value.clearFloating()
        logVersion.value += 1

        reportAccum += dtMs
        if (reportAccum >= REPORT_MS) {
          reportAccum = 0
          void report()
        }
      }
      rafId = requestAnimationFrame(step)
    }
    rafId = requestAnimationFrame(step)
  }

  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
  }

  async function report() {
    const current = sim.value
    const id = sessionId.value
    if (!current || id === null || reporting || !state.value) return

    const pending = current.drainPending()
    if (pending.kills.length === 0 && !pending.bossKilled && !pending.died) return

    reporting = true
    const gen = generation
    try {
      const res = await api.reportBattle({
        sessionId: id,
        regionId: current.region.id,
        elapsedMs: REPORT_MS,
        kills: pending.kills as KillPayload[],
        skillCasts: Object.entries(pending.skillCasts).map(([skillId, count]) => ({ skillId, count })),
        killCount: current.killCount,
        bossKilled: pending.bossKilled,
        died: pending.died,
        bossFightMs: pending.bossFightMs || undefined,
      })
      if (gen !== generation) return
      applyReport(res)
    } catch (e) {
      current.restorePending(pending)
      pushError(e)
    } finally {
      reporting = false
    }
  }

  function applyReport(res: Awaited<ReturnType<typeof api.reportBattle>>) {
    const current = sim.value
    if (!state.value || !current) return

    state.value.user.gold = res.gold
    state.value.hero.level = res.level.level
    state.value.hero.exp = res.level.exp
    if (res.goldGained > 0) {
      // 金币变化即时反映
      state.value.itemCounts = { ...state.value.itemCounts }
    }

    if (res.items.length > 0) {
      state.value.items = [...state.value.items, ...res.items]
      for (const item of res.items) {
        toast.push(`获得 ${item.name}（${item.rarity}）`, 'loot')
      }
    }
    if (res.autoSold.length > 0) {
      toast.push(`自动出售 ${res.autoSold.length} 件装备，+${res.autoGold} 金币`, 'info')
    }

    current.applyServerKillCount(res.killCount, res.killsRequired)

    if (res.boss) {
      bossResult.value = {
        bossName: res.boss.bossName,
        gold: res.boss.gold,
        exp: res.boss.exp,
        firstClear: res.boss.firstClear,
        nextRegionId: res.boss.nextRegionId,
        box: res.boss.box,
        items: res.boss.items,
      }
    }

    if (res.level.levelsGained > 0) {
      toast.push(`英雄升到 ${res.level.level} 级！`, 'success')
      void refreshAfterGearChange()
    }
  }

  function dismissBossResult() {
    bossResult.value = null
  }

  // ---------- 页面可见性：离开即暂停，不做离线收益 ----------

  function handleVisibility() {
    if (document.hidden) {
      if (running.value) void stopBattle(true)
    } else if (!running.value && sim.value && sessionId.value === null && state.value?.hero.currentRegionId) {
      // 恢复时重新开会话
      const regionId = sim.value.region.id
      void startBattle(regionId)
    }
  }

  // ---------- 装备 ----------

  async function equip(itemId: number, slot: SlotId) {
    try {
      await api.equip(itemId, slot)
      await refreshAfterGearChange()
    } catch (e) {
      pushError(e)
    }
  }

  async function unequip(slot: SlotId) {
    try {
      await api.unequip(slot)
      await refreshAfterGearChange()
    } catch (e) {
      pushError(e)
    }
  }

  async function sell(itemIds: number[]) {
    try {
      const res = await api.sell(itemIds)
      toast.push(`出售成功，获得 ${res.goldGained} 金币`, 'success')
      await loadState()
    } catch (e) {
      pushError(e)
    }
  }

  // ---------- 抽箱 ----------

  const lastDraw = ref<Item[]>([])

  async function openChest(chestId: string, count: number) {
    try {
      const res = await api.openChest(chestId, count)
      lastDraw.value = res.items
      state.value && (state.value.user.gold = res.gold)
      if (state.value) {
        state.value.items = [...state.value.items, ...res.items]
        const pity = state.value.pity[chestId] ?? { sinceRare: 0, sinceEpic: 0, sinceLegendary: 0 }
        state.value.pity[chestId] = { ...pity, ...res.pity }
      }
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  // ---------- 经济 ----------

  async function craft(category: Category, auto = true) {
    try {
      const res = await api.craft(category, auto)
      toast.push(`合成完成，消耗 ${res.consumed} 件，获得 ${res.produced.length} 件`, 'success')
      await loadState()
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function refine(itemId: number) {
    try {
      const res = await api.refine(itemId)
      toast.push(`重造完成，消耗 ${res.cost} 金币`, 'success')
      await loadState()
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function enchant(itemId: number, autoUntilRare = false) {
    try {
      const res = await api.enchant(itemId, autoUntilRare)
      toast.push(
        autoUntilRare
          ? `自动附魔 ${res.attempts} 次，消耗 ${res.cost} 金币${res.hit ? '，出现稀有/太古词条！' : ''}`
          : `附魔完成，消耗 ${res.cost} 金币`,
        res.hit ? 'loot' : 'success',
      )
      await loadState()
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  // ---------- 地区 ----------

  async function enterRegion(regionId: number) {
    try {
      if (running.value) await stopBattle(true)
      await api.enterRegion(regionId)
      await loadState()
      await startBattle(regionId)
    } catch (e) {
      pushError(e)
    }
  }

  async function advanceRegion() {
    try {
      if (running.value) await stopBattle(true)
      const res = await api.advanceRegion()
      await loadState()
      await startBattle((res as { region: { id: number } }).region.id)
    } catch (e) {
      pushError(e)
    }
  }

  // ---------- 生命周期 ----------

  function reset() {
    generation += 1
    running.value = false
    stopLoop()
    sim.value = null
    sessionId.value = null
    state.value = null
    bossResult.value = null
    lastDraw.value = []
  }

  return {
    state,
    loading,
    sim,
    sessionId,
    running,
    isRunning,
    battleLog,
    floating,
    bossResult,
    lastError,
    lastDraw,
    loggedIn,
    hero,
    gold,
    items,
    loadout,
    loadState,
    startBattle,
    stopBattle,
    report,
    dismissBossResult,
    handleVisibility,
    equip,
    unequip,
    sell,
    openChest,
    craft,
    refine,
    enchant,
    enterRegion,
    advanceRegion,
    refreshAfterGearChange,
    reset,
    TICK_MS,
  }
})
