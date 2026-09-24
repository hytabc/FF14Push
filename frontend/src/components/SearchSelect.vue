<script lang="ts">
export interface SearchOption {
  value: string
  label: string
  /** 右侧灰色说明（如地区名）。 */
  hint?: string
  /** 传入则渲染物品图标。 */
  iconId?: string
  /** 角标文案（如「等级不足」）。 */
  badge?: string
  badgeClass?: string
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'

import ItemIcon from '@/components/ItemIcon.vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: SearchOption[]
    placeholder?: string
    disabled?: boolean
    emptyText?: string
    /** 下拉最多展示多少项。 */
    maxVisible?: number
  }>(),
  { placeholder: '搜索…', disabled: false, emptyText: '无匹配项', maxVisible: 80 },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const query = ref('')
const open = ref(false)

const selected = computed(() => props.options.find((o) => o.value === props.modelValue) ?? null)

const filtered = computed(() => {
  const kw = query.value.trim()
  const list = kw
    ? props.options.filter((o) => o.label.includes(kw) || o.hint?.includes(kw))
    : props.options
  return list.slice(0, props.maxVisible)
})

function pick(option: SearchOption) {
  emit('update:modelValue', option.value)
  query.value = ''
  open.value = false
}

function clear() {
  emit('update:modelValue', '')
  query.value = ''
}

function onFocus() {
  if (props.disabled) return
  open.value = true
}
</script>

<template>
  <div class="relative">
    <div
      class="flex items-center gap-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 outline-none focus-within:border-amber-400"
      :class="disabled ? 'opacity-40' : ''"
    >
      <ItemIcon v-if="selected?.iconId" :base-id="selected.iconId" variant="plain" :size="18" />
      <input
        v-model="query"
        type="text"
        class="w-44 min-w-0 flex-1 bg-transparent text-xs text-ink-100 outline-none placeholder:text-ink-500"
        :placeholder="selected ? selected.label : placeholder"
        :disabled="disabled"
        @focus="onFocus"
        @keydown.esc="open = false"
      >
      <span v-if="selected && !open" class="truncate text-[11px] text-ink-400">{{ selected.label }}</span>
      <button
        v-if="selected && !disabled"
        type="button"
        class="shrink-0 rounded px-1 text-[11px] text-ink-500 hover:text-rose-300"
        title="清除"
        @click="clear"
      >
        ✕
      </button>
    </div>

    <template v-if="open">
      <div class="fixed inset-0 z-10" @click="open = false" />
      <div
        class="absolute left-0 top-full z-20 mt-1 max-h-64 w-full min-w-72 overflow-y-auto overscroll-contain rounded-lg border border-ink-600 bg-ink-900 p-1 shadow-xl"
      >
        <button
          v-for="o in filtered"
          :key="o.value"
          type="button"
          class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition hover:bg-ink-800"
          :class="o.value === modelValue ? 'bg-ink-800/60 text-amber-200' : 'text-ink-200'"
          @click="pick(o)"
        >
          <ItemIcon v-if="o.iconId" :base-id="o.iconId" variant="plain" :size="18" />
          <span class="truncate">{{ o.label }}</span>
          <span v-if="o.hint" class="ml-auto shrink-0 text-[10px] text-ink-500">{{ o.hint }}</span>
          <span
            v-if="o.badge"
            class="shrink-0 rounded px-1.5 py-0.5 text-[10px]"
            :class="o.badgeClass ?? 'bg-rose-500/20 text-rose-300'"
          >
            {{ o.badge }}
          </span>
        </button>
        <p v-if="!filtered.length" class="px-2 py-1 text-[11px] text-ink-500">{{ emptyText }}</p>
      </div>
    </template>
  </div>
</template>
