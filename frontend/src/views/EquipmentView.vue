<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import data from '@shared/schema'
import { api } from '@/api'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import ItemPickerModal from '@/components/ItemPickerModal.vue'
import Modal from '@/components/Modal.vue'
import TermBadges from '@/components/TermBadges.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { Item, SlotId } from '@/game/types'
import { rarityBg, rarityClass, rarityName, slotName, baseAttrName, attrRangeLabel, formatNumber, jobName } from '@/utils/format'
import { roleOfBaseId } from '@/utils/itemFilters'
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

/** 英雄当前职能：由已装备主手武器决定；无武器时不限制防具/饰品的职能。 */
const heroRole = computed(() => roleOfBaseId(loadout.value['mainHand']?.baseId ?? null))

/** 一键最强：需要主手武器作为职业锚点。 */
const hasWeapon = computed(() => !!loadout.value['mainHand'])
const autoEquipOpen = ref(false)
const includeEquipped = ref(false)
const autoEquipBusy = ref(false)
const autoEquipPreview = ref<Awaited<ReturnType<typeof api.autoEquipPreview>> | null>(null)

async function loadAutoEquipPreview() {
  if (!hasWeapon.value) return
  try {
    autoEquipPreview.value = await api.autoEquipPreview(includeEquipped.value)
  } catch (e) {
    autoEquipPreview.value = null
    toast.push(e instanceof Error ? e.message : '预览失败', 'error')
  }
}

async function openAutoBest() {
  if (!hasWeapon.value) return
  includeEquipped.value = false
  autoEquipOpen.value = true
  await loadAutoEquipPreview()
}

async function confirmAutoBest() {
  autoEquipBusy.value = true
  try {
    await game.autoEquip(includeEquipped.value)
    autoEquipOpen.value = false
  } finally {
    autoEquipBusy.value = false
  }
}

watch(includeEquipped, () => {
  void loadAutoEquipPreview()
})

/** 该候选来自其他英雄（本英雄换栏位不算「取自其他英雄」）。 */
function fromOtherHero(item: Item): boolean {
  return !!item.equippedHeroId && item.equippedHeroId !== game.hero?.id
}

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
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-semibold text-white">英雄装备</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs text-ink-400">共 {{ slots.length }} 个栏位（含双戒指）</span>
          <button
            class="rounded bg-amber-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!hasWeapon || autoEquipBusy"
            :title="hasWeapon ? '保留当前武器，一键装备各栏位战力最高的装备' : '请先装备一把武器'"
            @click="openAutoBest"
          >
            一键最强
          </button>
        </div>
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
      :hero-role="heroRole"
      :slot-is-weapon="pickerSlot === 'mainHand'"
      slot-scoped
      show-equipped-filter
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

    <Modal :open="autoEquipOpen" title="一键最强" @close="autoEquipOpen = false">
      <div class="space-y-3 text-sm">
        <p class="text-xs text-ink-400">
          保留当前主手武器作为职业锚点，把其余栏位换成符合「{{ jobName(autoEquipPreview?.jobId ?? '') }}」职能、战力最高的装备。
        </p>

        <div
          v-if="autoEquipPreview?.weapon"
          class="rounded border border-ink-700 bg-ink-900/50 px-3 py-2 text-xs"
        >
          <span class="text-ink-400">锚定武器：</span>
          <span :class="rarityClass(autoEquipPreview.weapon.rarity)">{{ autoEquipPreview.weapon.name }}</span>
          <span class="text-ink-400"> · {{ jobName(autoEquipPreview.jobId) }} · 战力 {{ formatNumber(autoEquipPreview.weapon.score) }}</span>
        </div>

        <label class="flex flex-wrap items-center gap-2 text-xs text-ink-200">
          <input v-model="includeEquipped" type="checkbox" class="accent-amber-500" />
          包含已被其他英雄装备的装备
          <span class="text-ink-500">（勾选后会把它们从原英雄身上取下）</span>
        </label>

        <div v-if="autoEquipPreview?.changes.length" class="max-h-80 space-y-1.5 overflow-y-auto">
          <div
            v-for="change in autoEquipPreview.changes"
            :key="change.slot"
            class="rounded border border-ink-700 bg-ink-900/40 px-3 py-2 text-xs"
          >
            <span class="text-ink-400">{{ slotName(change.slot) }}：</span>
            <span v-if="change.current" class="text-ink-400 line-through">{{ change.current.name }}</span>
            <span v-else class="text-ink-500">空</span>
            <span class="mx-1 text-ink-500">→</span>
            <span :class="rarityClass(change.next.rarity)">{{ change.next.name }}</span>
            <span class="text-amber-300"> 战力 {{ formatNumber(change.next.score) }}</span>
            <span
              v-if="fromOtherHero(change.next)"
              class="ml-1 rounded bg-rose-500/20 px-1 py-0.5 text-[10px] text-rose-200"
            >
              取自 {{ game.heroLabel(change.next.equippedHeroId) }}
            </span>
          </div>
        </div>
        <p v-else-if="autoEquipPreview" class="py-6 text-center text-xs text-ink-400">已是最强配置，无需更换。</p>
        <p v-else class="py-6 text-center text-xs text-ink-400">正在计算…</p>
      </div>

      <template #footer>
        <button class="rounded bg-ink-700 px-3 py-1.5 text-xs hover:bg-ink-600" @click="autoEquipOpen = false">
          取消
        </button>
        <button
          class="rounded bg-amber-600 px-3 py-1.5 text-xs text-white hover:bg-amber-500 disabled:opacity-40"
          :disabled="autoEquipBusy || !autoEquipPreview?.changes.length"
          @click="confirmAutoBest"
        >
          确认装备
        </button>
      </template>
    </Modal>
  </div>
</template>
