<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { TutorialState } from '@/game/types'

const game = useGameStore()
const toast = useToastStore()
const route = useRoute()

const tutorial = ref<TutorialState | null>(null)
const confirmSkip = ref(false)
const busy = ref(false)

/** 每步对应的页面路由，用于自动导航。 */
const STEP_ROUTE: Record<string, string> = {
  welcome: '/',
  recruitHero: '/tavern',
  viewHero: '/hero',
  enterRegion: '/region',
  watchBattle: '/',
  deathReset: '/',
  defeatBoss: '/',
  openChestEquip: '/equipment',
  drawChest: '/chest',
  craft: '/craft',
  sell: '/inventory',
  refine: '/inventory',
  enchant: '/inventory',
  regionAdvance: '/region',
  rankingOffline: '/ranking',
}

const visible = computed(() => {
  const t = tutorial.value
  if (!t) return false
  return !t.completed && !t.skipped
})

const current = computed(() => tutorial.value?.steps.find((s) => s.step === tutorial.value?.currentStep) ?? null)

const isLast = computed(() => (tutorial.value?.currentStep ?? 1) >= (tutorial.value?.totalSteps ?? 15))

async function load() {
  try {
    tutorial.value = await api.tutorial()
  } catch {
    tutorial.value = null
  }
}

async function next() {
  if (!tutorial.value || busy.value) return
  busy.value = true
  try {
    if (isLast.value) {
      const res = await api.tutorialComplete()
      tutorial.value = { ...tutorial.value, ...res }
      if (res.granted) {
        toast.push(`新手指引完成！获得 ${res.goldGained} 金币与 3 个宝箱`, 'success')
      }
      await game.loadState()
    } else {
      const step = tutorial.value.currentStep + 1
      const res = await api.tutorialStep(step)
      tutorial.value = { ...tutorial.value, ...res }
      await game.loadState()
      const nextStep = res.steps.find((s) => s.step === res.currentStep)
      const target = nextStep ? STEP_ROUTE[nextStep.key] : undefined
      if (target && target !== route.path) {
        // 指引步骤会切到对应页面
        window.location.assign(`#${target}`)
      }
    }
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function doSkip() {
  confirmSkip.value = false
  const res = await api.tutorialSkip()
  tutorial.value = { ...tutorial.value!, ...res }
  toast.push(res.message, 'info')
}

onMounted(load)
watch(() => game.state?.tutorial, (v) => {
  if (v && tutorial.value) {
    tutorial.value = { ...tutorial.value, currentStep: v.currentStep, completed: v.completed, skipped: v.skipped }
  }
})

defineExpose({ load })
</script>

<template>
  <Modal v-if="visible && current" :open="visible" :title="`新手指引 ${current.step}/15 · ${current.title}`">
    <p class="text-sm leading-relaxed text-ink-200">{{ current.text }}</p>
    <p class="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      需要操作：{{ current.action }}
    </p>
    <div class="mt-4 flex items-center justify-between text-xs text-ink-400">
      <span>完成全部 15 步可领取 500 金币与 3 个普通宝箱</span>
      <button class="underline transition hover:text-white" @click="confirmSkip = true">跳过指引</button>
    </div>

    <template #footer>
      <button
        class="rounded-md bg-amber-500 px-4 py-2 text-sm font-medium text-ink-950 transition hover:bg-amber-400 disabled:opacity-50"
        :disabled="busy"
        @click="next"
      >
        {{ isLast ? '完成指引并领取奖励' : '已完成，下一步' }}
      </button>
    </template>
  </Modal>

  <Modal :open="confirmSkip" title="确认跳过新手指引？" @close="confirmSkip = false">
    <p class="text-sm text-ink-200">
      跳过后续所有步骤后，将<b class="text-rose-300">无法获得</b>指引完成奖励。之后可在「设置 → 新手指引」中重新开启。
    </p>
    <template #footer>
      <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmSkip = false">
        继续指引
      </button>
      <button class="rounded-md bg-rose-600 px-3 py-2 text-sm text-white hover:bg-rose-500" @click="doSkip">
        确认跳过
      </button>
    </template>
  </Modal>
</template>
