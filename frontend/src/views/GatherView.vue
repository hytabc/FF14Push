<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import data from '@shared/schema'

import { useAuthStore } from '@/stores/auth'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

const game = useGameStore()
const dohdol = useDohDolStore()
const auth = useAuthStore()
const toast = useToastStore()

const job = ref('MIN')
const regionId = ref<number | null>(null)
const error = ref('')

const dolJobs = data.dohdolJobs.jobs.filter((j) => j.kind === 'dol' && j.id !== 'FSH')

/** 已解锁且在当前职业下有采集点的地区。 */
const availableNodes = computed(() => {
  const nodes = (data.gatherNodes.nodes as Array<{ regionId: number; jobId: string; levelReq: number }>).filter(
    (n) => n.jobId === job.value,
  )
  return nodes
    .filter((n) => {
      const p = game.state?.regionProgress?.[String(n.regionId)]
      return p ? p.unlocked : n.regionId === 1
    })
    .map((n) => ({ ...n, name: data.regions.regions.find((r) => r.id === n.regionId)?.name ?? `地区 ${n.regionId}` }))
})

const progress = computed(() => dohdol.state?.progress?.dol ?? null)
const materials = computed(() =>
  (dohdol.state?.materials ?? []).slice().sort((a, b) => b.count - a.count),
)
const bonus = computed(() => dohdol.state?.bonus ?? {})
const running = computed(() => dohdol.isRunning && dohdol.mode === 'gather')

onMounted(async () => {
  if (auth.isLoggedIn) await game.loadState()
  if (availableNodes.value.length && regionId.value === null) regionId.value = availableNodes.value[0].regionId
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  void dohdol.stop(true)
})

function onVisibility() {
  dohdol.handleVisibility()
}

function pickJob(id: string) {
  job.value = id
  regionId.value = availableNodes.value[0]?.regionId ?? null
}

async function toggle() {
  error.value = ''
  if (running.value) {
    await dohdol.stop()
    return
  }
  if (regionId.value === null) {
    error.value = '请选择采集地区'
    return
  }
  try {
    await dohdol.startGather(job.value, regionId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '采集失败'
    toast.push(error.value, 'error')
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="text-sm font-bold text-amber-200">采集 · 大地使者</h1>
        <span v-if="progress" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">
          采集等级 Lv.{{ progress.level }} · {{ progress.exp }}/{{ progress.expToNext }}
        </span>
        <span class="ml-auto text-xs text-ink-400">
          产量 +{{ (bonus.gatherYieldPct ?? 0).toFixed(0) }}% · 速度 +{{ (bonus.gatherSpeedPct ?? 0).toFixed(0) }}%
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        不同地区采集不同材料；材料不随地区等级递增，仅按种类区分。
      </p>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="j in dolJobs"
          :key="j.id"
          class="rounded-md px-3 py-1.5 text-xs transition"
          :class="job === j.id ? 'bg-amber-500/20 text-amber-200' : 'bg-ink-800 text-ink-300 hover:text-white'"
          @click="pickJob(j.id)"
        >
          {{ j.name }}
        </button>
        <select v-model.number="regionId" class="ml-auto rounded bg-ink-800 px-2 py-1 text-xs text-ink-200">
          <option :value="null" disabled>选择地区</option>
          <option v-for="n in availableNodes" :key="n.regionId" :value="n.regionId">
            {{ n.name }}（要求 Lv.{{ n.levelReq }}）
          </option>
        </select>
        <button
          class="rounded-md px-4 py-1.5 text-xs font-semibold transition"
          :class="running ? 'bg-red-500/20 text-red-300' : 'bg-emerald-500/20 text-emerald-300'"
          @click="toggle"
        >
          {{ running ? '停止采集' : '开始采集' }}
        </button>
      </div>
      <p v-if="error" class="mt-2 text-xs text-red-400">{{ error }}</p>
    </section>

    <section class="grid gap-3 md:grid-cols-2">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次产出</h2>
        <ul v-if="dohdol.lastGained.length" class="space-y-1 text-xs">
          <li v-for="g in dohdol.lastGained" :key="g.name" class="flex justify-between text-ink-200">
            <span>{{ g.name }}</span>
            <span class="text-emerald-300">+{{ g.count }}</span>
          </li>
        </ul>
        <p v-else class="text-xs text-ink-500">尚未产出。</p>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">材料库存</h2>
        <div class="max-h-64 space-y-1 overflow-y-auto text-xs">
          <div v-for="m in materials" :key="m.itemId" class="flex justify-between text-ink-200">
            <span>{{ m.name }}</span>
            <span class="font-mono text-ink-400">×{{ m.count }}</span>
          </div>
          <p v-if="!materials.length" class="text-ink-500">暂无材料。</p>
        </div>
      </div>
    </section>
  </div>
</template>
