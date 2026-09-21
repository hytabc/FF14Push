<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import ItemCard from '@/components/ItemCard.vue'
import Modal from '@/components/Modal.vue'
import { useToastStore } from '@/stores/toast'
import type { PlayerProfile } from '@/game/types'
import { formatNumber, jobName, rarityClass, rarityName } from '@/utils/format'
import { equipmentSlotGroups } from '@/utils/slots'

const props = defineProps<{ userId: number | null }>()
const emit = defineEmits<{ close: [] }>()

const toast = useToastStore()
const profile = ref<PlayerProfile | null>(null)
const loading = ref(false)

const groups = computed(() => equipmentSlotGroups())
const title = computed(() => (profile.value ? `${profile.value.nickname} 的装备` : '查看装备'))

watch(
  () => props.userId,
  async (id) => {
    if (id === null) return
    loading.value = true
    profile.value = null
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
  <Modal :open="userId !== null" :title="title" max-width="max-w-3xl" @close="emit('close')">
    <p v-if="loading" class="py-10 text-center text-xs text-ink-500">加载中…</p>

    <div v-else-if="profile" class="space-y-4 text-sm">
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-medium text-ink-100">{{ profile.nickname }}</span>
          <span class="text-ink-500">#{{ profile.username }}</span>
          <span class="ml-auto font-mono text-amber-300">战力 {{ formatNumber(profile.power) }}</span>
        </div>
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

      <div class="space-y-3">
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
                class="rounded-lg border border-dashed border-ink-700 px-3 py-2 text-[11px] text-ink-600"
              >
                {{ slot.name }}：空
              </div>
            </template>
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
