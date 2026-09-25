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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

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

const DROPDOWN_MIN_WIDTH = 288
const DROPDOWN_MAX_HEIGHT = 256

const query = ref('')
const open = ref(false)
const root = ref<HTMLElement | null>(null)
/** 下拉面板的 fixed 定位（相对视口）；面板 Teleport 到 body，避免被 card 的 backdrop-filter 层叠上下文夹住。 */
const pos = ref({ top: 0, left: 0, width: DROPDOWN_MIN_WIDTH })

const selected = computed(() => props.options.find((o) => o.value === props.modelValue) ?? null)

const filtered = computed(() => {
  const kw = query.value.trim()
  const list = kw
    ? props.options.filter((o) => o.label.includes(kw) || o.hint?.includes(kw))
    : props.options
  return list.slice(0, props.maxVisible)
})

/** 依据触发框位置计算面板坐标：水平夹进视口，下方空间不足时向上展开。 */
function updatePos() {
  const rect = root.value?.getBoundingClientRect()
  if (!rect) return
  const width = Math.max(rect.width, DROPDOWN_MIN_WIDTH)
  const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 8))
  const below = rect.bottom + 4
  const flip = below + DROPDOWN_MAX_HEIGHT > window.innerHeight && rect.top - DROPDOWN_MAX_HEIGHT - 4 > 0
  pos.value = { top: flip ? rect.top - DROPDOWN_MAX_HEIGHT - 4 : below, left, width }
}

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
  updatePos()
  open.value = true
}

/** 滚动 / 缩放时让面板跟随触发框（在面板内部滚动也会触发，故只重算位置、不关闭）。 */
function reposition() {
  if (open.value) updatePos()
}

onMounted(() => {
  window.addEventListener('scroll', reposition, true)
  window.addEventListener('resize', reposition)
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', reposition, true)
  window.removeEventListener('resize', reposition)
})
</script>

<template>
  <div ref="root" class="relative">
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
        @click="onFocus"
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

    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-[45]" @click="open = false" />
      <div
        v-if="open"
        class="fixed z-[46] max-h-64 overflow-y-auto overscroll-contain rounded-lg border border-ink-600 bg-ink-900 p-1 shadow-xl"
        :style="{ top: `${pos.top}px`, left: `${pos.left}px`, width: `${pos.width}px` }"
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
    </Teleport>
  </div>
</template>
