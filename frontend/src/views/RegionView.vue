<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api'
import { useGameStore } from '@/stores/game'
import type { RegionListEntry } from '@/game/types'
import { formatNumber } from '@/utils/format'

const game = useGameStore()
const regions = ref<RegionListEntry[]>([])
const chapters = ref<Array<{ id: number; name: string; regionIds: number[] }>>([])
const loading = ref(false)
const switching = ref<number | null>(null)

const currentId = computed(() => game.sim?.region?.id ?? game.state?.hero.currentRegionId ?? 1)

async function load() {
  loading.value = true
  try {
    const res = await api.regions()
    regions.value = res.regions
    chapters.value = res.chapters
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await load()
})

async function enter(region: RegionListEntry) {
  if (!region.unlocked || switching.value) return
  switching.value = region.id
  try {
    await game.enterRegion(region.id)
    await load()
  } finally {
    switching.value = null
  }
}

function goldRange(region: RegionListEntry) {
  const spread = 0.3
  return `${Math.floor(region.baseGold * (1 - spread))} ~ ${Math.ceil(region.baseGold * (1 + spread))}`
}

const heroLevel = computed(() => game.hero?.level ?? 1)
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">地区关卡</h2>
        <span class="text-xs text-ink-400">
          当前所在：{{ regions.find((r) => r.id === currentId)?.name ?? '—' }}
        </span>
        <span class="ml-auto text-xs text-ink-400">
          击杀进度 {{ game.sim?.killCount ?? 0 }} / {{ game.sim?.killsRequired ?? 0 }}
        </span>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        按顺序解锁，不可跳关；切换地区后当前地区的小怪击杀计数从 0 重新计算。已击败的 BOSS 不会重复出现。
      </p>
    </section>

    <p v-if="loading" class="py-10 text-center text-xs text-ink-600">加载中…</p>

    <section v-for="chapter in chapters" :key="chapter.id" class="space-y-2">
      <h3 class="text-sm font-semibold text-amber-200">第 {{ chapter.id }} 篇章 · {{ chapter.name }}</h3>
      <div class="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <button
          v-for="region in regions.filter((r) => r.chapter === chapter.id)"
          :key="region.id"
          class="card p-3 text-left transition disabled:cursor-not-allowed"
          :class="[
            region.id === currentId ? 'ring-2 ring-amber-400' : '',
            region.unlocked ? 'hover:border-white/40' : 'opacity-50',
          ]"
          :disabled="!region.unlocked || switching === region.id"
          @click="enter(region)"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-ink-100">
                <span class="mr-1 text-[10px] text-ink-500">#{{ region.id }}</span>{{ region.name }}
              </p>
              <p class="text-[10px] text-ink-400">
                Lv.{{ region.levelMin }}-{{ region.levelMax }} · 需击杀 {{ region.killsRequired }}
              </p>
            </div>
            <span
              v-if="region.cleared"
              class="shrink-0 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-300"
            >
              已通关
            </span>
            <span
              v-else-if="region.id === currentId"
              class="shrink-0 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200"
            >
              当前
            </span>
          </div>

          <ul class="mt-2 space-y-0.5 text-[10px] text-ink-400">
            <li>关底 BOSS：<span class="text-fuchsia-300">{{ region.bossName }}</span></li>
            <li>基础金币：{{ formatNumber(region.baseGold) }}（普通怪 {{ goldRange(region) }}）</li>
            <li>刷新间隔：{{ region.spawnInterval }}s / 只</li>
          </ul>

          <p v-if="!region.unlocked" class="mt-2 text-[10px] text-rose-300">{{ region.lockedHint }}</p>
          <p
            v-else-if="heroLevel < region.levelMin"
            class="mt-2 text-[10px] text-amber-300"
          >
            英雄等级低于推荐等级（{{ region.recommendedLevel }}），命中率下降且受到伤害增加
          </p>
        </button>
      </div>
    </section>
  </div>
</template>
