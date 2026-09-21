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

const job = ref('CRP')
const error = ref('')

const dohJobs = data.dohdolJobs.jobs.filter((j) => j.kind === 'doh')
const progress = computed(() => dohdol.state?.progress?.doh ?? null)
const running = computed(() => dohdol.isRunning && dohdol.mode === 'produce')

const recipes = computed(() =>
  (dohdol.state?.recipes ?? [])
    .filter((r) => r.jobId === job.value)
    .slice()
    .sort((a, b) => a.requiredLevel - b.requiredLevel),
)

const materials = computed(() => dohdol.state?.materials ?? [])
const consumables = computed(() => dohdol.state?.consumables ?? [])
const bonus = computed(() => dohdol.state?.bonus ?? {})

onMounted(async () => {
  if (auth.isLoggedIn) await game.loadState()
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibility)
  void dohdol.stop(true)
})

function onVisibility() {
  dohdol.handleVisibility()
}

async function startRecipe(recipeId: string) {
  error.value = ''
  if (running.value) {
    await dohdol.stop()
  }
  try {
    await dohdol.startProduce(job.value, recipeId)
    toast.push('开始生产', 'success')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '生产失败'
    toast.push(error.value, 'error')
  }
}

async function stop() {
  await dohdol.stop()
}
</script>

<template>
  <div class="space-y-4">
    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 class="text-sm font-bold text-amber-200">生产 · 能工巧匠</h1>
        <span v-if="progress" class="rounded bg-ink-800 px-2 py-1 text-xs text-ink-300">
          生产等级 Lv.{{ progress.level }} · {{ progress.exp }}/{{ progress.expToNext }}
        </span>
        <span class="ml-auto text-xs text-ink-400">
          制造品质 +{{ (bonus.craftQualityPct ?? 0).toFixed(0) }}%
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        制造装备恒为「高品质」：属性区间上移、必带太古词条，并按概率抽品阶；专用装备仅能通过生产获取。
      </p>
    </section>

    <section class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="j in dohJobs"
          :key="j.id"
          class="rounded-md px-2.5 py-1 text-xs transition"
          :class="job === j.id ? 'bg-amber-500/20 text-amber-200' : 'bg-ink-800 text-ink-400 hover:text-white'"
          @click="job = j.id"
        >
          {{ j.name }}
        </button>
        <button
          v-if="running"
          class="ml-auto rounded-md bg-red-500/20 px-4 py-1.5 text-xs font-semibold text-red-300"
          @click="stop"
        >
          停止生产
        </button>
      </div>
      <p v-if="error" class="mt-2 text-xs text-red-400">{{ error }}</p>
    </section>

    <section class="space-y-2">
      <div
        v-for="r in recipes"
        :key="r.id"
        class="rounded-lg border p-3"
        :class="r.unlocked ? 'border-ink-700/60 bg-ink-900/40' : 'border-ink-800/60 bg-ink-950/40 opacity-60'"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-ink-100">{{ r.output.name }}</span>
          <span v-if="r.output.quality === 'high'" class="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">
            高品质
          </span>
          <span v-if="r.output.supply === 'dohdol'" class="rounded bg-sky-500/20 px-1.5 py-0.5 text-[10px] text-sky-200">
            专用装备
          </span>
          <span
            v-if="!r.unlocked"
            class="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400"
          >需生产等级 Lv.{{ r.requiredLevel }}</span>
          <button
            class="ml-auto rounded-md px-3 py-1 text-xs transition"
            :class="r.unlocked && r.craftable > 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-800 text-ink-500'"
            :disabled="!r.unlocked || r.craftable <= 0"
            @click="startRecipe(r.id)"
          >
            制造
          </button>
        </div>
        <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
          <span
            v-for="i in r.inputs"
            :key="i.itemId"
            :class="i.have >= i.count ? 'text-ink-300' : 'text-red-400'"
          >
            {{ i.name }} {{ i.have }}/{{ i.count }}
          </span>
          <span class="text-ink-500">可制造 {{ r.craftable }} 次 · 每次 {{ r.craftSeconds }}s · +{{ r.xp }} 经验</span>
        </div>
      </div>
      <p v-if="!recipes.length" class="text-xs text-ink-500">该职业暂无可制造配方。</p>
    </section>

    <section class="grid gap-3 md:grid-cols-3">
      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">本次生产</h2>
        <ul v-if="dohdol.lastGained.length" class="space-y-1 text-xs">
          <li v-for="g in dohdol.lastGained" :key="g.name" class="flex justify-between text-ink-200">
            <span>{{ g.name }}</span><span class="text-emerald-300">+{{ g.count }}</span>
          </li>
        </ul>
        <ul v-if="dohdol.lastProduced.length" class="space-y-1 text-xs">
          <li v-for="(p, i) in dohdol.lastProduced" :key="i" class="text-amber-200">★ {{ p.name }}（高品质）</li>
        </ul>
        <p v-if="!dohdol.lastGained.length && !dohdol.lastProduced.length" class="text-xs text-ink-500">尚未生产。</p>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">材料库存</h2>
        <div class="max-h-56 space-y-1 overflow-y-auto text-xs">
          <div v-for="m in materials" :key="m.itemId" class="flex justify-between text-ink-200">
            <span>{{ m.name }}</span><span class="font-mono text-ink-400">×{{ m.count }}</span>
          </div>
          <p v-if="!materials.length" class="text-ink-500">暂无材料。</p>
        </div>
      </div>

      <div class="rounded-lg border border-ink-700/60 bg-ink-900/40 p-3">
        <h2 class="mb-2 text-xs font-semibold text-ink-300">药水 / 食物</h2>
        <div class="max-h-56 space-y-1 overflow-y-auto text-xs">
          <div v-for="c in consumables" :key="c.itemId" class="flex items-center justify-between text-ink-200">
            <span>{{ c.name }}</span>
            <span class="flex items-center gap-2">
              <span class="font-mono text-ink-400">×{{ c.count }}</span>
              <button class="rounded bg-ink-800 px-2 py-0.5 text-[10px] text-emerald-300 hover:bg-ink-700" @click="dohdol.useConsumable(c.itemId)">
                使用
              </button>
            </span>
          </div>
          <p v-if="!consumables.length" class="text-ink-500">暂无药水食物。</p>
        </div>
      </div>
    </section>
  </div>
</template>
