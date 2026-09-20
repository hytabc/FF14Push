import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastTone = 'info' | 'success' | 'error' | 'loot'

export interface Toast {
  id: number
  text: string
  tone: ToastTone
}

let seq = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<Toast[]>([])

  function push(text: string, tone: ToastTone = 'info', ttl = 3200) {
    const id = ++seq
    items.value.push({ id, text, tone })
    setTimeout(() => dismiss(id), ttl)
  }

  function dismiss(id: number) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  return { items, push, dismiss }
})
