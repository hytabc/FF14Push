import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import data from '@shared/schema'

import { api, type KillPayload } from '@/api'
import { toApiError } from '@/api/client'
import { sound } from '@/game/audio'
import { BattleSimulator } from '@/game/core/battle'
import type { AutoSoldItem, Category, GameState, Item, RaidBossEntry, RaidReportResponse, RerollMode, SlotId } from '@/game/types'

import { experienceLog, goldLog } from '@/utils/battleLog'

import { useAuthStore } from './auth'
import { useLootStore } from './loot'
import { useToastStore } from './toast'

const TICK_MS = 100
const REPORT_MS = 1500
/** `loadState` 的最小刷新间隔（毫秒）：突发调用会被合并为一次全量请求。 */
const STATE_MIN_INTERVAL_MS = 400
/** 单帧最多推进的模拟时间（毫秒），把后台补算分摊到多帧，避免卡住主线程。 */
const MAX_FRAME_MS = 400
/** 后台补算上限（毫秒）：页面存活期间按真实墙钟累计，切回前台后最多补齐这么多。 */
const CATCH_UP_MS = Number(data.combat.catchUpSeconds ?? 300) * 1000
const AUTO_ADVANCE_KEY = 'eorzea.autoAdvance'
const STAY_REGION_KEY = 'eorzea.stayRegion'

export interface BossResult {
  bossName: string
  gold: number
  exp: number
  firstClear: boolean
  nextRegionId: number | null
  unlockedDifficulty: number | null
  box: string | null
  items: Item[]
}

export const useGameStore = defineStore('game', () => {
  const auth = useAuthStore()
  const toast = useToastStore()
  const loot = useLootStore()

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

  // 原地挂机：选择「留在当前地区」后记录该地区，之后击败 BOSS 不再弹出结算窗
  // （本地偏好，持久化；切换地区后不再匹配，结算窗自然恢复）。
  const storedStay = Number(localStorage.getItem(STAY_REGION_KEY))
  const stayRegion = ref<number | null>(storedStay > 0 ? storedStay : null)

  function setStayRegion(regionId: number | null) {
    stayRegion.value = regionId
    if (regionId === null) localStorage.removeItem(STAY_REGION_KEY)
    else localStorage.setItem(STAY_REGION_KEY, String(regionId))
  }

  /** 当前战斗地区是否处于原地挂机。 */
  const isStaying = computed(() => {
    const active = sim.value?.region?.id ?? state.value?.hero.currentRegionId ?? null
    return active !== null && stayRegion.value === active
  })

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
  // 防加速：上次真实墙钟时间与尚未消耗的模拟时间预算
  let lastWallMs = 0
  let simBudgetMs = 0
  let reportAccum = 0
  let reporting = false
  let raidReporting = false
  let generation = 0
  // 上一次成功上报的墙钟时间，用于上报真实窗口（空窗口不上报，固定值会失真）
  let lastReportAt = 0
  // loadState 合并：在途请求、待补队列与上次刷新时刻
  let stateInflight: Promise<void> | null = null
  let statePending: { force: boolean } | null = null
  let stateLastAt = 0

  const loggedIn = computed(() => auth.isLoggedIn)
  const hero = computed(() => state.value?.hero ?? null)
  const gold = computed(() => state.value?.user.gold ?? 0)
  const items = computed(() => state.value?.items ?? [])
  const tags = computed(() => state.value?.tags ?? [])
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

  /**
   * 副本战斗面板：各 BOSS 血量与狂暴状态。
   *
   * 只依赖 0.1s 节拍（`uiTick`）而**不**依赖每帧的 `logVersion`：`bossEntries()` 每次求值
   * 都会新建数组与对象，挂在每帧上会让副本页整页 60fps 重渲染。血量按 10Hz 刷新已足够。
   */
  const raidBosses = computed<RaidBossEntry[]>(() => {
    void uiTick.value
    return sim.value?.bossEntries() ?? []
  })

  function pushError(e: unknown) {
    const err = toApiError(e)
    // 封号由全局响应拦截器静默处理（清空会话 → 空白页），此处不再弹任何提示。
    if (err.code === 'banned') return
    // 会话被顶替 / 设备并发超限都由全局拦截器与心跳接管（清会话 / 暂停循环），不弹错误。
    if (err.code === 'session_replaced' || err.code === 'device_limit') return
    lastError.value = err.message
    toast.push(err.message, 'error')
    if (err.status === 401) auth.logout()
  }

  async function runState() {
    stateLastAt = performance.now()
    loading.value = true
    try {
      state.value = await api.state()
    } catch (e) {
      pushError(e)
    } finally {
      loading.value = false
    }
  }

  /**
   * 拉取全量游戏状态（`/game/state` 是最重的读接口）。
   *
   * 突发调用会被**合并**：距上次刷新不足 `coalesceMs` 的调用共享同一次请求，
   * 在途期间的调用记为「结束后补一次」，因此装备变更 / 抽箱 / 采集上报等
   * 密集动作不会各发一次全量请求。关键路径（登录、装备变更）传 `{ force: true }` 立即生效。
   */
  function loadState(opts: { force?: boolean; coalesceMs?: number } = {}): Promise<void> {
    if (!auth.isLoggedIn) return Promise.resolve()
    const coalesce = Math.max(0, opts.coalesceMs ?? STATE_MIN_INTERVAL_MS)
    const force = Boolean(opts.force)

    if (stateInflight) {
      if (!statePending || force) statePending = { force }
      return stateInflight
    }

    const since = performance.now() - stateLastAt
    const delay = force ? 0 : Math.max(0, coalesce - since)
    stateInflight = new Promise<void>((resolve) => {
      setTimeout(resolve, delay)
    }).then(async () => {
      await runState()
      // 在途期间又来了请求：补一次，保证最终状态是最新的。
      while (statePending) {
        const next = statePending
        statePending = null
        if (next.force || performance.now() - stateLastAt >= STATE_MIN_INTERVAL_MS) {
          await runState()
        }
      }
      stateInflight = null
    })
    return stateInflight
  }

  /** 装备变更后重新计算面板并同步给模拟器。 */
  async function refreshAfterGearChange() {
    await loadState({ force: true })
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
        penalty: session.penalty,
        regionId: target,
        killsRequired: session.killsRequired,
        spawnInterval: session.spawnInterval,
        killCount: 0,
        difficulty: session.difficulty,
        eggId: state.value.hero.eggId,
        onSound: (cue) => sound.play(cue),
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
    // 防加速 + 后台补算：模拟时间只能来自真实墙钟（Date.now），不采信
    // requestAnimationFrame 的时间戳（可被扩展篡改）。页面切到后台时 rAF 暂停，
    // 切回后把这段时间一次性计入预算，单次上限 CATCH_UP_MS（同时限制系统时钟跳变作弊）；
    // 关闭页面后不再有上报，也就不会有补算。
    lastWallMs = Date.now()
    simBudgetMs = 0
    tickTimer = window.setInterval(() => {
      uiTick.value += 1
    }, TICK_MS)
    const step = () => {
      const wallNow = Date.now()
      const wallDelta = Math.min(CATCH_UP_MS, Math.max(0, wallNow - lastWallMs))
      lastWallMs = wallNow
      simBudgetMs = Math.min(CATCH_UP_MS, simBudgetMs + wallDelta)

      // 单帧最多推进 MAX_FRAME_MS，剩余预算在后续帧补齐。
      const dtMs = Math.min(MAX_FRAME_MS, simBudgetMs)
      simBudgetMs -= dtMs
      const dt = dtMs / 1000

      if (sim.value && running.value) {
        sim.value.tick(dt)
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
      // 上报了 BOSS 击杀但服务端未结算（小怪计数尚未对齐）：模拟会停在 cleared 且不再
      // 产生事件，若不恢复将永远无法进入下一地区。退回小怪阶段继续上报直至结算成功。
      if (pending.bossKilled && !res.boss) current.resumeAfterDroppedBoss()
    } catch (e) {
      const err = toApiError(e)
      // 会话已被服务端结束（开始远征/竞技场/切换英雄/其它标签页等）：本地静默停战，
      // 不再重试上报或弹窗，避免「战斗会话不存在或已结束」反复弹出。
      if (err.status === 404) {
        running.value = false
        stopLoop()
        sessionId.value = null
        current.pause()
        return
      }
      current.restorePending(pending)
      pushError(e)
    } finally {
      reporting = false
    }
  }

  function applyReport(res: Awaited<ReturnType<typeof api.reportBattle>>) {
    const current = sim.value
    if (!state.value || !current) return

    if (res.expGained > 0) current.recordReward(experienceLog(res.expGained, res.expCalculation))
    if (res.goldGained > 0) current.recordReward(goldLog(res.goldGained, res.goldCalculation))
    if (res.boss) {
      current.recordReward(res.boss.bossName + '：' + experienceLog(res.boss.exp, res.boss.expCalculation))
      if (res.boss.gold > 0) current.recordReward(res.boss.bossName + '：' + goldLog(res.boss.gold, res.boss.goldCalculation))
    }
    logVersion.value += 1
    state.value.user.gold = res.gold
    state.value.hero.level = res.level.level
    state.value.hero.exp = res.level.exp
    if (res.goldGained > 0) {
      // 金币变化即时反映
      state.value.itemCounts = { ...state.value.itemCounts }
    }

    showLoot(res.items)
    if (res.autoSold.length > 0) {
      toast.push(`自动出售 ${res.autoSold.length} 件装备，+${res.autoGold} 金币`, 'info')
    }

    current.applyServerKillCount(res.killCount, res.killsRequired)

    // 开启「自动进入下一阶段」时，击杀 BOSS 直接推进到下一地区，不弹结算窗
    let pendingAdvance = false
    if (res.boss) {
      // 地区战斗的装备只来自 BOSS 宝箱（怪物不掉落），掉落以气泡提示
      showLoot(res.boss.items)
      showAutoSold(res.boss.autoSold)

      if (res.boss.unlockedDifficulty) {
        toast.push(`已解锁难度 ${res.boss.unlockedDifficulty}！`, 'loot')
        // 立即刷新状态，让难度选择器出现新解锁的档位（否则需手动刷新页面才可见）。
        void loadState()
      }

      if (autoAdvance.value && res.boss.nextRegionId) {
        bossResult.value = null
        pendingAdvance = true
      } else if (isStaying.value) {
        // 原地挂机：不再弹结算窗，直接继续刷本地区的小怪。
        bossResult.value = null
        current.continueAfterClear()
      } else {
        bossResult.value = {
          bossName: res.boss.bossName,
          gold: res.boss.gold,
          exp: res.boss.exp,
          firstClear: res.boss.firstClear,
          nextRegionId: res.boss.nextRegionId,
          unlockedDifficulty: res.boss.unlockedDifficulty,
          box: res.boss.box,
          items: res.boss.items,
        }
      }
    }

    if (res.level.levelsGained > 0) {
      toast.push(`英雄升到 ${res.level.level} 级！`, 'success')
      sound.play('battle.levelup')
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

  /** 掉落物品：并入背包并以气泡提示。 */
  function showLoot(items: Item[]) {
    if (items.length === 0 || !state.value) return
    state.value.items = [...state.value.items, ...items]
    for (const item of items) {
      loot.push({ baseId: item.baseId, name: item.name, rarity: item.rarity })
    }
  }

  /** 自动出售的掉落同样以气泡提示。 */
  function showAutoSold(sold: AutoSoldItem[]) {
    for (const item of sold) {
      loot.push({
        baseId: item.baseId,
        name: item.name,
        rarity: item.rarity,
        note: `自动出售 +${item.price}`,
      })
    }
  }

  function dismissBossResult() {
    bossResult.value = null
    // 留在当前地区：BOSS 已击败后模拟会停在 cleared，这里恢复小怪阶段继续挂机。
    sim.value?.continueAfterClear()
  }

  /** 「留在当前地区」：记录该地区为原地挂机，之后击败 BOSS 不再弹出结算窗。 */
  function stayInCurrentRegion() {
    const regionId = sim.value?.region?.id ?? state.value?.hero.currentRegionId ?? null
    if (regionId !== null) setStayRegion(regionId)
    dismissBossResult()
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
        penalty: session.penalty,
        raid: { bosses: session.bosses, enrage: session.enrage },
        eggId: state.value.hero.eggId,
        onSound: (cue) => sound.play(cue),
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
        mechanismFailures: current.mechanismFailures,
        sessionId: id,
        raidId,
        cleared,
        died: !cleared,
        elapsedMs,
        fightMs,
      })
      raidResult.value = res
      if (res.cleared) current.recordReward('副本通关：' + experienceLog(res.expGained, res.expCalculation))
      if (res.goldGained > 0) current.recordReward('副本通关：' + goldLog(res.goldGained, res.goldCalculation))
      logVersion.value += 1
      if (res.pendingChest) setRaidChest(res.pendingChest.count, res.pendingChest.slots)
      if (state.value) state.value.user.gold = res.gold
      showLoot(res.items)
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

  // ---------- 装备标签 ----------

  async function createTag(name: string, color: string) {
    try {
      const res = await api.createTag(name, color)
      await loadState()
      return res.tag
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function updateTag(id: number, patch: { name?: string; color?: string }) {
    try {
      const res = await api.updateTag(id, patch)
      await loadState()
      return res.tag
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function deleteTag(id: number) {
    try {
      await api.deleteTag(id)
      await loadState()
      return true
    } catch (e) {
      pushError(e)
      return false
    }
  }

  async function setItemTags(itemId: number, tagIds: number[]) {
    try {
      const res = await api.setItemTags(itemId, tagIds)
      // 就地更新，避免整包刷新导致列表滚动位置丢失
      if (state.value) {
        const idx = state.value.items.findIndex((i) => i.id === itemId)
        if (idx >= 0) state.value.items[idx] = res.item
        const slot = res.item.equippedSlot
        if (slot && state.value.loadout[slot]) state.value.loadout[slot] = res.item
      }
      return res.item
    } catch (e) {
      pushError(e)
      return null
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

  /** 一次性金币解锁连抽档位（如 50 / 100 连）。账号级，解锁后所有箱子通用。 */
  async function unlockChestDraw(count: number) {
    try {
      const res = await api.unlockChestDraw(count)
      if (state.value) {
        state.value.user.gold = res.gold
        state.value.settings.chestUnlocks = res.unlocked
      }
      toast.push(`已解锁 ${count} 连抽`, 'success')
      return true
    } catch (e) {
      pushError(e)
      return false
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

  async function refine(itemId: number, mode: RerollMode = 'random', times = 1) {
    try {
      const res = await api.refine(itemId, mode, times)
      toast.push(`重造完成 ${res.times} 次，消耗 ${res.cost} 金币`, 'success')
      await loadState()
      return res
    } catch (e) {
      pushError(e)
      return null
    }
  }

  async function enchant(itemId: number, autoUntilRare = false, mode: RerollMode = 'random', times = 1) {
    try {
      const res = await api.enchant(itemId, autoUntilRare, 100, mode, times)
      toast.push(
        autoUntilRare
          ? `自动附魔 ${res.attempts} 次，消耗 ${res.cost} 金币${res.hit ? '，出现稀有/太古词条！' : ''}`
          : `附魔完成 ${res.times ?? res.attempts} 次，消耗 ${res.cost} 金币`,
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

  /** 切换地区战斗难度（仅限已解锁范围）；切换后落回该难度下「已通关最高地区 +1」。 */
  async function setDifficulty(level: number): Promise<boolean> {
    if (state.value?.difficulty?.level === level) return true
    try {
      if (running.value) await stopBattle(true)
      const res = await api.setDifficulty(level)
      await loadState()
      await startBattle(res.currentRegionId)
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
    loot.clear()
    lastReportAt = 0
    stateInflight = null
    statePending = null
    stateLastAt = 0
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
    stayRegion,
    setStayRegion,
    isStaying,
    lastError,
    lastDraw,
    loggedIn,
    hero,
    gold,
    items,
    tags,
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
    stayInCurrentRegion,
    startRaid,
    stopRaid,
    selectRaidTarget,
    dismissRaidResult,
    equip,
    unequip,
    sell,
    createTag,
    updateTag,
    deleteTag,
    setItemTags,
    openChest,
    unlockChestDraw,
    craft,
    refine,
    enchant,
    enterRegion,
    advanceRegion,
    setDifficulty,
    refreshAfterGearChange,
    reset,
    TICK_MS,
  }
})
