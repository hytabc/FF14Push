<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { TavernCandidate } from '@/game/types'
import { formatNumber, jobName, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const candidate = ref<TavernCandidate | null>(null)
const currentHero = ref<Record<string, unknown> | null>(null)
const refreshCost = ref(200)
const tenPullCost = ref(2000)
const multiCandidates = ref<TavernCandidate[]>([])
const loading = ref(false)
const busy = ref(false)
const confirmRecruit = ref(false)
const confirmMultiIndex = ref<number | null>(null)
const nextFreeAt = ref<number | null>(null)
const nowMs = ref(Date.now())
let timer: number | undefined

const hero = computed(() => game.hero)
const canAfford = computed(() => (candidate.value?.recruitCost ?? 0) <= game.gold)
const shortfall = computed(() => Math.max(0, (candidate.value?.recruitCost ?? 0) - game.gold))
const canAffordTenPull = computed(() => tenPullCost.value <= game.gold)
const pickedMulti = computed(() =>
  confirmMultiIndex.value === null ? null : (multiCandidates.value[confirmMultiIndex.value] ?? null),
)
const freeRemainingSec = computed(() =>
  nextFreeAt.value ? Math.max(0, Math.ceil((nextFreeAt.value - nowMs.value) / 1000)) : 0,
)
const freeAvailable = computed(() => freeRemainingSec.value <= 0)

function mmss(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  try {
    const res = await api.tavern()
    candidate.value = res.candidate
    currentHero.value = res.currentHero
    refreshCost.value = res.refreshCost
    tenPullCost.value = res.tenPullCost
    multiCandidates.value = res.multiCandidates ?? []
    nextFreeAt.value = res.nextFreeRefreshAt ? Date.parse(res.nextFreeRefreshAt) : null
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  timer = window.setInterval(() => (nowMs.value = Date.now()), 1000)
  if (!game.state) await game.loadState()
  await load()
})

onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
})

async function refresh(useGold: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.tavernRefresh(useGold)
    candidate.value = res.candidate
    if (game.state) game.state.user.gold = res.gold
    nextFreeAt.value = res.nextFreeRefreshAt ? Date.parse(res.nextFreeRefreshAt) : null
    toast.push(res.cost > 0 ? `消耗 ${res.cost} 金币刷新` : '已免费刷新候选英雄', 'info')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function tenPull() {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.tavernTenPull()
    multiCandidates.value = res.candidates
    if (game.state) game.state.user.gold = res.gold
    toast.push(`十连抽完成，消耗 ${formatNumber(res.cost)} 金币，可选择 1 名英雄招募`, 'success')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function clearMulti() {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.tavernTenPullClear()
    multiCandidates.value = []
    toast.push(res.message, 'info')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function openConfirm() {
  if (busy.value) return
  // 招募按英雄「当前」等级计费：确认前先刷新一次，避免升级后价格与服务端不一致。
  await load()
  confirmRecruit.value = true
}

async function recruit() {
  confirmRecruit.value = false
  busy.value = true
  try {
    const res = await api.tavernRecruit(true)
    toast.push('招募成功！新英雄已加入，旧英雄装备已卸下保留', 'success')
    await game.loadState()
    if (game.isRunning) await game.startBattle()
    void res
    await load()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function recruitMulti() {
  const index = confirmMultiIndex.value
  if (index === null) return
  confirmMultiIndex.value = null
  busy.value = true
  try {
    const res = await api.tavernTenPullRecruit(index, true)
    toast.push('招募成功！新英雄已加入，旧英雄装备已卸下保留', 'success')
    await game.loadState()
    if (game.isRunning) await game.startBattle()
    void res
    await load()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function dismiss() {
  busy.value = true
  try {
    const res = await api.tavernDismiss()
    toast.push((res as { message: string }).message, 'info')
    await game.loadState()
    await load()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

function attrBar(value: number, total: number) {
  return total > 0 ? (value / total) * 100 : 0
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">英雄酒馆</h2>
        <span class="text-xs text-ink-400">英雄栏位上限 1 名，招募新英雄将替换当前英雄</span>
        <span class="ml-auto font-mono text-sm text-amber-300">💰 {{ game.gold.toLocaleString() }}</span>
      </div>
    </section>

    <div class="grid gap-4 lg:grid-cols-2">
      <section class="card p-4">
        <h3 class="text-sm font-semibold text-white">当前英雄</h3>
        <div v-if="hero" class="mt-3 space-y-1 text-xs">
          <p class="text-ink-100">{{ hero.name }}</p>
          <p class="text-ink-400">
            Lv.{{ hero.level }} · {{ jobName(hero.jobId) }} ·
            <span :class="rarityClass(hero.talent)">{{ rarityName(hero.talent) }}资质</span>
          </p>
          <p class="text-ink-400">
            力量 {{ hero.strength }}{{ hero.ancientAttr === 'str' ? '🌟' : '' }} /
            敏捷 {{ hero.agility }}{{ hero.ancientAttr === 'dex' ? '🌟' : '' }} /
            智力 {{ hero.intellect }}{{ hero.ancientAttr === 'int' ? '🌟' : '' }}
          </p>
          <p v-if="hero.isInitial" class="text-[11px] text-amber-300">
            初始英雄不可解雇，请先招募新英雄进行替换
          </p>
          <button
            v-if="!hero.isInitial"
            class="mt-3 rounded-md bg-rose-600/80 px-3 py-2 text-xs text-white hover:bg-rose-500 disabled:opacity-50"
            :disabled="busy"
            @click="dismiss"
          >
            解雇英雄（装备保留）
          </button>
        </div>
        <p v-else class="mt-3 text-xs text-ink-500">当前没有英雄，可花费金币招募一名。</p>
      </section>

      <section class="card p-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white">候选英雄</h3>
          <div class="flex gap-2">
            <button
              class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600 disabled:opacity-50"
              :disabled="busy || loading || !freeAvailable"
              @click="refresh(false)"
            >
              {{ freeAvailable ? '免费刷新（每 10 分钟 1 次）' : `免费刷新（${mmss(freeRemainingSec)} 后可再用）` }}
            </button>
            <button
              class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600 disabled:opacity-50"
              :disabled="busy || loading"
              @click="refresh(true)"
            >
              花 {{ refreshCost }} 金币刷新
            </button>
          </div>
        </div>

        <div v-if="candidate" class="mt-3 space-y-3">
          <div class="flex items-center gap-2">
            <p class="text-sm text-ink-100">{{ candidate.name }}</p>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px]" :class="rarityClass(candidate.talent)">
              {{ rarityName(candidate.talent) }}
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
              {{ candidate.attrBiasLabel }}
            </span>
          </div>

          <div class="space-y-1.5">
            <div v-for="row in [
              { key: 'str', label: '力量', value: candidate.strength, color: 'bg-rose-400' },
              { key: 'dex', label: '敏捷', value: candidate.agility, color: 'bg-emerald-400' },
              { key: 'int', label: '智力', value: candidate.intellect, color: 'bg-sky-400' },
            ]" :key="row.key" class="flex items-center gap-2 text-[11px]">
              <span class="w-8 text-ink-400">{{ row.label }}</span>
              <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                <div class="h-full rounded-full" :class="row.color" :style="{ width: `${Math.min(100, attrBar(row.value, 260) * 3)}%` }" />
              </div>
              <span class="w-12 text-right font-mono text-ink-200">
                {{ row.value }}<span v-if="candidate.ancientAttr === row.key">🌟</span>
              </span>
            </div>
          </div>

          <p class="text-[11px] text-ink-400">
            总点数 {{ candidate.totalPoints }} · 推荐职业：
            {{ candidate.recommendedJobs.slice(0, 4).map((j) => jobName(j)).join('、') }}
            {{ candidate.recommendedJobs.length > 4 ? ' 等' : '' }}
          </p>

          <button
            class="w-full rounded-md py-2.5 text-sm font-medium transition disabled:opacity-40"
            :class="canAfford ? 'bg-amber-500 text-ink-950 hover:bg-amber-400' : 'bg-ink-700 text-ink-400'"
            :disabled="!canAfford || busy"
            @click="openConfirm"
          >
            招募 · {{ formatNumber(candidate.recruitCost) }} 金币
          </button>
          <p v-if="!canAfford" class="text-[11px] text-rose-300">
            金币不足，还差 {{ formatNumber(shortfall) }} 金币
          </p>
          <p class="text-[10px] text-ink-600">
            招募费用 = 基础费用 × 资质系数 × (1 + 当前英雄等级 / 10)
          </p>
        </div>
      </section>
    </div>

    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h3 class="text-sm font-semibold text-white">十连抽</h3>
        <span class="text-[11px] text-ink-400">
          一次刷出 10 名候选英雄，可从其中招募 1 名（按其招募费用结算）或全部放弃
        </span>
        <div class="ml-auto flex gap-2">
          <button
            v-if="multiCandidates.length"
            class="rounded bg-ink-700 px-3 py-1.5 text-[11px] hover:bg-ink-600 disabled:opacity-50"
            :disabled="busy"
            @click="clearMulti"
          >
            都不购买
          </button>
          <button
            class="rounded-md px-4 py-1.5 text-[11px] font-medium transition disabled:opacity-40"
            :class="canAffordTenPull ? 'bg-indigo-500 text-white hover:bg-indigo-400' : 'bg-ink-700 text-ink-400'"
            :disabled="busy || loading || !canAffordTenPull"
            @click="tenPull"
          >
            十连抽 · {{ formatNumber(tenPullCost) }} 金币
          </button>
        </div>
      </div>

      <div v-if="multiCandidates.length" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <div
          v-for="(c, idx) in multiCandidates"
          :key="idx"
          class="rounded-lg border border-ink-700 bg-ink-800/60 p-2 text-[11px]"
        >
          <div class="flex items-center gap-1">
            <span class="truncate text-ink-100">{{ c.name }}</span>
            <span class="ml-auto rounded bg-ink-900 px-1 text-[10px]" :class="rarityClass(c.talent)">
              {{ rarityName(c.talent) }}
            </span>
          </div>
          <p class="text-[10px] text-ink-400">{{ c.attrBiasLabel }} · 总 {{ c.totalPoints }}</p>
          <p class="font-mono text-[10px] text-ink-300">
            力 {{ c.strength }}{{ c.ancientAttr === 'str' ? '🌟' : '' }} /
            敏 {{ c.agility }}{{ c.ancientAttr === 'dex' ? '🌟' : '' }} /
            智 {{ c.intellect }}{{ c.ancientAttr === 'int' ? '🌟' : '' }}
          </p>
          <button
            class="mt-1.5 w-full rounded bg-amber-500 px-2 py-1 text-[10px] font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-40"
            :disabled="busy || c.recruitCost > game.gold"
            @click="confirmMultiIndex = idx"
          >
            招募 · {{ formatNumber(c.recruitCost) }}
          </button>
        </div>
      </div>
      <p v-else class="mt-3 text-xs text-ink-500">尚未十连抽，点击右上角按钮开始。</p>
    </section>

    <Modal :open="confirmRecruit" title="确认招募并替换英雄" @close="confirmRecruit = false">
      <p class="text-sm text-ink-200">
        将<b class="text-rose-300">替换当前英雄</b>：当前英雄装备会自动卸下并返回背包，
        <b class="text-rose-300">等级与经验不保留</b>。新英雄以 1 级加入。
      </p>
      <p v-if="candidate" class="mt-3 text-xs text-ink-400">
        新英雄：{{ candidate.name }} · {{ rarityName(candidate.talent) }} · {{ candidate.attrBiasLabel }} ·
        力量 {{ candidate.strength }} / 敏捷 {{ candidate.agility }} / 智力 {{ candidate.intellect }}
      </p>
      <p v-if="candidate" class="mt-2 text-xs text-amber-300">
        将消耗 {{ formatNumber(candidate.recruitCost) }} 金币（当前持有 💰 {{ game.gold.toLocaleString() }}）
      </p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmRecruit = false">
          取消
        </button>
        <button class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950" @click="recruit">
          确认招募
        </button>
      </template>
    </Modal>

    <Modal
      :open="confirmMultiIndex !== null"
      title="确认招募并替换英雄"
      @close="confirmMultiIndex = null"
    >
      <p class="text-sm text-ink-200">
        将<b class="text-rose-300">替换当前英雄</b>：当前英雄装备会自动卸下并返回背包，
        <b class="text-rose-300">等级与经验不保留</b>。新英雄以 1 级加入。
      </p>
      <p v-if="pickedMulti" class="mt-3 text-xs text-ink-400">
        新英雄：{{ pickedMulti.name }} · {{ rarityName(pickedMulti.talent) }} · {{ pickedMulti.attrBiasLabel }} ·
        力量 {{ pickedMulti.strength }}{{ pickedMulti.ancientAttr === 'str' ? '🌟' : '' }} /
        敏捷 {{ pickedMulti.agility }}{{ pickedMulti.ancientAttr === 'dex' ? '🌟' : '' }} /
        智力 {{ pickedMulti.intellect }}{{ pickedMulti.ancientAttr === 'int' ? '🌟' : '' }}
      </p>
      <p v-if="pickedMulti" class="mt-2 text-xs text-amber-300">
        将消耗 {{ formatNumber(pickedMulti.recruitCost) }} 金币（当前持有 💰 {{ game.gold.toLocaleString() }}）
      </p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmMultiIndex = null">
          取消
        </button>
        <button class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950" @click="recruitMulti">
          确认招募
        </button>
      </template>
    </Modal>
  </div>
</template>
