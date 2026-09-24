<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import ItemCard from '@/components/ItemCard.vue'
import ItemIcon from '@/components/ItemIcon.vue'
import Modal from '@/components/Modal.vue'
import TermBadges from '@/components/TermBadges.vue'
import { useToastStore } from '@/stores/toast'
import type { PlayerProfile } from '@/game/types'
import { formatNumber, formatPlaytime, jobName, rarityBg, rarityClass, rarityName, attrRangeLabel } from '@/utils/format'
import { dohdolSlotGroups, equipmentSlotGroups } from '@/utils/slots'

const props = defineProps<{ userId: number | null }>()
const emit = defineEmits<{ close: [] }>()

const toast = useToastStore()
const profile = ref<PlayerProfile | null>(null)
const loading = ref(false)
const tab = ref<'combat' | 'dohdol'>('combat')

const groups = computed(() => equipmentSlotGroups())
const title = computed(() => (profile.value ? `${profile.value.nickname} 的装备` : '查看装备'))

const dohdolGroups = computed(() => dohdolSlotGroups())
const dohdolBonusNames: Record<string, string> = data.dohdolEquipment.bonusNames

/** 该玩家佩戴中的称号名（未佩戴为 null）。 */
const activeTitleName = computed(() => {
  const id = profile.value?.activeTitleId
  if (!id) return null
  return data.titles.titles.find((t) => t.id === id)?.name ?? id
})

function dohdolBonusName(attr: string): string {
  return dohdolBonusNames[attr] ?? attr
}

watch(
  () => props.userId,
  async (id) => {
    if (id === null) return
    loading.value = true
    profile.value = null
    tab.value = 'combat'
    try {
      profile.value = await api.playerProfile(id)
    } catch (e) {
      toast.push(toApiError(e).message, 'error')
      emit('close')
    } finally {
      loading.value = false
    }
  },
)
</script>

<template>
  <Modal :open="userId !== null" :title="title" max-width="max-w-4xl" @close="emit('close')">
    <p v-if="loading" class="py-10 text-center text-xs text-ink-500">加载中…</p>

    <div v-else-if="profile" class="space-y-4 text-sm">
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-medium text-ink-100">{{ profile.nickname }}</span>
          <span class="text-ink-500">#{{ profile.username }}</span>
          <span
            v-if="activeTitleName"
            class="inline-block rounded border border-amber-400 bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-100"
          >{{ activeTitleName }}</span>
          <span class="ml-auto font-mono text-amber-300">战力 {{ formatNumber(profile.power) }}</span>
        </div>
        <p class="mt-1 text-ink-400">游玩时间 {{ formatPlaytime(profile.playSeconds) }}</p>
        <template v-if="profile.hero">
          <p class="mt-1 text-ink-400">
            Lv.{{ profile.hero.level }} · {{ jobName(profile.hero.jobId) }} ·
            <span :class="rarityClass(profile.hero.talent)">{{ rarityName(profile.hero.talent) }}资质</span>
          </p>
          <p class="mt-1 text-ink-400">
            力量 {{ profile.hero.strength }}{{ profile.hero.ancientAttr === 'str' ? '🌟' : '' }} /
            敏捷 {{ profile.hero.agility }}{{ profile.hero.ancientAttr === 'dex' ? '🌟' : '' }} /
            智力 {{ profile.hero.intellect }}{{ profile.hero.ancientAttr === 'int' ? '🌟' : '' }}
          </p>
        </template>
      </div>

      <div class="flex gap-1 rounded-lg bg-ink-800 p-1 text-xs">
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="tab === 'combat' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="tab = 'combat'"
        >
          战斗装备
        </button>
        <button
          class="flex-1 rounded-md py-1.5 transition"
          :class="tab === 'dohdol' ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="tab = 'dohdol'"
        >
          生产采集装备
        </button>
      </div>

      <!-- 战斗装备 -->
      <div v-if="tab === 'combat'" class="space-y-3">
        <div v-for="group in groups" :key="group.key">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="grid gap-2" :class="group.full ? '' : 'sm:grid-cols-2'">
            <template v-for="slot in group.slots" :key="slot.id">
              <ItemCard
                v-if="profile.loadout[slot.id]"
                :item="profile.loadout[slot.id]!"
                :show-actions="false"
              />
              <div
                v-else
                class="rounded-lg border border-dashed border-ink-700 px-3 py-2 text-[11px] text-ink-400"
              >
                {{ slot.name }}：空
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 生产 / 采集专用装备 -->
      <div v-else class="grid gap-4 lg:grid-cols-2">
        <div v-for="group in dohdolGroups" :key="group.key">
          <p class="mb-2 text-xs font-medium text-ink-400">{{ group.title }}</p>
          <div class="grid gap-2 sm:grid-cols-2">
            <div
              v-for="slot in group.slots"
              :key="slot.id"
              class="rounded-lg border p-3"
              :class="
                profile.dohdolLoadout[slot.id]
                  ? [rarityClass(profile.dohdolLoadout[slot.id]!.rarity), rarityBg(profile.dohdolLoadout[slot.id]!.rarity)]
                  : 'border-ink-700 bg-ink-800/60'
              "
            >
              <div class="flex items-start gap-2">
                <ItemIcon
                  v-if="profile.dohdolLoadout[slot.id]"
                  :base-id="profile.dohdolLoadout[slot.id]!.baseId"
                  :rarity="profile.dohdolLoadout[slot.id]!.rarity"
                  :size="28"
                />
                <div class="min-w-0 flex-1">
                  <p class="text-[11px] text-ink-400">{{ slot.name }}</p>
                  <template v-if="profile.dohdolLoadout[slot.id]">
                    <p class="truncate text-sm font-medium">{{ profile.dohdolLoadout[slot.id]!.name }}</p>
                    <p class="text-[10px] text-ink-400">
                      {{ rarityName(profile.dohdolLoadout[slot.id]!.rarity) }} · Lv.{{ profile.dohdolLoadout[slot.id]!.levelReq }}
                    </p>
                    <div class="mt-1 space-y-0.5 text-[10px] text-ink-300">
                      <p v-for="entry in profile.dohdolLoadout[slot.id]!.baseAttrs" :key="entry.attr">
                        {{ dohdolBonusName(entry.attr) }} +{{ entry.value }}
                        <span class="font-mono text-ink-500">{{ attrRangeLabel(entry.min, entry.max, 1) }}</span>
                      </p>
                    </div>
                    <TermBadges class="mt-1" :terms="profile.dohdolLoadout[slot.id]!.terms" />
                  </template>
                  <p v-else class="mt-1 text-xs text-ink-400">空</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p class="text-[11px] text-ink-500">仅显示该玩家当前已装备的栏位（只读）。</p>
    </div>

    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="emit('close')">
        关闭
      </button>
    </template>
  </Modal>
</template>
