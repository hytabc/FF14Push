<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Modal from '@/components/Modal.vue'
import type { SequenceLoopMode } from '@/game/core/sequence'
import type { SavedSequence } from '@/game/types'
import { useDohDolStore } from '@/stores/dohdol'
import { MAX_SEQUENCES, useSequencesStore } from '@/stores/sequences'
import { useToastStore } from '@/stores/toast'

const dohdol = useDohDolStore()
const store = useSequencesStore()
const toast = useToastStore()

const name = ref('')
const importCode = ref('')
const confirmDeleteId = ref<number | null>(null)

const LOOP_LABEL: Record<SequenceLoopMode, string> = {
  once: '不循环',
  count: '循环 N 次',
  infinite: '一直循环',
}

watch(
  () => store.open,
  (open) => {
    if (!open) return
    name.value = ''
    importCode.value = ''
    confirmDeleteId.value = null
  },
)

const duplicate = computed(() => store.byName(name.value))
const saveLabel = computed(() => (duplicate.value ? '覆盖保存' : '保存'))
const saveBlocked = computed(
  () => !name.value.trim() || store.busy || !store.canSave || (store.full && !duplicate.value),
)

function loopLabel(slot: SavedSequence): string {
  if (slot.loopMode === 'count') return `循环 ${slot.loopTotal} 次`
  return LOOP_LABEL[slot.loopMode] ?? LOOP_LABEL.once
}

async function save() {
  const ok = await store.saveCurrent(name.value)
  if (ok) name.value = ''
}

function onDelete(id: number) {
  if (confirmDeleteId.value === id) {
    void store.remove(id)
    confirmDeleteId.value = null
  } else {
    confirmDeleteId.value = id
  }
}

function copyCode(code: string) {
  if (!navigator.clipboard) {
    toast.push(`蓝图ID：${code}`, 'info')
    return
  }
  void navigator.clipboard.writeText(code).then(
    () => toast.push('蓝图ID已复制', 'success'),
    () => toast.push(`复制失败，请手动复制：${code}`, 'error'),
  )
}

function doImport() {
  void store.importByCode(importCode.value).then((ok) => {
    if (ok) importCode.value = ''
  })
}
</script>

<template>
  <Modal :open="store.open" title="序列库" max-width="max-w-2xl" @close="store.close()">
    <div class="space-y-4 text-sm">
      <!-- 保存当前序列 -->
      <section class="rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <p class="mb-2 text-xs text-ink-400">
          保存当前编辑区的序列（{{ dohdol.sequence.length }} 步 · {{ LOOP_LABEL[dohdol.loopMode] }}）；
          已保存 {{ store.count }}/{{ MAX_SEQUENCES }} 组。
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <input
            v-model="name"
            maxlength="24"
            placeholder="序列名称（≤24 字）"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
            @keyup.enter="save"
          />
          <button
            class="rounded bg-teal-600 px-2.5 py-1.5 text-xs text-white hover:bg-teal-500 disabled:opacity-40"
            :disabled="saveBlocked"
            @click="save"
          >
            {{ saveLabel }}
          </button>
        </div>
        <p v-if="duplicate" class="mt-1 text-[11px] text-amber-300">
          已存在同名序列，保存将覆盖「{{ duplicate.name }}」（蓝图ID不变）。
        </p>
        <p v-else-if="store.full" class="mt-1 text-[11px] text-amber-300">
          已达上限 {{ MAX_SEQUENCES }} 组，请先删除或覆盖已有序列。
        </p>
        <p v-else-if="!store.canSave" class="mt-1 text-[11px] text-ink-500">
          当前编辑区为空，请先添加步骤。
        </p>
      </section>

      <!-- 我的序列 -->
      <section>
        <p class="mb-2 text-xs font-semibold text-ink-300">我的序列</p>
        <p v-if="store.loading" class="py-3 text-center text-xs text-ink-500">加载中…</p>
        <p v-else-if="!store.list.length" class="py-3 text-center text-xs text-ink-500">
          还没有保存的序列。
        </p>
        <ul v-else class="space-y-2">
          <li
            v-for="slot in store.list"
            :key="slot.id"
            class="rounded-lg border border-ink-700 bg-ink-800/60 p-2.5"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span class="truncate text-ink-100">{{ slot.name }}</span>
              <span class="text-[10px] text-ink-500">
                共 {{ slot.stepCount }} 步 · {{ loopLabel(slot) }}
              </span>
              <span class="ml-auto flex items-center gap-1">
                <button
                  class="rounded bg-ink-700 px-2 py-1 text-[11px] text-ink-200 hover:bg-ink-600 disabled:opacity-30"
                  :disabled="store.busy || dohdol.seqActive"
                  title="读取到当前编辑区"
                  @click="store.readSlot(slot)"
                >
                  读取
                </button>
                <button
                  class="rounded bg-ink-700 px-2 py-1 text-[11px] text-ink-200 hover:bg-ink-600 disabled:opacity-30"
                  :disabled="store.busy || dohdol.seqActive || !store.canSave"
                  title="用当前编辑区覆盖该序列"
                  @click="store.overwriteSlot(slot)"
                >
                  覆盖
                </button>
                <button
                  class="rounded px-2 py-1 text-[11px]"
                  :class="
                    confirmDeleteId === slot.id
                      ? 'bg-rose-600 text-white'
                      : 'bg-ink-700 text-rose-300 hover:bg-ink-600'
                  "
                  :disabled="store.busy"
                  @click="onDelete(slot.id)"
                >
                  {{ confirmDeleteId === slot.id ? '确认删除' : '删除' }}
                </button>
              </span>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-2">
              <span class="text-[10px] text-ink-500">蓝图ID</span>
              <code class="rounded bg-ink-900 px-2 py-0.5 font-mono text-xs tracking-widest text-amber-200">
                {{ slot.shareCode }}
              </code>
              <button
                class="rounded bg-ink-700 px-2 py-0.5 text-[10px] text-ink-200 hover:bg-ink-600"
                @click="copyCode(slot.shareCode)"
              >
                复制
              </button>
            </div>
          </li>
        </ul>
        <p v-if="store.list.length" class="mt-1 text-[11px] text-ink-500">
          把蓝图ID发给其他玩家，对方在下方导入即可使用（删除序列后该蓝图ID失效）。
        </p>
      </section>

      <!-- 导入蓝图 -->
      <section class="rounded-lg border border-ink-700 bg-ink-800/70 p-3">
        <p class="mb-2 text-xs text-ink-400">
          输入蓝图ID导入其他玩家的序列到当前编辑区（会替换编辑区，不占用你的序列槽位）。
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <input
            v-model="importCode"
            maxlength="12"
            placeholder="蓝图ID（8 位）"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 font-mono text-xs uppercase tracking-widest"
            @keyup.enter="doImport"
          />
          <button
            class="rounded bg-amber-500/20 px-2.5 py-1.5 text-xs text-amber-100 hover:bg-amber-500/30 disabled:opacity-40"
            :disabled="!importCode.trim() || store.busy || dohdol.seqActive"
            @click="doImport"
          >
            导入
          </button>
        </div>
      </section>
    </div>

    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="store.close()">
        关闭
      </button>
    </template>
  </Modal>
</template>
