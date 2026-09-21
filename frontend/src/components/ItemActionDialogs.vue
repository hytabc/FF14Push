<script setup lang="ts">
import { computed } from 'vue'

import data from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { enchantQualityExplain } from '@/game/explanations'
import { useItemActions } from '@/stores/itemActions'
import type { RerollChange } from '@/game/types'
import {
  attrName,
  attrRangeLabel,
  attrSuffix,
  rarityClass,
  rarityName,
  subAttrQualityClass,
  termLabel,
} from '@/utils/format'
import { diffReroll } from '@/utils/rerollDiff'

const actions = useItemActions()
const enchantInfo = enchantQualityExplain()

const item = computed(() => actions.pending?.item ?? null)
const kind = computed(() => actions.pending?.kind ?? null)
const result = computed(() => actions.result)
const changes = computed<RerollChange[]>(() =>
  result.value ? diffReroll(result.value.kind, result.value.before, result.value.after) : [],
)
const resultItem = computed(() => result.value?.after ?? null)

const title = computed(() => {
  if (result.value) return result.value.kind === 'refine' ? '重造结果' : '附魔结果'
  switch (kind.value) {
    case 'refine':
      return '确认重造'
    case 'enchant':
      return '确认附魔'
    case 'enchantAuto':
      return '自动附魔至稀有/太古'
    case 'sell':
      return '确认出售'
    default:
      return ''
  }
})

const mode = computed(() => actions.pending?.mode ?? 'random')
const isRerollMode = computed(() => kind.value === 'refine' || kind.value === 'enchant')

// 实付价由后端按当前重造次数算好下发，避免前端与结算公式漂移
const refineCost = computed(() =>
  mode.value === 'basedOnCurrent' ? (item.value?.refineCostBasedOnCurrent ?? 0) : (item.value?.refineCost ?? 0),
)
const enchantCost = computed(() =>
  mode.value === 'basedOnCurrent'
    ? (item.value?.enchantCostBasedOnCurrent ?? 0)
    : (item.value?.enchantCost ?? 0),
)
const sellPrice = computed(() => item.value?.sellPriceMax ?? 0)

function fmt(value: number): string {
  return String(Math.round(value * 100) / 100)
}

function dirClass(direction: RerollChange['direction']): string {
  if (direction === 'up') return 'text-emerald-400'
  if (direction === 'down') return 'text-rose-400'
  return 'text-ink-400'
}

function arrow(direction: RerollChange['direction']): string {
  if (direction === 'up') return '▲'
  if (direction === 'down') return '▼'
  return '＝'
}

function close() {
  if (result.value) actions.closeResult()
  else actions.cancel()
}
</script>

<template>
  <Modal :open="!!actions.pending || !!actions.result" :title="title" @close="close()">
    <!-- 结果视图：逐条涨跌 -->
    <div v-if="result && resultItem" class="space-y-3 text-sm">
      <div class="flex items-center gap-3 rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <ItemIcon :base-id="resultItem.baseId" :rarity="resultItem.rarity" :size="44" />
        <div>
          <p class="font-medium" :class="rarityClass(resultItem.rarity)">
            {{ resultItem.name }} · {{ rarityName(resultItem.rarity) }}
          </p>
          <p class="text-[11px] text-ink-400">{{ result.kind === 'refine' ? '重造完成' : '附魔完成' }}</p>
        </div>
      </div>

      <ul v-if="changes.length" class="space-y-1">
        <li
          v-for="change in changes"
          :key="change.key"
          class="flex items-center justify-between gap-3 rounded-md border border-ink-700 bg-ink-800/50 px-2.5 py-1.5 text-xs"
        >
          <span class="truncate text-ink-200">{{ change.name }}</span>
          <span class="shrink-0 font-mono" :class="dirClass(change.direction)">
            <span class="text-ink-300">{{ change.before == null ? '—' : fmt(change.before) }}</span>
            <span class="mx-1 text-ink-600">→</span>
            <span>{{ change.after == null ? '—' : fmt(change.after) }}</span>
            <span v-if="change.delta != null && change.delta !== 0" class="ml-1.5">
              （{{ change.delta > 0 ? '+' : '' }}{{ fmt(change.delta) }}）
            </span>
            <span class="ml-1">{{ arrow(change.direction) }}</span>
          </span>
        </li>
      </ul>
      <p v-else class="text-xs text-ink-400">本次没有可展示的属性变化。</p>
    </div>

    <!-- 确认视图 -->
    <div v-else-if="item" class="space-y-3 text-sm">
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <div class="flex items-center gap-3">
          <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="48" />
          <p class="font-medium" :class="rarityClass(item.rarity)">
            {{ item.name }} · {{ rarityName(item.rarity) }}
          </p>
        </div>
        <ul class="mt-1 space-y-0.5 text-[11px]">
          <li
            v-for="entry in item.subAttrs"
            :key="entry.attr"
            :class="subAttrQualityClass(entry.quality)"
          >
            {{ attrName(entry.attr) }} +{{ entry.value.toFixed(2) }}{{ attrSuffix(entry.attr) }}
            <span v-if="entry.quality === 'ancient'" class="ml-0.5">🌟</span>
            <template v-else>
              <span class="text-ink-500">{{ attrRangeLabel(entry.min, entry.max, 2) }}</span>
              <span v-if="entry.quality === 'rare'" class="ml-0.5">（稀有）</span>
            </template>
          </li>
        </ul>
        <div v-if="item.terms.length" class="mt-2 flex flex-wrap gap-1">
          <span
            v-for="term in item.terms"
            :key="term.id"
            class="rounded border border-ink-600 px-1.5 py-0.5 text-[10px]"
            :class="term.type === 'debuff' ? 'text-rose-300' : 'text-emerald-300'"
          >
            {{ termLabel(term) }}
            {{ term.desc.replace('{v}', String(term.value)) }}
          </span>
        </div>
      </div>

      <div v-if="isRerollMode" class="grid grid-cols-2 gap-2">
        <button
          class="rounded-md border px-2 py-2 text-xs transition"
          :class="
            mode === 'random'
              ? 'border-indigo-400 bg-indigo-500/15 text-indigo-200'
              : 'border-ink-600 text-ink-400 hover:border-ink-400'
          "
          @click="actions.setMode('random')"
        >
          彻底随机
          <span class="mt-0.5 block font-mono text-[10px]">
            {{ (kind === 'refine' ? item.refineCost : item.enchantCost).toLocaleString() }} 金
          </span>
        </button>
        <button
          class="rounded-md border px-2 py-2 text-xs transition"
          :class="
            mode === 'basedOnCurrent'
              ? 'border-emerald-400 bg-emerald-500/15 text-emerald-200'
              : 'border-ink-600 text-ink-400 hover:border-ink-400'
          "
          @click="actions.setMode('basedOnCurrent')"
        >
          基于当前
          <span class="mt-0.5 block font-mono text-[10px]">
            {{ (kind === 'refine' ? item.refineCostBasedOnCurrent : item.enchantCostBasedOnCurrent).toLocaleString() }} 金
          </span>
        </button>
      </div>

      <p v-if="kind === 'refine'" class="text-xs text-ink-300">
        <template v-if="mode === 'basedOnCurrent'">
          基于当前：<b class="text-white">每种属性独立</b>在现有值附近小幅浮动，
          <b class="text-emerald-300">可能升也可能降</b>；副属性种类与品阶、类型、等级需求、词条均保持不变。
        </template>
        <template v-else>
          彻底随机：重新洗牌<b class="text-white">基础属性浮动值</b>与<b class="text-white">副属性（种类与数值）</b>，
          等同重新获得该装备；品阶、类型、等级需求与所有 Buff/Debuff <b class="text-emerald-300">保持不变</b>。
        </template>
        <span v-if="item.refineCount" class="text-amber-300">
          该装备已重造 {{ item.refineCount }} 次，重造费用会随次数继续上涨。
        </span>
      </p>
      <p v-else-if="kind === 'enchant'" class="text-xs text-ink-300">
        <template v-if="mode === 'basedOnCurrent'">
          基于当前：保留现有词条种类，<b class="text-white">每条独立</b>在现有值附近小幅浮动，
          <b class="text-emerald-300">可能升也可能降</b>；品质保留。
        </template>
        <template v-else>
          彻底随机：将<b class="text-rose-300">覆盖现有全部 Buff/Debuff</b>（数量、种类、数值均重新随机）。
          每个词条独立判定品质：稀有 {{ (data.economy.termQuality.rare * 100).toFixed(1) }}%、
          太古 {{ (data.economy.termQuality.ancient * 100).toFixed(1) }}%（仅 Buff）。附魔结果<b class="text-rose-300">不可撤销</b>。
          <InfoTip :title="enchantInfo.title">
            <p v-for="(line, i) in enchantInfo.lines" :key="i">{{ line }}</p>
          </InfoTip>
        </template>
      </p>
      <p v-else-if="kind === 'enchantAuto'" class="text-xs text-ink-300">
        将持续附魔直到出现<b class="text-amber-300">稀有或太古 Buff</b>词条为止，每次附魔都会消耗金币，
        总消耗取决于运气。最多尝试 100 次或金币耗尽即停止。
      </p>
      <p v-else class="text-xs text-ink-300">
        出售后装备<b class="text-rose-300">永久消失</b>，获得金币。图鉴解锁记录会保留。
      </p>

      <p class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        <template v-if="kind === 'refine'">消耗：{{ refineCost.toLocaleString() }} 金币</template>
        <template v-else-if="kind === 'enchant'">消耗：{{ enchantCost.toLocaleString() }} 金币</template>
        <template v-else-if="kind === 'enchantAuto'">
          单次消耗：{{ enchantCost.toLocaleString() }} 金币（按次数累计）
        </template>
        <template v-else>获得：约 {{ sellPrice.toLocaleString() }} 金币</template>
      </p>
    </div>

    <template #footer>
      <template v-if="result">
        <button
          class="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500"
          @click="actions.closeResult()"
        >
          完成
        </button>
      </template>
      <template v-else>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="actions.cancel()">
          取消
        </button>
        <button
          class="rounded-md px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          :class="kind === 'sell' ? 'bg-amber-600 hover:bg-amber-500' : 'bg-indigo-600 hover:bg-indigo-500'"
          :disabled="actions.busy"
          @click="actions.confirm()"
        >
          {{ actions.busy ? '处理中…' : '确认' }}
        </button>
      </template>
    </template>
  </Modal>
</template>
