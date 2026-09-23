<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import InfoTip from '@/components/InfoTip.vue'
import Modal from '@/components/Modal.vue'
import { ancientPityExplain, recruitCostExplain, talentExplain } from '@/game/explanations'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { RarityId, TavernCandidate } from '@/game/types'
import { formatNumber, jobName, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const candidate = ref<TavernCandidate | null>(null)
const currentHero = ref<Record<string, unknown> | null>(null)
const refreshCost = ref(200)
const tenPullCost = ref(2000)
const multiCandidates = ref<TavernCandidate[]>([])
const ancientPity = ref({ count: 0, threshold: 500 })
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

/** 神话资质、带太古属性或彩蛋英雄＝有效英雄，刷新/放弃前需要二次确认。 */
function isPrecious(c: TavernCandidate | null | undefined): boolean {
  return !!c && (c.talent === 'mythic' || c.ancientAttr !== null || !!c.eggId)
}

const candidatePrecious = computed(() => isPrecious(candidate.value))
const preciousMulti = computed(() => multiCandidates.value.filter(isPrecious))

// 待确认的「会丢英雄」操作
const pendingKind = ref<null | 'refresh' | 'tenPull' | 'clearMulti'>(null)
const pendingUseGold = ref(false)

const preciousToLose = computed<TavernCandidate[]>(() =>
  pendingKind.value === 'refresh' ? (candidate.value ? [candidate.value] : []) : preciousMulti.value,
)

const discardTitle = computed(() => {
  switch (pendingKind.value) {
    case 'refresh':
      return '确认刷新候选英雄？'
    case 'tenPull':
      return '确认十连抽？'
    case 'clearMulti':
      return '确认放弃本批候选？'
    default:
      return ''
  }
})

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
    ancientPity.value = res.ancientPity
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
    if (res.ancientPity) ancientPity.value = res.ancientPity
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
    if (res.ancientPity) ancientPity.value = res.ancientPity
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
    toast.push('招募成功！新英雄已加入名册，可在英雄名册中切换出战', 'success')
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
    toast.push('招募成功！新英雄已加入名册，可在英雄名册中切换出战', 'success')
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
    const res = await api.tavernDismiss(game.hero?.id ?? 0)
    toast.push((res as { message: string }).message, 'info')
    await game.loadState()
    await load()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

function requestRefresh(useGold: boolean) {
  if (busy.value) return
  // 当前候选是神话/太古时先确认，避免把有效英雄刷新掉
  if (candidatePrecious.value) {
    pendingUseGold.value = useGold
    pendingKind.value = 'refresh'
    return
  }
  void refresh(useGold)
}

function requestTenPull() {
  if (busy.value) return
  // 换一批十连会丢掉尚未招募的候选，其中若有神话/太古需先确认
  if (preciousMulti.value.length) {
    pendingKind.value = 'tenPull'
    return
  }
  void tenPull()
}

function requestClearMulti() {
  if (busy.value) return
  if (preciousMulti.value.length) {
    pendingKind.value = 'clearMulti'
    return
  }
  void clearMulti()
}

function cancelDiscard() {
  pendingKind.value = null
}

async function confirmDiscard() {
  const kind = pendingKind.value
  const useGold = pendingUseGold.value
  pendingKind.value = null
  if (kind === 'refresh') await refresh(useGold)
  else if (kind === 'tenPull') await tenPull()
  else if (kind === 'clearMulti') await clearMulti()
}

function attrBar(value: number, total: number) {
  return total > 0 ? (value / total) * 100 : 0
}

// 概率说明：资质权重 / 太古保底 / 招募费用公式
const talentInfo = talentExplain()
const ancientPityInfo = computed(() => ancientPityExplain(ancientPity.value.count, ancientPity.value.threshold))
const talentWeightRows = computed(() =>
  data.talents.order.map((rarity) => ({ rarity: rarity as RarityId, weight: data.talents.talentWeights[rarity] ?? 0 })),
)
function fmtWeight(weight: number): string {
  const value = (weight ?? 0) * 100
  return `${value % 1 === 0 ? value.toFixed(0) : value.toFixed(1)}%`
}
function recruitInfo(candidate: TavernCandidate) {
  return recruitCostExplain(hero.value?.level ?? 1, candidate.talent, candidate.recruitCost)
}

/** 彩蛋英雄说明文案（无彩蛋返回空串）。 */
function eggDesc(eggId: string | null | undefined): string {
  return eggId ? (data.eggHeroes.byId[eggId]?.desc ?? '彩蛋英雄') : ''
}

const eggChancePct = computed(() => `${(data.eggHeroes.eggChance * 100).toFixed(1)}%`)
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">英雄酒馆</h2>
        <span class="text-xs text-ink-400">英雄名册上限 8 名，新英雄独立养成，不替换现有英雄</span>
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
          <p v-if="hero.eggId" class="text-[11px] text-fuchsia-300">
            🎁 彩蛋英雄 · {{ eggDesc(hero.eggId) }}
          </p>
          <p v-if="(game.state?.heroes?.length ?? 1) <= 1" class="text-[11px] text-amber-300">
            至少保留一名英雄，无法全部解雇
          </p>
          <button
            class="mt-3 rounded-md bg-rose-600/80 px-3 py-2 text-xs text-white hover:bg-rose-500 disabled:opacity-50"
            :disabled="busy || (game.state?.heroes?.length ?? 1) <= 1"
            @click="dismiss"
          >
            解雇英雄（装备保留）
          </button>
        </div>
        <p v-else class="mt-3 text-xs text-ink-500">当前没有英雄，可花费金币招募一名。</p>
      </section>

      <section data-tutorial="recruit" class="card p-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-white">候选英雄</h3>
          <div class="flex gap-2">
            <button
              class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600 disabled:opacity-50"
              :disabled="busy || loading || !freeAvailable"
              @click="requestRefresh(false)"
            >
              {{ freeAvailable ? '免费刷新（每 10 分钟 1 次）' : `免费刷新（${mmss(freeRemainingSec)} 后可再用）` }}
            </button>
            <button
              class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600 disabled:opacity-50"
              :disabled="busy || loading"
              @click="requestRefresh(true)"
            >
              花 {{ refreshCost }} 金币刷新
            </button>
          </div>
        </div>

        <p class="mt-2 text-[11px] text-term-ancient">
          🌟 太古保底：{{ ancientPity.count }} / {{ ancientPity.threshold }}
          （每 {{ ancientPity.threshold }} 个候选必出一次「太古属性英雄」）
          <InfoTip :title="ancientPityInfo.title">
            <p v-for="(line, i) in ancientPityInfo.lines" :key="i">{{ line }}</p>
          </InfoTip>
        </p>
        <p class="mt-1 text-[11px] text-ink-400">
          资质概率：
          <span v-for="(row, idx) in talentWeightRows" :key="row.rarity">
            <span :class="rarityClass(row.rarity)">{{ rarityName(row.rarity) }}</span> {{ fmtWeight(row.weight) }}<span
              v-if="idx < talentWeightRows.length - 1"
              class="text-ink-600"
            >
              /
            </span>
          </span>
          <InfoTip :title="talentInfo.title">
            <p v-for="(line, i) in talentInfo.lines" :key="i">{{ line }}</p>
          </InfoTip>
        </p>

        <p class="mt-1 text-[11px] text-fuchsia-300">
          🎁 彩蛋英雄：{{ eggChancePct }} 共用概率（不影响上方资质概率，命中后随机出现一位）
        </p>

        <p v-if="candidatePrecious" class="mt-2 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
          当前候选为<b>神话 / 太古 / 彩蛋</b>有效英雄，刷新前会二次确认。
        </p>

        <div v-if="candidate" class="mt-3 space-y-3">
          <div class="flex items-center gap-2">
            <p class="text-sm text-ink-100">{{ candidate.name }}</p>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px]" :class="rarityClass(candidate.talent)">
              {{ rarityName(candidate.talent) }}
            </span>
            <span class="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
              {{ candidate.attrBiasLabel }}
            </span>
            <span v-if="candidate.eggId" class="rounded bg-fuchsia-500/20 px-2 py-0.5 text-[11px] text-fuchsia-300">
              🎁 彩蛋
            </span>
          </div>

          <p v-if="candidate.eggId" class="text-[11px] text-fuchsia-300">
            {{ eggDesc(candidate.eggId) }}
          </p>

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
            <InfoTip :title="recruitInfo(candidate).title">
              <p v-for="(line, i) in recruitInfo(candidate).lines" :key="i">{{ line }}</p>
            </InfoTip>
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
            @click="requestClearMulti"
          >
            都不购买
          </button>
          <button
            class="rounded-md px-4 py-1.5 text-[11px] font-medium transition disabled:opacity-40"
            :class="canAffordTenPull ? 'bg-indigo-500 text-white hover:bg-indigo-400' : 'bg-ink-700 text-ink-400'"
            :disabled="busy || loading || !canAffordTenPull"
            @click="requestTenPull"
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
          <p class="text-[10px] text-ink-400">
            {{ c.attrBiasLabel }} · 总 {{ c.totalPoints }}<span v-if="c.eggId" class="text-fuchsia-300"> · 🎁彩蛋</span>
          </p>
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

    <Modal :open="confirmRecruit" title="确认招募英雄" @close="confirmRecruit = false">
      <p class="text-sm text-ink-200">
        新英雄以 1 级加入名册，当前英雄的等级、经验和装备全部保留。最多拥有 8 名英雄。
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
      title="确认招募英雄"
      @close="confirmMultiIndex = null"
    >
      <p class="text-sm text-ink-200">
        新英雄以 1 级加入名册，当前英雄的等级、经验和装备全部保留。最多拥有 8 名英雄。
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

    <Modal :open="pendingKind !== null" :title="discardTitle" @close="cancelDiscard">
      <p class="text-sm text-ink-200">
        检测到<b class="text-term-ancient">神话 / 太古</b>候选英雄。继续操作会使以下英雄
        <b class="text-rose-300">永久丢失</b>（未被招募的候选不会保留）。
      </p>
      <ul class="mt-3 space-y-1 text-xs text-ink-300">
        <li v-for="(c, idx) in preciousToLose" :key="`${c.name}-${idx}`">
          {{ c.name }} ·
          <span :class="rarityClass(c.talent)">{{ rarityName(c.talent) }}</span>
          · {{ c.attrBiasLabel }}
          <span v-if="c.ancientAttr" class="text-term-ancient">· 太古属性 🌟</span>
        </li>
      </ul>
      <p class="mt-3 text-xs text-ink-400">想保留的话，点「取消」后先招募该英雄。</p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="cancelDiscard">
          取消（保留）
        </button>
        <button
          class="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-500"
          @click="confirmDiscard"
        >
          确认继续
        </button>
      </template>
    </Modal>
  </div>
</template>
