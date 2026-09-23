<script setup lang="ts">
import { computed } from 'vue'

import data from '@shared/schema'

import ItemIcon from '@/components/ItemIcon.vue'
import type { StepStatus } from '@/game/core/sequence'
import { useDohDolStore } from '@/stores/dohdol'

defineProps<{
  /** 面板标题，如「采集序列」/「制作序列」。 */
  title: string
  hint?: string
}>()

const dohdol = useDohDolStore()

const STATUS_LABEL: Record<StepStatus, string> = {
  done: '完成',
  partial: '未完成',
  skipped: '跳过',
  interrupted: '中断',
}
const STATUS_CLASS: Record<StepStatus, string> = {
  done: 'text-emerald-300',
  partial: 'text-amber-300',
  skipped: 'text-rose-300',
  interrupted: 'text-ink-400',
}

function jobName(id: string): string {
  return data.dohdolJobById[id]?.name ?? id
}

function regionName(id: number): string {
  return data.regions.regions.find((r) => r.id === id)?.name ?? `地区 ${id}`
}

/** 序列步骤 → 展示用视图模型。 */
const rows = computed(() =>
  dohdol.sequence.map((step) => {
    const sub =
      step.kind === 'gather'
        ? `${jobName(step.jobId)} · ${regionName(step.regionId)}`
        : jobName(step.jobId)
    const recipe =
      step.kind === 'produce' ? dohdol.state?.recipes.find((r) => r.id === step.recipeId) : undefined
    const iconId =
      step.kind === 'gather' ? step.materialId : recipe?.output.baseId ?? recipe?.output.itemId ?? ''
    return { step, sub, iconId }
  }),
)

/** 运行中的当前步下标；未运行时 -1。 */
const runningIndex = computed(() => (dohdol.seqActive ? dohdol.seqIndex : -1))
const total = computed(() => dohdol.sequence.length)
</script>

<template>
  <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="text-xs font-semibold text-ink-300">{{ title }}</h2>
      <span class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-ink-400">共 {{ total }} 步</span>
      <div class="ml-auto flex items-center gap-1.5">
        <button
          v-if="!dohdol.seqActive"
          class="rounded-md px-3 py-1 text-xs font-semibold transition"
          :class="total ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-800 text-ink-500'"
          :disabled="!total"
          @click="dohdol.startSequence()"
        >
          开始序列
        </button>
        <button
          v-else
          class="rounded-md bg-red-500/20 px-3 py-1 text-xs font-semibold text-red-300"
          @click="dohdol.stopSequence()"
        >
          停止序列
        </button>
        <button
          v-if="total && !dohdol.seqActive"
          class="rounded-md bg-ink-800 px-2 py-1 text-[10px] text-ink-300 hover:text-white"
          @click="dohdol.clearSequence()"
        >
          清空
        </button>
      </div>
    </div>
    <p v-if="hint" class="mt-1 text-[11px] text-ink-500">{{ hint }}</p>

    <div class="mt-2">
      <slot name="composer" />
    </div>

    <ol v-if="total" class="mt-2 space-y-1 text-xs">
      <li
        v-for="(row, i) in rows"
        :key="row.step.id"
        class="flex flex-wrap items-center gap-2 rounded border px-2 py-1"
        :class="i === runningIndex ? 'border-emerald-500/60 bg-emerald-500/10' : 'border-ink-800 bg-ink-950/40'"
      >
        <span class="w-5 text-right font-mono text-[10px] text-ink-500">{{ i + 1 }}</span>
        <ItemIcon :base-id="row.iconId" variant="plain" :size="18" />
        <span class="truncate text-ink-200">{{ row.step.name }}</span>
        <span class="text-ink-500">×{{ row.step.target }}</span>
        <span class="text-[10px] text-ink-500">{{ row.sub }}</span>
        <span v-if="i === runningIndex" class="text-[10px] font-mono text-emerald-300">
          {{ row.step.kind === 'gather' ? `${dohdol.seqGained}/${row.step.target}` : '进行中' }}
        </span>
        <span class="ml-auto flex items-center gap-1">
          <button
            class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-300 hover:text-white disabled:opacity-30"
            :disabled="dohdol.seqActive || i === 0"
            title="上移"
            @click="dohdol.moveStep(row.step.id, -1)"
          >
            ↑
          </button>
          <button
            class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-300 hover:text-white disabled:opacity-30"
            :disabled="dohdol.seqActive || i === total - 1"
            title="下移"
            @click="dohdol.moveStep(row.step.id, 1)"
          >
            ↓
          </button>
          <button
            class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-ink-700 disabled:opacity-30"
            :disabled="dohdol.seqActive"
            title="移除"
            @click="dohdol.removeStep(row.step.id)"
          >
            ✕
          </button>
        </span>
      </li>
    </ol>
    <p v-else class="mt-2 text-[11px] text-ink-500">尚未添加步骤。</p>

    <div v-if="dohdol.seqActive" class="mt-3">
      <div class="mb-1 flex justify-between text-[11px] text-ink-400">
        <span>
          第 {{ dohdol.seqIndex + 1 }}/{{ total }} 步 · {{ dohdol.currentSeqStep?.name }}
        </span>
        <span class="font-mono text-emerald-300">{{ dohdol.progressPct }}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-ink-800">
        <div
          class="h-full rounded-full bg-emerald-500 transition-[width] duration-100 ease-linear"
          :style="{ width: `${dohdol.progressPct}%` }"
        />
      </div>
    </div>

    <div v-if="dohdol.seqResults.length" class="mt-3 rounded border border-ink-800 bg-ink-950/40 p-2">
      <p class="mb-1 text-[11px] font-semibold text-ink-300">本次序列结果</p>
      <ul class="space-y-0.5 text-[11px]">
        <li v-for="r in dohdol.seqResults" :key="r.id" class="flex items-center gap-2">
          <span class="truncate text-ink-200">{{ r.name }}</span>
          <span class="font-mono text-ink-400">{{ r.done }}/{{ r.target }}</span>
          <span :class="STATUS_CLASS[r.status]">{{ STATUS_LABEL[r.status] }}</span>
          <span v-if="r.reason" class="truncate text-ink-500">（{{ r.reason }}）</span>
        </li>
      </ul>
    </div>
  </section>
</template>
