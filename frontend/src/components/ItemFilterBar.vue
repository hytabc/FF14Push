<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Item } from '@/game/types'
import { RARITY_ORDER, rarityName } from '@/utils/format'
import {
  type ItemFilterState,
  createItemFilters,
  filterOptionSets,
  hasActiveFilters,
  roleOfBaseId,
} from '@/utils/itemFilters'

const props = withDefaults(
  defineProps<{
    modelValue: ItemFilterState
    /** 候选池：用于派生各筛选的可选项，只列出实际存在的值。 */
    pool: Item[]
    showSearch?: boolean
    showRarity?: boolean
    showCategory?: boolean
    showSlot?: boolean
    showWeaponType?: boolean
    showRole?: boolean
  }>(),
  {
    showSearch: true,
    showRarity: false,
    showCategory: true,
    showSlot: true,
    showWeaponType: true,
    showRole: true,
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: ItemFilterState] }>()

const chipsOpen = ref(false)

const options = computed(() => filterOptionSets(props.pool))
const active = computed(() => hasActiveFilters(props.modelValue))
/** 候选池里没有任何一件能判定职能（如纯专用装备池）时，隐藏职能筛选。 */
const roleAvailable = computed(() => props.pool.some((i) => roleOfBaseId(i.baseId)))
const hasChips = computed(
  () => options.value.subAttrs.length > 0 || options.value.terms.length > 0 || options.value.bonuses.length > 0,
)

function update(patch: Partial<ItemFilterState>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function setLevel(key: 'levelMin' | 'levelMax', raw: string) {
  const n = raw === '' ? '' : Number(raw)
  update({ [key]: Number.isNaN(n as number) ? '' : n } as Partial<ItemFilterState>)
}

function toggle(key: 'subAttrs' | 'terms' | 'quality' | 'bonus', id: string) {
  const next = new Set(props.modelValue[key] as Set<string>)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  emit('update:modelValue', { ...props.modelValue, [key]: next } as ItemFilterState)
}

function reset() {
  emit('update:modelValue', createItemFilters())
}
</script>

<template>
  <div class="space-y-2 text-xs">
    <div class="flex flex-wrap items-center gap-2">
      <input
        v-if="showSearch"
        :value="modelValue.query"
        type="text"
        placeholder="按名称搜索"
        class="w-40 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-ink-100 outline-none focus:border-amber-400"
        @input="update({ query: ($event.target as HTMLInputElement).value })"
      />

      <select
        v-if="showRarity"
        :value="modelValue.rarity"
        class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        @change="update({ rarity: ($event.target as HTMLSelectElement).value as ItemFilterState['rarity'] })"
      >
        <option value="all">全部品阶</option>
        <option v-for="r in RARITY_ORDER" :key="r" :value="r">{{ rarityName(r) }}</option>
      </select>

      <select
        v-if="showCategory && options.categories.length > 1"
        :value="modelValue.category"
        class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        @change="update({ category: ($event.target as HTMLSelectElement).value })"
      >
        <option value="all">全部种类</option>
        <option v-for="o in options.categories" :key="o.id" :value="o.id">{{ o.label }}</option>
      </select>

      <select
        v-if="showSlot && options.slots.length > 1"
        :value="modelValue.slot"
        class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        @change="update({ slot: ($event.target as HTMLSelectElement).value })"
      >
        <option value="all">全部部位</option>
        <option v-for="o in options.slots" :key="o.id" :value="o.id">{{ o.label }}</option>
      </select>

      <select
        v-if="showWeaponType && options.weaponTypes.length > 1"
        :value="modelValue.weaponType"
        class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        @change="update({ weaponType: ($event.target as HTMLSelectElement).value })"
      >
        <option value="all">全部武器</option>
        <option v-for="o in options.weaponTypes" :key="o.id" :value="o.id">{{ o.label }}</option>
      </select>

      <select
        v-if="showRole && roleAvailable"
        :value="modelValue.role"
        class="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
        @change="update({ role: ($event.target as HTMLSelectElement).value as ItemFilterState['role'] })"
      >
        <option value="all">全部职能</option>
        <option v-for="r in ['tank', 'healer', 'melee', 'physicalRanged', 'magicalRanged']" :key="r" :value="r">
          {{ { tank: '坦克', healer: '治疗', melee: '近战DPS', physicalRanged: '远程物理DPS', magicalRanged: '远程魔法DPS' }[r] }}
        </option>
      </select>

      <label class="flex items-center gap-1 text-ink-400">
        等级
        <input
          :value="modelValue.levelMin"
          type="number"
          min="1"
          step="1"
          placeholder="最低"
          class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          @input="setLevel('levelMin', ($event.target as HTMLInputElement).value)"
        />
        <span class="text-ink-400">-</span>
        <input
          :value="modelValue.levelMax"
          type="number"
          min="1"
          step="1"
          placeholder="最高"
          class="w-16 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus:border-amber-400"
          @input="setLevel('levelMax', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <button
        v-if="hasChips"
        class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
        @click="chipsOpen = !chipsOpen"
      >
        {{ chipsOpen ? '收起词条筛选' : '词条 / 副词条' }}
      </button>
      <button
        v-if="active"
        class="rounded bg-ink-800 px-2.5 py-1.5 text-ink-300 transition hover:bg-ink-700"
        @click="reset"
      >
        重置
      </button>
    </div>

    <div v-if="chipsOpen && hasChips" class="space-y-2 border-t border-ink-700 pt-2">
      <div v-if="options.subAttrs.length" class="flex flex-wrap items-center gap-1.5">
        <span class="shrink-0 text-ink-400">副词条：</span>
        <button
          v-for="o in options.subAttrs"
          :key="o.id"
          class="rounded-full border px-2.5 py-1 transition"
          :class="modelValue.subAttrs.has(o.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="toggle('subAttrs', o.id)"
        >
          {{ o.label }}
        </button>
      </div>

      <div v-if="options.terms.length" class="flex flex-wrap items-center gap-1.5">
        <span class="shrink-0 text-ink-400">词条：</span>
        <button
          v-for="o in options.terms"
          :key="o.id"
          class="rounded-full border px-2.5 py-1 transition"
          :class="modelValue.terms.has(o.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="toggle('terms', o.id)"
        >
          {{ o.label }}
        </button>
      </div>

      <div class="flex flex-wrap items-center gap-1.5">
        <span class="shrink-0 text-ink-400">品质：</span>
        <button
          v-for="q in (['common', 'rare', 'ancient'] as const)"
          :key="q"
          class="rounded-full border px-2.5 py-1 transition"
          :class="modelValue.quality.has(q) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="toggle('quality', q)"
        >
          {{ { common: '普通', rare: '稀有', ancient: '太古' }[q] }}
        </button>
        <span class="text-ink-400">副属性或词条品质命中任一</span>
      </div>

      <div v-if="options.bonuses.length" class="flex flex-wrap items-center gap-1.5">
        <span class="shrink-0 text-ink-400">专用加成：</span>
        <button
          v-for="o in options.bonuses"
          :key="o.id"
          class="rounded-full border px-2.5 py-1 transition"
          :class="modelValue.bonus.has(o.id) ? 'border-amber-400 bg-amber-500/20 text-amber-200' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          @click="toggle('bonus', o.id)"
        >
          {{ o.label }}
        </button>
      </div>
    </div>
  </div>
</template>
