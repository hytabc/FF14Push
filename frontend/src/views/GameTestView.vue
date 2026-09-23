<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 静态单文件小游戏，由 Vite 从 frontend/public/games 直接托管。 */
const GAME_SRC = '/games/ff14-test-game.html'

const stage = ref<HTMLElement | null>(null)
const fullscreen = ref(false)

function syncFullscreen() {
  fullscreen.value = document.fullscreenElement === stage.value
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await stage.value?.requestFullscreen()
  } catch {
    /* 浏览器拒绝全屏（如缺少用户手势）时静默忽略 */
  }
}

function openInNewTab() {
  window.open(GAME_SRC, '_blank', 'noopener,noreferrer')
}

onMounted(() => document.addEventListener('fullscreenchange', syncFullscreen))
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', syncFullscreen))
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">游戏测试</h2>
        <span class="text-xs text-ink-400">晓月残章 · 以太回溯 — 单文件 FF14 风格 Roguelike</span>
        <div class="ml-auto flex items-center gap-2 text-[11px]">
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="toggleFullscreen">
            {{ fullscreen ? '退出全屏' : '全屏' }}
          </button>
          <button class="rounded bg-ink-700 px-2 py-1.5 hover:bg-ink-600" @click="openInNewTab">
            新窗口打开
          </button>
        </div>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        选择一个职业开始以太回溯，走完「普通副本 → 极神讨伐 → 零式挑战 → 绝境战」航线。电脑端使用
        WASD / 方向键移动，1~4 释放技能；手机端使用左侧摇杆与右侧技能键。
      </p>
    </section>

    <div
      ref="stage"
      class="overflow-hidden rounded-xl border border-ink-700 bg-black"
      :class="fullscreen ? 'h-screen w-screen' : 'h-[70vh] min-h-[420px]'"
    >
      <iframe
        :src="GAME_SRC"
        title="晓月残章 · 以太回溯"
        class="h-full w-full border-0"
        allowfullscreen
      ></iframe>
    </div>
  </div>
</template>
