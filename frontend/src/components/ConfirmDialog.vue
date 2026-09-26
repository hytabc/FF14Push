<script setup lang="ts">
import Modal from '@/components/Modal.vue'
import { useConfirmStore } from '@/stores/confirm'

/** 全局通用确认弹窗（出售 / 删除等不可逆操作的二次确认）。 */
const confirm = useConfirmStore()
</script>

<template>
  <Modal :open="confirm.open" :title="confirm.title" @close="confirm.cancel()">
    <p v-if="confirm.message" class="whitespace-pre-line text-sm text-ink-200">{{ confirm.message }}</p>
    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirm.cancel()">
        {{ confirm.cancelLabel }}
      </button>
      <button
        class="rounded-md px-3 py-2 text-sm font-medium text-white"
        :class="confirm.tone === 'danger' ? 'bg-rose-600 hover:bg-rose-500' : 'bg-amber-600 hover:bg-amber-500'"
        @click="confirm.accept()"
      >
        {{ confirm.confirmLabel }}
      </button>
    </template>
  </Modal>
</template>
