<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import data from '@shared/schema'
import { api } from '@/api'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import ItemPickerModal from '@/components/ItemPickerModal.vue'
import TermBadges from '@/components/TermBadges.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { Item, SlotId } from '@/game/types'
import { rarityBg, rarityClass, rarityName, slotName, baseAttrName, attrRangeLabel } from '@/utils/format'
import { dohdolSlotGroups, equipmentSlotGroups } from '@/utils/slots'

const game = useGameStore()
const toast = useToastStore()
const pickerSlot = ref<SlotId | null>(null)
const dohdolSlot = ref<string | null>(null)

const DEDICATED_CATEGORIES = new Set(['doh_tool', 'doh_gear', 'dol_tool', 'dol_gear'])
const DOHDOL_BONUS_NAMES: Record<string, string> = data.dohdolEquipment.bonusNames

function dohdolBonusName(attr: string): string {
  return DOHDOL_BONUS_NAMES[attr] ?? attr
}

const dohdolSlots = computed(() => [...data.dohdolEquipment.slots].sort((a, b) => a.order - b.order))
/** 生产 / 采集专用装备分组：生产在左、采集在右。 */
const dohdolGroups = computed(() => dohdolSlotGroups())
const dohdolLoadout = computed(() => game.state?.dohdol?.loadout ?? {})
const dohdolCandidates = computed<Item[]>(() => {
  if (!dohdolSlot.value) return []
  return game.items
    .filter((item) => DEDICATED_CATEGORIES.has(item.category) && item.slot === dohdolSlot.value)
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
})

const slots = computed(() => [...data.slots].sort((a, b) => a.order - b.order))

/** 栏位分组：左侧防具、右侧饰品、下方武器（整行）。 */
const slotGroups = computed(() => equipmentSlotGroups())

const loadout = computed(() => game.loadout)

const candidates = computed<Item[]>(() => {
  if (!pickerSlot.value) return []
  return game.items
    .filter((item) => item.equipSlots.includes(pickerSlot.value as SlotId))
    .sort((a, b) => b.score - a.score || b.levelReq - a.levelReq || a.name.localeCompare(b.name))
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

async function equipDohdol(item: Item) {
  try {
    await api.dohdolEquip(item.id, item.slot)
    dohdolSlot.value = null
    await game.loadState()
  } catch (e) {
    toast.push(e instanceof Error ? e.message : '穿戴失败', 'error')
  }
}

async function unequipDohdol(slot: string) {
  try {
    await api.dohdolUnequip(slot)
    await game.loadState()
  } catch (e) {
    toast.push(e instanceof Error ? e.message : '卸下失败', 'error')
  }
}
</script>

<template>
  <div class="space-y-4">
    <section data-tutorial="equipment" class="card p-4">
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
                  <p v-else class="mt-1 text-xs text-ink-400">空 — 点击选择装备</p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="card p-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-white">生产 / 采集专用装备</h2>
        <span class="text-xs text-ink-400">仅能通过生产制造获取 · 不影响战力</span>
      </div>
      <div class="mt-4 grid gap-4 lg:grid-cols-2">
        <div v-for="group in dohdolGroups" :key="group.key">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="grid gap-2 sm:grid-cols-2">
            <button
              v-for="slot in group.slots"
              :key="slot.id"
              class="rounded-lg border p-3 text-left transition hover:border-white/40"
              :class="
                dohdolLoadout[slot.id]
                  ? [rarityClass(dohdolLoadout[slot.id]!.rarity), rarityBg(dohdolLoadout[slot.id]!.rarity)]
                  : 'border-ink-700 bg-ink-800/60'
              "
              @click="dohdolSlot = slot.id"
            >
              <div class="flex items-start gap-2">
                <ItemIcon
                  v-if="dohdolLoadout[slot.id]"
                  :base-id="dohdolLoadout[slot.id]!.baseId"
                  :rarity="dohdolLoadout[slot.id]!.rarity"
                  :size="28"
                />
                <div class="min-w-0 flex-1">
                  <p class="text-[11px] text-ink-400">{{ slot.name }}</p>
                  <template v-if="dohdolLoadout[slot.id]">
                    <p class="truncate text-sm font-medium">{{ dohdolLoadout[slot.id]!.name }}</p>
                    <div class="mt-1 space-y-0.5 text-[10px] text-ink-300">
                      <p v-for="entry in dohdolLoadout[slot.id]!.baseAttrs" :key="entry.attr">
                        {{ dohdolBonusName(entry.attr) }} +{{ entry.value }}
                        <span class="font-mono text-ink-500">{{ attrRangeLabel(entry.min, entry.max, 1) }}</span>
                      </p>
                    </div>
                    <TermBadges class="mt-1" :terms="dohdolLoadout[slot.id]!.terms" />
                  </template>
                  <p v-else class="mt-1 text-xs text-ink-400">空 — 点击选择</p>
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

    <ItemPickerModal
      :open="!!pickerSlot"
      :title="`选择装备 · ${pickerSlot ? slotName(pickerSlot) : ''}`"
      :candidates="candidates"
      :equipped="pickerSlot ? (loadout[pickerSlot] ?? null) : null"
      slot-scoped
      @close="pickerSlot = null"
      @equip="pickerSlot && equip($event, pickerSlot)"
      @unequip="pickerSlot && unequip(pickerSlot)"
    />

    <ItemPickerModal
      :open="!!dohdolSlot"
      :title="`选择专用装备 · ${dohdolSlot ? (dohdolSlots.find((s) => s.id === dohdolSlot)?.name ?? dohdolSlot) : ''}`"
      :candidates="dohdolCandidates"
      :equipped="dohdolSlot ? (dohdolLoadout[dohdolSlot] ?? null) : null"
      slot-scoped
      @close="dohdolSlot = null"
      @equip="equipDohdol"
      @unequip="dohdolSlot && unequipDohdol(dohdolSlot)"
    />
  </div>
</template>
