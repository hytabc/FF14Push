<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import InfoTip from '@/components/InfoTip.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { sound } from '@/game/audio'
import type { MateriaSlotState, MateriaState, MateriaStockEntry, SlotId } from '@/game/types'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { baseAttrName } from '@/utils/format'
import { equipmentSlotGroups } from '@/utils/slots'

const game = useGameStore()
const toast = useToastStore()

const state = ref<MateriaState | null>(null)
const loading = ref(false)
const busy = ref(false)
const picker = ref<{ slot: SlotId; index: number } | null>(null)

const slotGroups = computed(() => equipmentSlotGroups())
const slotsById = computed(() => {
  const out: Record<string, MateriaSlotState> = {}
  for (const slot of state.value?.slots ?? []) out[slot.id] = slot
  return out
})
const loadout = computed(() => game.loadout)

const bonusRows = computed(() =>
  Object.entries(state.value?.bonus ?? {}).map(([stat, value]) => ({
    stat,
    name: baseAttrName(stat) || stat,
    value,
  })),
)

/** 库存中可镶嵌的魔晶石（数量 > 0）。 */
const available = computed(() => (state.value?.stock ?? []).filter((s) => s.count > 0))

/** 可合成：数量达到 mergeFrom 且未满级。 */
const mergeable = computed(() => {
  const need = state.value?.mergeFrom ?? 5
  const cap = state.value?.maxLevel ?? 5
  return (state.value?.stock ?? []).filter((s) => s.count >= need && s.level < cap)
})

/** 栏位当前可镶嵌的孔位（按顺序填充：最低的空孔）。 */
function nextIndex(slot: MateriaSlotState | undefined): number | null {
  if (!slot) return null
  for (const socket of slot.sockets) {
    if (!socket.materia) return socket.index
  }
  return null
}

function statLabel(stat: string, fallback: string): string {
  return baseAttrName(stat) || fallback
}

async function load() {
  loading.value = true
  try {
    state.value = await api.materiaState()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!game.state) await game.loadState()
  await load()
})

function openPicker(slot: MateriaSlotState) {
  const index = nextIndex(slot)
  if (index === null) return
  picker.value = { slot: slot.id, index }
}

async function socket(materiaId: string) {
  const target = picker.value
  if (!target || busy.value) return
  busy.value = true
  try {
    const res = await api.materiaSocket(target.slot, target.index, materiaId)
    state.value = res.state
    picker.value = null
    if (res.success) {
      toast.push(`${res.materia.name} 镶嵌成功！`, 'success')
      sound.play('materia.ok')
    } else {
      toast.push(`镶嵌失败（成功率 ${Math.round(res.chance * 100)}%），${res.materia.name} 已消耗`, 'error')
      sound.play('materia.fail')
    }
    await game.loadState()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function remove(slot: MateriaSlotState, index: number) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.materiaRemove(slot.id, index)
    state.value = res.state
    toast.push(`已取出 ${res.removed.name}`, 'info')
    await game.loadState()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function merge(entry: MateriaStockEntry) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await api.materiaMerge(entry.id)
    state.value = res.state
    toast.push(`合成成功：${res.produced.name}`, 'success')
    sound.play('ui.success')
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">魔晶石镶嵌</h2>
        <span class="text-xs text-ink-400">
          孔位属于<strong class="text-ink-200">账号的 11 个装备栏位</strong>（每栏 {{ state?.socketsPerSlot ?? 5 }} 孔），
          换装备 / 换英雄都不会改变。镶嵌失败会消耗该魔晶石，取出必定成功并返还。
        </span>
        <InfoTip title="镶嵌成功率">
          <p>第 1 孔必定成功，越往后越低（服务端结算）：</p>
          <p v-for="(chance, i) in state?.successChance ?? []" :key="i" class="font-mono">
            第 {{ i + 1 }} 孔：{{ Math.round(chance * 100) }}%
          </p>
          <p class="text-ink-400">来源：shared/data/materia.json:successChance。失败消耗 1 个魔晶石。</p>
        </InfoTip>
        <span class="ml-auto text-xs text-ink-400">
          当前加成
          <template v-if="bonusRows.length">
            <span v-for="row in bonusRows" :key="row.stat" class="ml-2 font-mono text-emerald-300">
              {{ row.name }} +{{ row.value }}
            </span>
          </template>
          <span v-else class="ml-1 text-ink-500">（未镶嵌）</span>
        </span>
      </div>
    </section>

    <!-- 栏位 × 孔位 -->
    <section v-for="group in slotGroups" :key="group.key" class="card p-4">
      <h3 class="text-sm font-semibold text-white">{{ group.title }}</h3>
      <div class="mt-3 grid gap-3" :class="group.full ? '' : 'md:grid-cols-2'">
        <div v-for="slot in group.slots" :key="slot.id" class="rounded-lg border border-ink-700 bg-ink-800/40 p-3">
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-medium text-ink-100">{{ slot.name }}</span>
            <span class="truncate text-[11px] text-ink-500">
              {{ loadout[slot.id as SlotId]?.name ?? '未装备' }}
            </span>
          </div>

          <div class="mt-2 flex flex-wrap gap-2">
            <div
              v-for="socket in slotsById[slot.id]?.sockets ?? []"
              :key="socket.index"
              class="flex min-w-[7.5rem] flex-1 items-center gap-2 rounded-md border p-2 text-[11px]"
              :class="socket.materia ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-ink-700 bg-ink-900/60'"
            >
              <template v-if="socket.materia">
                <ItemIcon :base-id="socket.materia.id" :size="24" variant="plain" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-ink-100">{{ socket.materia.name }}</p>
                  <p class="text-emerald-300">
                    {{ statLabel(socket.materia.stat, socket.materia.statName) }} +{{ socket.materia.value }}
                  </p>
                </div>
                <button
                  class="shrink-0 rounded bg-ink-700 px-1.5 py-0.5 text-ink-200 hover:bg-ink-600"
                  :disabled="busy"
                  @click="remove(slotsById[slot.id], socket.index)"
                >
                  取出
                </button>
              </template>
              <template v-else>
                <div class="min-w-0 flex-1">
                  <p class="text-ink-400">第 {{ socket.index + 1 }} 孔</p>
                  <p class="font-mono text-ink-300">成功率 {{ Math.round(socket.chance * 100) }}%</p>
                </div>
                <button
                  class="shrink-0 rounded px-1.5 py-0.5"
                  :class="
                    nextIndex(slotsById[slot.id]) === socket.index
                      ? 'bg-amber-500 text-ink-950 hover:bg-amber-400'
                      : 'cursor-not-allowed bg-ink-800 text-ink-600'
                  "
                  :disabled="busy || nextIndex(slotsById[slot.id]) !== socket.index"
                  @click="openPicker(slotsById[slot.id])"
                >
                  镶嵌
                </button>
              </template>
            </div>
          </div>
          <p class="mt-1 text-[10px] text-ink-600">孔位按顺序镶嵌（第 1 孔 → 第 5 孔），已镶嵌的孔位可随时取出。</p>
        </div>
      </div>
    </section>

    <!-- 合成 -->
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-sm font-semibold text-white">魔晶石合成</h3>
        <span class="text-xs text-ink-400">
          {{ state?.mergeFrom ?? 5 }} 个同级同种 → 1 个高一级
        </span>
        <InfoTip title="合成规则">
          <p>{{ state?.mergeFrom ?? 5 }} 个相同的低级魔晶石合成为 1 个对应种类的高一级魔晶石。</p>
          <p>最高 {{ state?.maxLevel ?? 5 }} 级，满级后不可继续合成。</p>
          <p class="text-ink-400">来源：shared/data/materia.json:mergeFrom。</p>
        </InfoTip>
      </div>

      <div v-if="mergeable.length" class="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="entry in mergeable"
          :key="entry.id"
          class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2 text-xs"
        >
          <ItemIcon :base-id="entry.id" :size="24" variant="plain" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-ink-100">{{ entry.name }}</p>
            <p class="text-ink-400">持有 {{ entry.count }}</p>
          </div>
          <button
            class="shrink-0 rounded bg-amber-500 px-2 py-1 text-ink-950 hover:bg-amber-400 disabled:opacity-50"
            :disabled="busy"
            @click="merge(entry)"
          >
            合成
          </button>
        </div>
      </div>
      <p v-else class="mt-2 text-[11px] text-ink-500">暂无可合成的魔晶石（需要 {{ state?.mergeFrom ?? 5 }} 个同级同种）。</p>
    </section>

    <!-- 库存 -->
    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">魔晶石库存</h3>
      <p class="mt-1 text-[11px] text-ink-500">魔晶石由挖宝产出，可在「背包 / 物品」中出售换金币。</p>
      <div class="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3 lg:grid-cols-6">
        <div
          v-for="entry in state?.stock ?? []"
          :key="entry.id"
          class="flex items-center gap-2 rounded-md border p-2"
          :class="entry.count > 0 ? 'border-ink-700 bg-ink-800/40' : 'border-ink-800/60 bg-ink-900/40 opacity-60'"
        >
          <ItemIcon :base-id="entry.id" :size="20" variant="plain" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-ink-200">{{ entry.name }}</p>
            <p class="text-ink-500">{{ statLabel(entry.stat, entry.statName) }} +{{ entry.value }}</p>
          </div>
          <span class="font-mono" :class="entry.count > 0 ? 'text-amber-300' : 'text-ink-600'">
            {{ entry.count }}
          </span>
        </div>
      </div>
    </section>

    <!-- 选择魔晶石 -->
    <Modal
      :open="picker !== null"
      :title="`镶嵌魔晶石（第 ${(picker?.index ?? 0) + 1} 孔 · 成功率 ${Math.round(((state?.successChance ?? [])[picker?.index ?? 0] ?? 0) * 100)}%）`"
      max-width="max-w-2xl"
      @close="picker = null"
    >
      <p class="mb-2 text-[11px] text-ink-400">镶嵌失败会消耗该魔晶石（成功率见标题）。</p>
      <div v-if="available.length" class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
        <button
          v-for="entry in available"
          :key="entry.id"
          class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/40 p-2 text-left transition hover:border-amber-400"
          :disabled="busy"
          @click="socket(entry.id)"
        >
          <ItemIcon :base-id="entry.id" :size="24" variant="plain" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-ink-100">{{ entry.name }}</p>
            <p class="text-emerald-300">{{ statLabel(entry.stat, entry.statName) }} +{{ entry.value }}</p>
          </div>
          <span class="font-mono text-amber-300">×{{ entry.count }}</span>
        </button>
      </div>
      <p v-else class="py-6 text-center text-xs text-ink-500">没有可用的魔晶石，去「挖宝」副本获取。</p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm text-ink-200 hover:bg-ink-600" @click="picker = null">
          取消
        </button>
      </template>
    </Modal>
  </div>
</template>
