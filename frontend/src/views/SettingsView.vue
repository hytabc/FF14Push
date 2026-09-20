<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api'
import data from '@shared/schema'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { RARITY_ORDER, rarityName } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const enabled = ref(false)
const rarities = ref<string[]>([])
const saving = ref(false)
const confirmRestart = ref(false)

const autoSellOptions = data.economy.sell.autoSellRarities

onMounted(async () => {
  if (!game.state) await game.loadState()
  const settings = game.state?.settings.autoSell
  enabled.value = settings?.enabled ?? false
  rarities.value = settings?.rarities ?? [...autoSellOptions]
})

function toggleRarity(rarity: string) {
  rarities.value = rarities.value.includes(rarity)
    ? rarities.value.filter((r) => r !== rarity)
    : [...rarities.value, rarity]
}

async function save() {
  saving.value = true
  try {
    await api.setAutoSell(enabled.value, rarities.value)
    toast.push('设置已保存', 'success')
    await game.loadState()
  } catch {
    toast.push('保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function restartTutorial() {
  confirmRestart.value = false
  await api.tutorialRestart()
  toast.push('新手指引已从第一步重新开始', 'success')
  await game.loadState()
  window.location.reload()
}

async function replayFromSettings() {
  await api.tutorialRestart()
  await game.loadState()
  window.location.reload()
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <h2 class="text-lg font-semibold text-white">设置</h2>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">自动出售</h3>
      <p class="mt-1 text-[11px] text-ink-500">
        开启后，新获得的指定品阶装备会立即出售换取金币（合成与重造产物不受影响）。
      </p>

      <label class="mt-3 flex items-center gap-2 text-xs text-ink-200">
        <input v-model="enabled" type="checkbox" />
        开启自动出售
      </label>

      <div class="mt-3 flex flex-wrap gap-2">
        <button
          v-for="rarity in RARITY_ORDER"
          :key="rarity"
          class="rounded border px-2 py-1 text-[11px] transition"
          :class="
            rarities.includes(rarity)
              ? 'border-amber-400 bg-amber-400/15 text-amber-200'
              : 'border-ink-600 text-ink-400 hover:border-ink-400'
          "
          @click="toggleRarity(rarity)"
        >
          {{ rarityName(rarity) }}
        </button>
      </div>

      <button
        class="mt-4 rounded-md bg-amber-500 px-4 py-2 text-sm font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
        :disabled="saving"
        @click="save"
      >
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">新手指引</h3>
      <p class="mt-1 text-[11px] text-ink-500">
        重新开启后将回到第 1 步，需重新完成全部 15 步才能领取奖励。
      </p>
      <div class="mt-3 flex gap-2">
        <button
          class="rounded-md bg-ink-700 px-3 py-2 text-xs hover:bg-ink-600"
          @click="confirmRestart = true"
        >
          重新播放新手指引
        </button>
      </div>
    </section>

    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">游戏说明</h3>
      <ul class="mt-2 space-y-1 text-[11px] text-ink-400">
        <li>· 金币仅通过打怪掉落获得，出售装备为辅助来源。</li>
        <li>· 英雄离线不做收益结算：离开页面即暂停战斗（无离线挂机）。</li>
        <li>· 小怪阶段阵亡会重置该地区击杀计数，已获得的金币与经验保留。</li>
        <li>· 战斗结算由服务端校验，客户端只负责表现。</li>
        <li>· 重造 / 附魔是金币的主要回收途径。</li>
      </ul>
      <button class="mt-3 text-[11px] text-sky-300 underline" @click="replayFromSettings">重播指引（直接生效）</button>
    </section>

    <Modal :open="confirmRestart" title="重新播放新手指引？" @close="confirmRestart = false">
      <p class="text-sm text-ink-200">
        指引会从第 1 步重新开始，页面将刷新。已领取的奖励不会重复发放。
      </p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="confirmRestart = false">
          取消
        </button>
        <button class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950" @click="restartTutorial">
          确认重播
        </button>
      </template>
    </Modal>
  </div>
</template>
