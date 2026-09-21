<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useTagsStore } from '@/stores/tags'
import { TAG_COLORS, tagColorHex } from '@/utils/format'

const game = useGameStore()
const tagsStore = useTagsStore()

const tags = computed(() => game.tags)
const assignItem = computed(() => tagsStore.assignItem)
const isAssign = computed(() => assignItem.value !== null)
const title = computed(() => {
  if (!isAssign.value) return '管理标签'
  const item = assignItem.value
  return item ? `标签 · ${item.name}` : '标签'
})

const newName = ref('')
const newColor = ref(TAG_COLORS[0]?.id ?? 'gray')
const confirmDeleteId = ref<number | null>(null)

watch(
  () => tagsStore.open,
  (open) => {
    if (open) {
      newName.value = ''
      confirmDeleteId.value = null
    }
  },
)

function hasTag(tagId: number): boolean {
  return (assignItem.value?.tagIds ?? []).includes(tagId)
}

async function submitNew() {
  const name = newName.value.trim()
  if (!name) return
  const tag = await tagsStore.createTag(name, newColor.value)
  if (tag) newName.value = ''
}

function chipStyle(colorId: string) {
  const hex = tagColorHex(colorId)
  return { color: hex, borderColor: hex, backgroundColor: `${hex}22` }
}

function swatchStyle(colorId: string, active: boolean) {
  const hex = tagColorHex(colorId)
  return { backgroundColor: active ? hex : `${hex}44`, borderColor: hex }
}

function onRenameInput(id: number, event: Event) {
  tagsStore.rename(id, (event.target as HTMLInputElement).value)
}

function onDelete(id: number) {
  if (confirmDeleteId.value === id) {
    tagsStore.remove(id)
    confirmDeleteId.value = null
  } else {
    confirmDeleteId.value = id
  }
}
</script>

<template>
  <Modal :open="tagsStore.open" :title="title" @close="tagsStore.close()">
    <div class="space-y-3 text-sm">
      <div class="rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <p class="mb-2 text-xs text-ink-400">{{ isAssign ? '新建标签并直接贴上' : '新建标签' }}</p>
        <div class="flex flex-wrap items-center gap-2">
          <input
            v-model="newName"
            maxlength="16"
            placeholder="标签名称（≤16 字）"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
            @keyup.enter="submitNew"
          />
          <button
            class="rounded bg-teal-600 px-2.5 py-1.5 text-xs text-white hover:bg-teal-500 disabled:opacity-40"
            :disabled="!newName.trim() || tagsStore.busy"
            @click="submitNew"
          >
            新建
          </button>
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <button
            v-for="c in TAG_COLORS"
            :key="c.id"
            class="h-6 w-6 rounded-full border-2 transition"
            :class="newColor === c.id ? 'scale-110' : 'opacity-70 hover:opacity-100'"
            :style="swatchStyle(c.id, newColor === c.id)"
            :title="c.name"
            @click="newColor = c.id"
          />
        </div>
      </div>

      <p v-if="!tags.length" class="py-4 text-center text-xs text-ink-500">
        还没有标签，先在上方新建一个。
      </p>

      <!-- 贴标签模式：勾选即切换 -->
      <div v-else-if="isAssign" class="flex flex-wrap gap-1.5">
        <button
          v-for="tag in tags"
          :key="tag.id"
          class="rounded-full border px-3 py-1 text-xs transition"
          :class="hasTag(tag.id) ? '' : 'border-ink-600 text-ink-300 hover:border-ink-400'"
          :style="hasTag(tag.id) ? chipStyle(tag.color) : undefined"
          @click="tagsStore.toggleOnItem(tag.id)"
        >
          <span v-if="hasTag(tag.id)">✓ </span>{{ tag.name }}
        </button>
      </div>

      <!-- 管理模式：改名 / 改色 / 删除 -->
      <ul v-else class="space-y-2">
        <li
          v-for="tag in tags"
          :key="tag.id"
          class="rounded-lg border border-ink-700 bg-ink-800/60 p-2.5"
        >
          <div class="flex items-center gap-2">
            <input
              :value="tag.name"
              maxlength="16"
              class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1 text-xs"
              @change="onRenameInput(tag.id, $event)"
            />
            <button
              class="shrink-0 rounded px-2 py-1 text-xs"
              :class="
                confirmDeleteId === tag.id
                  ? 'bg-rose-600 text-white'
                  : 'bg-ink-700 text-ink-300 hover:bg-ink-600'
              "
              @click="onDelete(tag.id)"
            >
              {{ confirmDeleteId === tag.id ? '确认删除' : '删除' }}
            </button>
          </div>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="c in TAG_COLORS"
              :key="c.id"
              class="h-5 w-5 rounded-full border-2 transition"
              :class="tag.color === c.id ? 'scale-110' : 'opacity-60 hover:opacity-100'"
              :style="swatchStyle(c.id, tag.color === c.id)"
              :title="c.name"
              @click="tagsStore.recolor(tag.id, c.id)"
            />
          </div>
        </li>
        <li class="pt-1 text-[11px] text-ink-500">删除标签会把它从所有装备上移除。</li>
      </ul>
    </div>

    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="tagsStore.close()">
        关闭
      </button>
    </template>
  </Modal>
</template>
