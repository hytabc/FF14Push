<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import { useDohDolStore } from '@/stores/dohdol'
import { useGameStore } from '@/stores/game'
import { useTagsStore } from '@/stores/tags'
import type { Category, Item, RarityId } from '@/game/types'
import { RARITY_ORDER, formatNumber, rarityName, tagColorHex } from '@/utils/format'

const game = useGameStore()
const tagsStore = useTagsStore()
const dohdol = useDohDolStore()

const consumables = computed(() => game.state?.dohdol?.consumables ?? [])
const activeBuffs = computed(() => game.state?.dohdol?.active ?? [])

const category = ref<'all' | Category>('all')
const rarityFilter = ref<'all' | RarityId>('all')
const sortBy = ref<'rarity' | 'level' | 'name' | 'power'>('rarity')
const tagFilter = ref<Set<number>>(new Set())
const selected = ref<Set<number>>(new Set())
const page = ref(1)
const PAGE_SIZE = 24
const confirmBatch = ref(false)

const filtered = computed(() => {
  let list = game.items.filter((i) => !i.equippedSlot)
  if (category.value !== 'all') list = list.filter((i) => i.category === category.value)
  if (rarityFilter.value !== 'all') list = list.filter((i) => i.rarity === rarityFilter.value)
  if (tagFilter.value.size) {
    // 多选标签：命中任一即显示（OR）
    list = list.filter((i) => (i.tagIds ?? []).some((id) => tagFilter.value.has(id)))
  }

  const rarityIndex = (r: RarityId) => RARITY_ORDER.indexOf(r)
  return list.sort((a, b) => {
    if (sortBy.value === 'power') return b.score - a.score || rarityIndex(b.rarity) - rarityIndex(a.rarity)
    if (sortBy.value === 'rarity') return rarityIndex(b.rarity) - rarityIndex(a.rarity) || b.levelReq - a.levelReq
    if (sortBy.value === 'level') return b.levelReq - a.levelReq
    return a.name.localeCompare(b.name, 'zh-Hans-CN')
  })
})

watch([sortBy, category, rarityFilter, tagFilter], () => {
  page.value = 1
})

function toggleTagFilter(tagId: number) {
  const next = new Set(tagFilter.value)
  if (next.has(tagId)) next.delete(tagId)
  else next.add(tagId)
  tagFilter.value = next
}

function clearTagFilter() {
  tagFilter.value = new Set()
}

function tagChipStyle(colorId: string) {
  const hex = tagColorHex(colorId)
  return { color: hex, borderColor: hex, backgroundColor: `${hex}22` }
}

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const pageItems = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
const selectedItems = computed(() => game.items.filter((i) => selected.value.has(i.id)))
const selectedValue = computed(() => selectedItems.value.reduce((sum, i) => sum + i.sellPriceMax, 0))

const counts = computed(() => {
  const map: Record<string, number> = {}
  for (const item of game.items) {
    if (item.equippedSlot) continue
    map[item.category] = (map[item.category] ?? 0) + 1
  }
  return map
})

onMounted(async () => {
  if (!game.state) await game.loadState()
})

function toggle(item: Item) {
  const next = new Set(selected.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  selected.value = next
}

function selectPage() {
  const next = new Set(selected.value)
  for (const item of pageItems.value) next.add(item.id)
  selected.value = next
}

function clearSelection() {
  selected.value = new Set()
}

async function batchSell() {
  confirmBatch.value = false
  const ids = [...selected.value]
  if (!ids.length) return
  await game.sell(ids)
  clearSelection()
}
</script>

<template>
  <div class="space-y-4">
    <section v-if="consumables.length || activeBuffs.length" class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-sm font-semibold text-white">药水 / 食物</h2>
        <div class="flex flex-wrap gap-2 text-[11px]">
          <span
            v-for="b in activeBuffs"
            :key="b.kind"
            class="rounded bg-emerald-500/20 px-2 py-1 text-emerald-200"
          >
            生效中：{{ b.name }} · {{ b.remainingSec }}s
          </span>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <div
          v-for="c in consumables"
          :key="c.itemId"
          class="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/50 px-2 py-1 text-[11px]"
          :title="c.desc"
        >
          <ItemIcon :base-id="c.itemId" variant="plain" :size="20" />
          <span class="text-ink-200">{{ c.name }}</span>
          <span class="font-mono text-ink-400">×{{ c.count }}</span>
          <button
            class="rounded bg-emerald-600/80 px-2 py-0.5 text-white hover:bg-emerald-500"
            @click="dohdol.useConsumable(c.itemId)"
          >
            使用
          </button>
          <button
            class="rounded bg-amber-600/70 px-2 py-0.5 text-white hover:bg-amber-500 disabled:opacity-40"
            :disabled="(c.sell ?? 0) <= 0"
            @click="dohdol.sellStack(c.kind, c.itemId, 1)"
          >
            出售
          </button>
        </div>
      </div>
    </section>

    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">背包</h2>
        <span class="text-xs text-ink-400">
          武器 {{ counts.weapon ?? 0 }} · 防具 {{ counts.armor ?? 0 }} · 饰品 {{ counts.accessory ?? 0 }}
        </span>
        <span class="ml-auto text-xs text-ink-400">已选 {{ selected.size }} 件 · 约 {{ formatNumber(selectedValue) }} 金币</span>
      </div>

      <div class="mt-3 flex flex-wrap gap-2 text-xs">
        <select v-model="category" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="all">全部大类</option>
          <option value="weapon">武器</option>
          <option value="armor">防具</option>
          <option value="accessory">饰品</option>
        </select>
        <select v-model="rarityFilter" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="all">全部品阶</option>
          <option v-for="r in RARITY_ORDER" :key="r" :value="r">{{ rarityName(r) }}</option>
        </select>
        <select v-model="sortBy" class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5">
          <option value="power">按战力排序</option>
          <option value="rarity">按品阶排序</option>
          <option value="level">按等级需求排序</option>
          <option value="name">按名称排序</option>
        </select>

        <div class="ml-auto flex gap-2">
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="selectPage">选中本页</button>
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="clearSelection">清空</button>
          <button
            class="rounded bg-amber-600 px-2 py-1.5 text-white hover:bg-amber-500 disabled:opacity-40"
            :disabled="!selected.size"
            @click="confirmBatch = true"
          >
            批量出售
          </button>
        </div>
      </div>

      <div class="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <template v-if="game.tags.length">
          <span class="text-ink-400">标签：</span>
          <button
            v-for="tag in game.tags"
            :key="tag.id"
            class="rounded-full border px-2.5 py-1 transition"
            :class="tagFilter.has(tag.id) ? '' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
            :style="tagFilter.has(tag.id) ? tagChipStyle(tag.color) : undefined"
            @click="toggleTagFilter(tag.id)"
          >
            {{ tag.name }}
          </button>
          <button v-if="tagFilter.size" class="px-2 py-1 text-ink-400 hover:text-white" @click="clearTagFilter">
            清除筛选
          </button>
        </template>
        <button class="ml-auto rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="tagsStore.openManage()">
          管理标签
        </button>
      </div>
    </section>

    <section class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <ItemCard
        v-for="item in pageItems"
        :key="item.id"
        :item="item"
        :selected="selected.has(item.id)"
        @select="toggle(item)"
        @equip="(i) => game.equip(i.id, i.equipSlots[0])"
        @filter-tag="toggleTagFilter"
      />
      <p v-if="!pageItems.length" class="col-span-full py-10 text-center text-xs text-ink-600">
        背包是空的，去「抽箱」页面获取装备吧。
      </p>
    </section>

    <nav v-if="totalPages > 1" class="flex items-center justify-center gap-2 text-xs">
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="page <= 1"
        @click="page = Math.max(1, page - 1)"
      >
        上一页
      </button>
      <span class="text-ink-400">{{ page }} / {{ totalPages }}</span>
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="page >= totalPages"
        @click="page = Math.min(totalPages, page + 1)"
      >
        下一页
      </button>
    </nav>

    <Teleport to="body">
      <div
        v-if="confirmBatch"
        class="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
        @click.self="confirmBatch = false"
      >
        <div class="card w-full max-w-md p-5">
          <h3 class="text-lg font-semibold text-white">确认批量出售</h3>
          <p class="mt-2 text-sm text-ink-200">
            将出售 {{ selected.size }} 件装备，预计获得约
            <b class="text-amber-300">{{ formatNumber(selectedValue) }}</b> 金币。出售后装备永久消失（图鉴记录保留）。
          </p>
          <div class="mt-4 flex justify-end gap-2">
            <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmBatch = false">
              取消
            </button>
            <button class="rounded-md bg-amber-600 px-3 py-2 text-sm text-white hover:bg-amber-500" @click="batchSell">
              确认出售
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
