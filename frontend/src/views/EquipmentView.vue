<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import data from '@shared/schema'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import type { Item, SlotId } from '@/game/types'
import { rarityBg, rarityClass, rarityName, slotName, baseAttrName } from '@/utils/format'

const game = useGameStore()
const pickerSlot = ref<SlotId | null>(null)

const slots = computed(() => [...data.slots].sort((a, b) => a.order - b.order))

/** 栏位分组：左侧防具、右侧饰品、下方武器（整行）。 */
const slotGroups = computed(() => {
  const byId = new Map(slots.value.map((s) => [s.id, s]))
  const pick = (ids: SlotId[]) => ids.map((id) => byId.get(id)).filter((s) => s !== undefined)
  return [
    { key: 'armor', title: '防具', slots: pick(['head', 'body', 'hands', 'legs', 'feet']), full: false },
    {
      key: 'accessory',
      title: '饰品',
      slots: pick(['necklace', 'earring', 'bracelet', 'ring1', 'ring2']),
      full: false,
    },
    { key: 'weapon', title: '武器', slots: pick(['mainHand']), full: true },
  ]
})

const loadout = computed(() => game.loadout)

const candidates = computed<Item[]>(() => {
  if (!pickerSlot.value) return []
  return game.items
    .filter((item) => item.equipSlots.includes(pickerSlot.value as SlotId))
    .sort((a, b) => b.score - a.score || b.levelReq - a.levelReq || a.name.localeCompare(b.name))
})

const slotCategory = computed(() => {
  if (!pickerSlot.value) return ''
  return data.slots.find((s) => s.id === pickerSlot.value)?.category ?? ''
})

onMounted(async () => {
  if (!game.state) await game.loadState()
})

function openPicker(slotId: SlotId) {
  pickerSlot.value = slotId
}

async function equip(item: Item, slotId: SlotId) {
  await game.equip(item.id, slotId)
  pickerSlot.value = null
}

async function unequip(slotId: SlotId) {
  await game.unequip(slotId)
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-white">英雄装备</h2>
        <span class="text-xs text-ink-400">共 {{ slots.length }} 个栏位（含双戒指）</span>
      </div>

      <div class="mt-4 grid gap-3 lg:grid-cols-2">
        <div v-for="group in slotGroups" :key="group.key" :class="group.full ? 'lg:col-span-2' : ''">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="space-y-2">
            <button
              v-for="slot in group.slots"
              :key="slot.id"
              class="w-full rounded-lg border p-3 text-left transition hover:border-white/40"
              :class="loadout[slot.id] ? [rarityClass(loadout[slot.id]!.rarity), rarityBg(loadout[slot.id]!.rarity)] : 'border-ink-700 bg-ink-800/60'"
              @click="openPicker(slot.id)"
            >
              <div class="flex items-center gap-3">
                <ItemIcon
                  v-if="loadout[slot.id]"
                  :base-id="loadout[slot.id]!.baseId"
                  :rarity="loadout[slot.id]!.rarity"
                  :size="32"
                />
                <div class="min-w-0 flex-1">
                  <p class="text-[11px] text-ink-400">{{ slot.name }}</p>
                  <template v-if="loadout[slot.id]">
                    <p class="truncate text-sm font-medium">{{ loadout[slot.id]!.name }}</p>
                    <p class="text-[10px] text-ink-400">
                      {{ rarityName(loadout[slot.id]!.rarity) }} · Lv.{{ loadout[slot.id]!.levelReq }}
                    </p>
                    <div class="mt-1 space-y-0.5 text-[10px] text-ink-300">
                      <p v-for="entry in loadout[slot.id]!.baseAttrs" :key="entry.attr">
                        {{ baseAttrName(entry.attr) }} +{{ Math.round(entry.value) }}
                      </p>
                    </div>
                  </template>
                  <p v-else class="mt-1 text-xs text-ink-600">空 — 点击选择装备</p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section v-if="Object.keys(loadout).length" class="card p-4">
      <h3 class="text-sm font-semibold text-white">已装备详情</h3>
      <div class="mt-3 grid gap-2 md:grid-cols-2">
        <div v-for="slot in slots" :key="slot.id">
          <ItemCard
            v-if="loadout[slot.id]"
            :item="loadout[slot.id]!"
            :show-actions="true"
            @unequip="unequip(slot.id)"
            @select="openPicker(slot.id)"
          />
        </div>
      </div>
    </section>

    <Modal
      :open="!!pickerSlot"
      :title="`选择装备 · ${pickerSlot ? slotName(pickerSlot) : ''}`"
      max-width="max-w-3xl"
      @close="pickerSlot = null"
    >
      <p class="mb-3 text-xs text-ink-400">
        仅显示可放入该栏位的装备（无等级限制），已按战力从高到低排序。
      </p>
      <div class="max-h-[55vh] space-y-2 overflow-y-auto pr-1">
        <button
          v-if="loadout[pickerSlot!]"
          class="w-full rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-left text-xs text-rose-200"
          @click="unequip(pickerSlot!)"
        >
          卸下当前装备（{{ loadout[pickerSlot!]!.name }}）
        </button>

        <ItemCard
          v-for="item in candidates"
          :key="item.id"
          :item="item"
          :show-actions="false"
          :equipped="item.equippedSlot === pickerSlot"
          @select="equip(item, pickerSlot!)"
        />
        <p v-if="!candidates.length" class="py-6 text-center text-xs text-ink-600">
          背包中没有可用于「{{ slotCategory }}」栏位的装备，去抽箱页面获取吧。
        </p>
      </div>
    </Modal>
  </div>
</template>
