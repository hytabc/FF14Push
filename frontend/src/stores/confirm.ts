import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ConfirmTone = 'default' | 'danger'

export interface ConfirmOptions {
  title: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  /** danger：确认按钮为红色（用于出售 / 删除等不可逆操作）。 */
  tone?: ConfirmTone
}

/**
 * 通用确认弹窗：`await confirm.ask({...})` 返回玩家是否确认。
 * 由全局挂载的 `ConfirmDialog.vue` 渲染，用于出售等不可逆操作的「二次确认」。
 */
export const useConfirmStore = defineStore('confirm', () => {
  const open = ref(false)
  const title = ref('')
  const message = ref('')
  const confirmLabel = ref('确认')
  const cancelLabel = ref('取消')
  const tone = ref<ConfirmTone>('default')

  let resolver: ((ok: boolean) => void) | null = null

  function ask(opts: ConfirmOptions): Promise<boolean> {
    // 理论上不会并发；若上一个确认尚未作答，先按「取消」结算，避免 Promise 悬挂。
    resolver?.(false)
    title.value = opts.title
    message.value = opts.message ?? ''
    confirmLabel.value = opts.confirmLabel ?? '确认'
    cancelLabel.value = opts.cancelLabel ?? '取消'
    tone.value = opts.tone ?? 'default'
    open.value = true
    return new Promise<boolean>((resolve) => {
      resolver = resolve
    })
  }

  function settle(ok: boolean) {
    open.value = false
    const done = resolver
    resolver = null
    done?.(ok)
  }

  const accept = () => settle(true)
  const cancel = () => settle(false)

  return { open, title, message, confirmLabel, cancelLabel, tone, ask, accept, cancel }
})
