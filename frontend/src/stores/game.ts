import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api, type KillPayload } from '@/api'
import { toApiError } from '@/api/client'
import { BattleSimulator } from '@/game/core/battle'
import type { Category, GameState, Item, RaidBossEntry, RaidReportResponse, RerollMode, SlotId } from '@/game/types'
import { rarityName } from '@/utils/format'

import { useAuthStore } from './auth'
import { useToastStore } from './toast'

const TICK_MS = 100
const REPORT_MS = 1500
const AUTO_ADVANCE_KEY = 'eorzea.autoAdvance'

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
  // 0.1s 节拍：技能 CD 等时间数据按 0.1s 刷新展示
  const uiTick = ref(0)
  const bossResult = ref<BossResult | null>(null)
  const lastError = ref<string | null>(null)

  // 自动进入下一阶段：击杀 BOSS 后自动前往下一地区（本地偏好，持久化）
  const autoAdvance = ref(localStorage.getItem(AUTO_ADVANCE_KEY) === '1')

  function setAutoAdvance(value: boolean) {
    autoAdvance.value = value
    localStorage.setItem(AUTO_ADVANCE_KEY, value ? '1' : '0')
  }

  /** 高难副本：进行中的挑战与结算结果。 */
  const raid = ref<{ raidId: string; name: string } | null>(null)
  const raidSessionId = ref<number | null>(null)
  const raidResult = ref<RaidReportResponse | null>(null)

  /** 待开启的高难宝箱（可自选装备种类）。 */
  const raidChest = ref<{ count: number; slots: string[] }>({ count: 0, slots: [] })

  function setRaidChest(count: number, slots?: string[]) {
    raidChest.value = {
      count: Math.max(0, count),
      slots: slots && slots.length ? slots : raidChest.value.slots,
    }
  }

  async function claimRaidChest(slot: string) {
    try {
      const res = await api.raidChestClaim(slot)
      await loadState()
      setRaidChest(res.pendingChest)
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  let rafId = 0
  let tickTimer = 0
  let lastTs = 0
  let reportAccum = 0
  let reporting = false
  let raidReporting = false
  let generation = 0
  // 上一次成功上报的墙钟时间，用于上报真实窗口（空窗口不上报，固定值会失真）
  let lastReportAt = 0

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

  /** 副本战斗面板：各 BOSS 血量与狂暴状态。 */
  const raidBosses = computed<RaidBossEntry[]>(() => {
    void uiTick.value
    logVersion.value
    return sim.value?.bossEntries() ?? []
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
    if (raid.value) await stopRaid(true)
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
      lastReportAt = performance.now()
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
    tickTimer = window.setInterval(() => {
      uiTick.value += 1
    }, TICK_MS)
    const step = (ts: number) => {
      const dtMs = Math.min(400, ts - lastTs)
      lastTs = ts
      const dt = dtMs / 1000

      if (sim.value && running.value) {
        sim.value.tick(dt)
        sim.value.clearFloating()
        logVersion.value += 1

        if (raid.value) {
          // 副本只在「通关 / 阵亡」时上报一次，不做周期上报
          void finishRaidIfDone()
        } else {
          reportAccum += dtMs
          if (reportAccum >= REPORT_MS) {
            reportAccum = 0
            void report()
          }
        }
      }
      rafId = requestAnimationFrame(step)
    }
    rafId = requestAnimationFrame(step)
  }

  function stopLoop() {
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
    if (tickTimer) window.clearInterval(tickTimer)
    tickTimer = 0
  }

  async function report() {
    const current = sim.value
    const id = sessionId.value
    if (!current || id === null || reporting || !state.value) return

    const pending = current.drainPending()
    if (pending.kills.length === 0 && !pending.bossKilled && !pending.died) return

    reporting = true
    const gen = generation
    const elapsedMs = Math.min(20_000, Math.max(300, Math.round(performance.now() - lastReportAt)))
    try {
      const res = await api.reportBattle({
        sessionId: id,
        regionId: current.region?.id ?? 0,
        elapsedMs,
        kills: pending.kills as KillPayload[],
        skillCasts: Object.entries(pending.skillCasts).map(([skillId, count]) => ({ skillId, count })),
        killCount: current.killCount,
        bossKilled: pending.bossKilled,
        died: pending.died,
        bossFightMs: pending.bossFightMs || undefined,
      })
      if (gen !== generation) return
      lastReportAt = performance.now()
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
        toast.push(`获得 ${item.name}（${rarityName(item.rarity)}）`, 'loot')
      }
    }
    if (res.autoSold.length > 0) {
      toast.push(`自动出售 ${res.autoSold.length} 件装备，+${res.autoGold} 金币`, 'info')
    }

    current.applyServerKillCount(res.killCount, res.killsRequired)

    // 开启「自动进入下一阶段」时，击杀 BOSS 直接推进到下一地区，不弹结算窗
    let pendingAdvance = false
    if (res.boss) {
      if (autoAdvance.value && res.boss.nextRegionId) {
        bossResult.value = null
        pendingAdvance = true
      } else {
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
    }

    if (res.level.levelsGained > 0) {
      toast.push(`英雄升到 ${res.level.level} 级！`, 'success')
      if (!pendingAdvance) void refreshAfterGearChange()
    }

    if (pendingAdvance) {
      void advanceRegion().then((ok) => {
        if (ok) toast.push('已自动进入下一地区', 'info')
        // 推进失败（例如已是最后一个地区）：留在当前地区重新挂机
        else void startBattle()
      })
    }
  }

  function dismissBossResult() {
    bossResult.value = null
    // 留在当前地区：BOSS 已击败后模拟会停在 cleared，这里恢复小怪阶段继续挂机。
    sim.value?.continueAfterClear()
  }

  // ---------- 高难副本 ----------

  async function startRaid(raidId: string) {
    if (!state.value) return
    try {
      if (running.value || sessionId.value !== null) await stopBattle(true)
      const session = await api.raidStart(raidId)
      raid.value = { raidId: session.raidId, name: session.name }
      raidSessionId.value = session.sessionId
      raidResult.value = null
      sim.value = new BattleSimulator({
        stats: state.value.hero.stats,
        raid: { bosses: session.bosses, enrage: session.enrage, hard: session.difficulty === 'hard' },
      })
      sim.value.start()
      running.value = true
      logVersion.value += 1
      reportAccum = 0
      lastReportAt = performance.now()
      startLoop()
    } catch (e) {
      pushError(e)
    }
  }

  async function stopRaid(silent = false) {
    running.value = false
    stopLoop()
    sim.value?.pause()
    raid.value = null
    const id = raidSessionId.value
    raidSessionId.value = null
    if (id !== null) {
      try {
        await api.raidStop(id)
      } catch {
        /* 会话可能已结束，忽略 */
      }
    }
    if (!silent) toast.push('已退出副本', 'info')
  }

  function selectRaidTarget(index: number) {
    sim.value?.selectTarget(index)
    logVersion.value += 1
  }

  /** 副本结束时（通关或阵亡）上报一次并弹出结算。 */
  async function finishRaidIfDone() {
    const current = sim.value
    const id = raidSessionId.value
    if (!current || id === null || raidReporting) return
    if (current.phase !== 'cleared' && current.phase !== 'dead') return

    raidReporting = true
    running.value = false
    stopLoop()
    const cleared = current.phase === 'cleared'
    const fightMs = Math.round(current.bossFightMs)
    const elapsedMs = Math.max(300, Math.round(performance.now() - lastReportAt))
    const raidId = raid.value?.raidId ?? ''
    raid.value = null
    raidSessionId.value = null
    try {
      const res = await api.raidReport({
        sessionId: id,
        raidId,
        cleared,
        died: !cleared,
        elapsedMs,
        fightMs,
      })
      raidResult.value = res
      if (res.pendingChest) setRaidChest(res.pendingChest.count, res.pendingChest.slots)
      if (state.value) {
        state.value.user.gold = res.gold
        if (res.items.length > 0) {
          state.value.items = [...state.value.items, ...res.items]
          for (const item of res.items) {
            toast.push(`获得 ${item.name}（${rarityName(item.rarity)}）`, 'loot')
          }
        }
      }
      if (res.cleared) {
        toast.push(res.message, res.firstClear ? 'loot' : 'success')
      } else {
        toast.push(res.message, 'error')
      }
      if (res.level && res.level.levelsGained > 0) {
        toast.push(`英雄升到 ${res.level.level} 级！`, 'success')
      }
      await loadState()
    } catch (e) {
      pushError(e)
    } finally {
      raidReporting = false
    }
  }

  function dismissRaidResult() {
    raidResult.value = null
  }

  // ---------- 页面可见性：离开即暂停，不做离线收益 ----------

  function handleVisibility() {
    if (document.hidden) {
      // 副本留在客户端继续跑（不主动结束会话），地区战斗则离开即暂停
      if (running.value && !raid.value) void stopBattle(true)
    } else if (!running.value && sim.value && sessionId.value === null) {
      if (raid.value) {
        // 副本中途中断则重开一次挑战
        void startRaid(raid.value.raidId)
      } else if (state.value?.hero.currentRegionId) {
        void startBattle(sim.value.region?.id)
      }
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

  async function openChest(chestId: string, count: number, level?: number) {
    try {
      const res = await api.openChest(chestId, count, level)
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

  async function refine(itemId: number, mode: RerollMode = 'random') {
    try {
      const res = await api.refine(itemId, mode)
      toast.push(`重造完成，消耗 ${res.cost} 金币`, 'success')
      await loadState()
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function enchant(itemId: number, autoUntilRare = false, mode: RerollMode = 'random') {
    try {
      const res = await api.enchant(itemId, autoUntilRare, 100, mode)
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

  async function advanceRegion(): Promise<boolean> {
    try {
      if (running.value) await stopBattle(true)
      const res = await api.advanceRegion()
      await loadState()
      await startBattle((res as { region: { id: number } }).region.id)
      return true
    } catch (e) {
      pushError(e)
      return false
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
    raid.value = null
    raidSessionId.value = null
    raidResult.value = null
    raidChest.value = { count: 0, slots: [] }
    lastDraw.value = []
    lastReportAt = 0
  }

  return {
    state,
    loading,
    sim,
    sessionId,
    running,
    isRunning,
    uiTick,
    battleLog,
    floating,
    bossResult,
    autoAdvance,
    setAutoAdvance,
    lastError,
    lastDraw,
    loggedIn,
    hero,
    gold,
    items,
    loadout,
    raid,
    raidResult,
    raidBosses,
    raidChest,
    setRaidChest,
    claimRaidChest,
    loadState,
    startBattle,
    stopBattle,
    report,
    dismissBossResult,
    startRaid,
    stopRaid,
    selectRaidTarget,
    dismissRaidResult,
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
