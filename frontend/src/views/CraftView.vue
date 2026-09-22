<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api'
import data from '@shared/schema'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import type { Category, CraftPlan, Item } from '@/game/types'
import { RARITY_ORDER, attrName, attrSuffix, baseAttrName, formatNumber, rarityBg, rarityClass, rarityName } from '@/utils/format'

const game = useGameStore()

const category = ref<Category>('weapon')
const plan = ref<CraftPlan | null>(null)
const loading = ref(false)
const busy = ref(false)

const result = ref<{ fee: number; consumed: number; produced: Item[] } | null>(null)
const showResult = ref(false)

const CATEGORIES: Array<{ id: Category; name: string }> = [
  { id: 'weapon', name: '武器' },
  { id: 'armor', name: '防具' },
  { id: 'accessory', name: '饰品' },
]

const categories = data.crafting.categories

const counts = computed(() => {
  const map: Record<string, number> = {}
  for (const rarity of RARITY_ORDER) map[rarity] = 0
  for (const item of game.items) {
    if (item.category !== category.value) continue
    if (item.equippedSlot) continue
    map[item.rarity] += 1
  }
  return map
})

const required = data.crafting.requiredCount

async function loadPlan() {
  loading.value = true
  try {
    const res = await api.craftPreview(category.value, true)
    plan.value = res.plan
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await loadPlan()
})

watch(category, loadPlan)
watch(() => game.items.length, loadPlan)

async function doCraft() {
  if (busy.value) return
  busy.value = true
  try {
    const res = await game.craft(category.value, true)
    if (res) {
      result.value = { fee: res.fee, consumed: res.consumed, produced: res.produced }
      showResult.value = true
      await loadPlan()
    }
  } finally {
    busy.value = false
  }
}

/** 合成产物按品阶从高到低展示。 */
const producedSorted = computed(() =>
  [...(result.value?.produced ?? [])].sort(
    (a, b) => RARITY_ORDER.indexOf(b.rarity) - RARITY_ORDER.indexOf(a.rarity) || b.score - a.score,
  ),
)

const affordable = computed(() => (plan.value?.totalFee ?? 0) <= game.gold)
const hasSteps = computed(() => (plan.value?.steps ?? []).some((s) => s.crafts > 0))
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">装备合成</h2>
        <span class="text-xs text-ink-400">
          {{ required }} 件同品阶同类装备 → 1 件更高品阶装备
        </span>
        <span class="ml-auto font-mono text-sm text-amber-300">💰 {{ game.gold.toLocaleString() }}</span>
      </div>

      <div class="mt-3 flex gap-1 rounded-lg bg-ink-800 p-1 text-xs">
        <button
          v-for="cat in CATEGORIES"
          :key="cat.id"
          class="flex-1 rounded-md py-1.5 transition"
          :class="category === cat.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="category = cat.id"
        >
          {{ cat.name }}
        </button>
      </div>
      <p class="mt-2 text-[11px] text-ink-600">
        可用大类：{{ categories.map((c) => ({ weapon: '武器', armor: '防具', accessory: '饰品' })[c as 'weapon']).join(' / ') }}
      </p>
      <p class="mt-1 text-[11px] text-ink-500">
        产物以<b class="text-ink-300">最差素材</b>为准：装备种类 / 等级取该组 16 件中最低的一件，品质只有 16 件全部为高品质时才保留（1 件普通即产出普通）。
      </p>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">当前持有（未装备）</h3>
      <div class="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
        <div
          v-for="rarity in RARITY_ORDER"
          :key="rarity"
          class="rounded-lg border border-ink-700 bg-ink-800/60 p-2 text-center"
        >
          <p class="text-[10px] text-ink-400">{{ rarityName(rarity) }}</p>
          <p class="font-mono text-lg" :class="rarityClass(rarity)">{{ counts[rarity] }}</p>
          <p class="text-[10px] text-ink-600">可合成 {{ Math.floor(counts[rarity] / required) }}</p>
        </div>
      </div>
    </section>

    <section data-tutorial="craft" class="card p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white">一键合成预览</h3>
        <span class="text-xs text-ink-400">
          手续费合计
          <b class="font-mono text-amber-300">{{ formatNumber(plan?.totalFee ?? 0) }}</b>
        </span>
      </div>

      <p v-if="loading" class="py-6 text-center text-xs text-ink-600">计算中…</p>
      <p v-else-if="!hasSteps" class="py-6 text-center text-xs text-ink-600">
        当前没有足够的同类装备可合成（每级需要 {{ required }} 件）。
      </p>

      <div v-else class="mt-3 space-y-2">
        <div
          v-for="step in plan?.steps.filter((s) => s.crafts > 0)"
          :key="step.from"
          class="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-xs"
        >
          <span :class="rarityClass(step.from)">
            {{ rarityName(step.from) }} ×{{ required * step.crafts }}
          </span>
          <span class="text-ink-500">→</span>
          <span :class="rarityClass(step.to)">{{ rarityName(step.to) }} ×{{ step.crafts }}</span>
          <span class="font-mono text-ink-400">{{ formatNumber(step.totalFee) }} 金币</span>
        </div>

        <div class="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          合成后预计获得：
          <span v-for="(amount, rarity) in plan?.produced" :key="rarity" class="ml-2">
            {{ rarityName(rarity as never) }} ×{{ amount }}
          </span>
        </div>
      </div>

      <button
        class="mt-4 w-full rounded-md py-2.5 text-sm font-medium transition disabled:opacity-40"
        :class="affordable ? 'bg-amber-500 text-ink-950 hover:bg-amber-400' : 'bg-ink-700 text-ink-400'"
        :disabled="!hasSteps || !affordable || busy"
        @click="doCraft"
      >
        {{
          busy
            ? '合成中…'
            : !hasSteps
              ? '没有可合成的装备'
              : !affordable
                ? '手续费不足'
                : '一键合成'
        }}
      </button>

      <p class="mt-3 text-[11px] text-ink-600">
        合成手续费：{{ data.crafting.routes.map((r) => `${rarityName(r.from)}→${rarityName(r.to)} ${formatNumber(r.fee)}`).join(' · ') }}
      </p>
    </section>

    <Modal :open="showResult" title="合成结果" max-width="max-w-3xl" @close="showResult = false">
      <div v-if="result" class="space-y-3">
        <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3 text-xs text-ink-300">
          消耗 <b class="font-mono text-ink-100">{{ result.consumed }}</b> 件装备 ·
          手续费 <b class="font-mono text-amber-300">{{ formatNumber(result.fee) }}</b> 金币 ·
          获得 <b class="font-mono text-emerald-300">{{ result.produced.length }}</b> 件
        </div>

        <p v-if="!result.produced.length" class="py-6 text-center text-xs text-ink-600">
          本次没有产出装备。
        </p>

        <div v-else class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <article
            v-for="item in producedSorted"
            :key="item.id"
            class="rounded-lg border p-3"
            :class="[rarityClass(item.rarity), rarityBg(item.rarity)]"
          >
            <div class="flex items-center gap-2">
              <ItemIcon :base-id="item.baseId" :rarity="item.rarity" :size="36" />
              <div class="min-w-0">
                <p class="truncate text-xs font-medium">{{ item.name }}</p>
                <p class="text-[10px] text-ink-400">{{ rarityName(item.rarity) }} · Lv.{{ item.levelReq }}</p>
              </div>
            </div>
            <div class="mt-1 space-y-0.5 text-[10px] text-ink-300">
              <p v-for="entry in item.baseAttrs" :key="`b-${entry.attr}`">
                {{ baseAttrName(entry.attr) }} +{{ Math.round(entry.value) }}
              </p>
              <p v-for="entry in item.subAttrs" :key="`s-${entry.attr}`">
                {{ attrName(entry.attr) }} +{{ entry.value.toFixed(2) }}{{ attrSuffix(entry.attr) }}
              </p>
            </div>
          </article>
        </div>
      </div>

      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="showResult = false">
          关闭
        </button>
        <RouterLink
          to="/inventory"
          class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-amber-400"
          @click="showResult = false"
        >
          去背包查看
        </RouterLink>
      </template>
    </Modal>
  </div>
</template>
