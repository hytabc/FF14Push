<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import data from '@shared/schema'
import type { GatherNodeDef } from '@shared/schema'

import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { gatherYieldExplain } from '@/game/explanations'
import { useAuthStore } from '@/stores/auth'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'

const game = useGameStore()
const dohdol = useDohDolStore()
const auth = useAuthStore()
const toast = useToastStore()
const route = useRoute()
const router = useRouter()

const job = ref('MIN')
const regionId = ref<number | null>(null)
const error = ref('')

const dolJobs = data.dohdolJobs.jobs.filter((j) => j.kind === 'dol' && j.id !== 'FSH')

/** 已解锁且在当前职业下有采集点的地区。 */
const availableNodes = computed(() => {
  const nodes = (data.gatherNodes.nodes as GatherNodeDef[]).filter(
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

/** 当前选中采集点（用于展示产出概率）。 */
const currentNode = computed(
  () => availableNodes.value.find((n) => n.regionId === regionId.value) ?? null,
)
const yieldInfo = computed(() => gatherYieldExplain(currentNode.value))
const yieldRows = computed(() => {
  const yields = (currentNode.value?.yields ?? []) as Array<{ materialId: string; weight: number }>
  const total = yields.reduce((sum, y) => sum + Math.max(0, y.weight), 0) || 1
  return yields.map((y) => ({
    itemId: y.materialId,
    name: data.materialById[y.materialId]?.name ?? y.materialId,
    pct: (Math.max(0, y.weight) / total) * 100,
  }))
})

/** 各地区产出总览（含未解锁地区，仅供预览）。 */
const overviewOpen = ref(false)
const regionOverview = computed(() => {
  const jobIds = dolJobs.map((j) => j.id)
  const byRegion = new Map<
    number,
    {
      regionId: number
      name: string
      unlocked: boolean
      nodes: Array<{ jobId: string; jobName: string; levelReq: number; yields: typeof yieldRows.value }>
    }
  >()
  for (const node of data.gatherNodes.nodes as GatherNodeDef[]) {
    if (!jobIds.includes(node.jobId)) continue
    const entry = game.state?.regionProgress?.[String(node.regionId)]
    const unlocked = entry ? entry.unlocked : node.regionId === 1
    let region = byRegion.get(node.regionId)
    if (!region) {
      region = {
        regionId: node.regionId,
        name: data.regions.regions.find((r) => r.id === node.regionId)?.name ?? `地区 ${node.regionId}`,
        unlocked,
        nodes: [],
      }
      byRegion.set(node.regionId, region)
    }
    const total = node.yields.reduce((sum, y) => sum + Math.max(0, y.weight), 0) || 1
    region.nodes.push({
      jobId: node.jobId,
      jobName: data.dohdolJobById[node.jobId]?.name ?? node.jobId,
      levelReq: node.levelReq,
      yields: node.yields.map((y) => ({
        itemId: y.materialId,
        name: data.materialById[y.materialId]?.name ?? y.materialId,
        pct: (Math.max(0, y.weight) / total) * 100,
      })),
    })
  }
  for (const region of byRegion.values()) region.nodes.sort((a, b) => a.levelReq - b.levelReq)
  return [...byRegion.values()].sort((a, b) => a.regionId - b.regionId)
})
const materials = computed(() =>
  (dohdol.state?.materials ?? []).slice().sort((a, b) => b.count - a.count),
)
const bonus = computed(() => dohdol.state?.bonus ?? {})
const running = computed(() => dohdol.isRunning && dohdol.mode === 'gather')

const totalValue = computed(() =>
  materials.value.reduce((sum, m) => sum + (m.sell ?? 0) * m.count, 0),
)

function sellAll() {
  void dohdol.sellStacks(
    materials.value
      .filter((m) => (m.sell ?? 0) > 0)
      .map((m) => ({ kind: m.kind, itemId: m.itemId, count: m.count })),
  )
}

onMounted(async () => {
  if (auth.isLoggedIn) await game.loadState()
  if (availableNodes.value.length && regionId.value === null) regionId.value = availableNodes.value[0].regionId
  await applyJump()
})
onUnmounted(() => {
  void dohdol.stop(true)
})

/** 从生产页跳转过来时：选中对应采集点，并按需自动开始采集。 */
async function applyJump() {
  const jobParam = typeof route.query.job === 'string' ? route.query.job : ''
  const regionParam = typeof route.query.region === 'string' ? Number(route.query.region) : NaN
  if (!jobParam || !Number.isFinite(regionParam)) return
  const auto = route.query.auto === '1'
  // 清掉 query，避免刷新 / 前进后退时重复触发
  void router.replace({ name: 'gather' })
  if (!dolJobs.some((j) => j.id === jobParam)) return
  job.value = jobParam
  if (!availableNodes.value.some((n) => n.regionId === regionParam)) return
  regionId.value = regionParam
  if (auto && !dohdol.isRunning) await toggle()
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

      <p v-if="yieldRows.length" class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-500">
        该采集点产出：
        <span v-for="row in yieldRows" :key="row.itemId" class="inline-flex items-center gap-1">
          <ItemIcon :base-id="row.itemId" variant="plain" :size="16" />
          <span class="text-ink-300">{{ row.name }}</span>
          {{ row.pct.toFixed(row.pct < 1 ? 1 : 0) }}%
        </span>
        <InfoTip :title="yieldInfo.title">
          <p v-for="(line, i) in yieldInfo.lines" :key="i">{{ line }}</p>
        </InfoTip>
      </p>

      <div v-if="running" class="mt-3">
        <div class="mb-1 flex justify-between text-[11px] text-ink-400">
          <span>正在采集…</span>
          <span class="font-mono text-emerald-300">{{ dohdol.progressPct }}%</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-ink-800">
          <div
            class="h-full rounded-full bg-emerald-500 transition-[width] duration-100 ease-linear"
            :style="{ width: `${dohdol.progressPct}%` }"
          />
        </div>
      </div>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <button class="flex w-full items-center justify-between text-left" @click="overviewOpen = !overviewOpen">
        <h2 class="text-xs font-semibold text-ink-300">各地区产出总览</h2>
        <span class="text-[11px] text-ink-400">{{ overviewOpen ? '收起 ▲' : '展开 ▼' }}</span>
      </button>
      <p class="mt-1 text-[11px] text-ink-500">
        每个地区能采集到的材料（含未解锁地区，仅作预览）；概率为该采集点内各材料的相对权重。
      </p>
      <div v-if="overviewOpen" class="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="r in regionOverview"
          :key="r.regionId"
          class="rounded border border-ink-800 bg-ink-950/40 p-2"
          :class="r.unlocked ? '' : 'opacity-50'"
        >
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-ink-200">{{ r.name }}</span>
            <span v-if="!r.unlocked" class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400">未解锁</span>
          </div>
          <div v-for="n in r.nodes" :key="n.jobId" class="mt-1.5">
            <p class="text-[10px] text-ink-500">{{ n.jobName }} · 要求 Lv.{{ n.levelReq }}</p>
            <div class="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
              <span
                v-for="y in n.yields"
                :key="y.itemId"
                class="inline-flex items-center gap-1 text-[11px] text-ink-300"
              >
                <ItemIcon :base-id="y.itemId" variant="plain" :size="16" />
                {{ y.name }}
                <span class="text-ink-600">{{ y.pct.toFixed(y.pct < 1 ? 1 : 0) }}%</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-3 md:grid-cols-2">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次产出</h2>
        <ul v-if="dohdol.lastGained.length" class="space-y-1 text-xs">
          <li v-for="g in dohdol.lastGained" :key="g.itemId" class="flex justify-between text-ink-200">
            <span class="flex min-w-0 items-center gap-1.5">
              <ItemIcon :base-id="g.itemId" variant="plain" :size="18" />
              <span class="truncate">{{ g.name }}</span>
            </span>
            <span class="text-emerald-300">+{{ g.count }}</span>
          </li>
        </ul>
        <p v-else class="text-xs text-ink-500">尚未产出。</p>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <div class="mb-2 flex items-center justify-between">
          <h2 class="text-xs font-semibold text-ink-300">材料库存</h2>
          <button
            v-if="materials.length"
            class="rounded bg-amber-600/70 px-2 py-0.5 text-[10px] text-white hover:bg-amber-500"
            @click="sellAll"
          >
            全部出售（+{{ totalValue }}）
          </button>
        </div>
        <div class="max-h-64 space-y-1 overflow-y-auto text-xs">
          <div v-for="m in materials" :key="m.itemId" class="flex items-center justify-between text-ink-200">
            <span class="flex min-w-0 items-center gap-1.5">
              <ItemIcon :base-id="m.itemId" variant="plain" :size="18" />
              <span class="truncate">{{ m.name }}</span>
            </span>
            <span class="flex items-center gap-2">
              <span class="font-mono text-ink-400">×{{ m.count }}</span>
              <span class="font-mono text-ink-500">{{ (m.sell ?? 0) * m.count }}</span>
              <button
                class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-amber-300 hover:bg-ink-700 disabled:opacity-40"
                :disabled="(m.sell ?? 0) <= 0"
                @click="dohdol.sellStack(m.kind, m.itemId, m.count)"
              >
                出售
              </button>
            </span>
          </div>
          <p v-if="!materials.length" class="text-ink-500">暂无材料。</p>
        </div>
      </div>
    </section>
  </div>
</template>
