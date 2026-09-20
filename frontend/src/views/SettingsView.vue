<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import data from '@shared/schema'
import Modal from '@/components/Modal.vue'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import { RARITY_ORDER, formatNumber, rarityName } from '@/utils/format'

const game = useGameStore()
const toast = useToastStore()

const enabled = ref(false)
const rarities = ref<string[]>([])
const saving = ref(false)
const confirmRestart = ref(false)

const redeemEnabled = ref(false)
const canRedeem = ref(false)
const rewardGold = ref(0)
const redeemCode = ref('')
const redeeming = ref(false)

const autoSellOptions = data.economy.sell.autoSellRarities

onMounted(async () => {
  if (!game.state) await game.loadState()
  const settings = game.state?.settings.autoSell
  enabled.value = settings?.enabled ?? false
  rarities.value = settings?.rarities ?? [...autoSellOptions]
  await loadRedeem()
})

async function loadRedeem() {
  try {
    const res = await api.redeemState()
    redeemEnabled.value = res.enabled
    canRedeem.value = res.canRedeem
    rewardGold.value = res.rewardGold
  } catch {
    redeemEnabled.value = false
  }
}

async function submitRedeem() {
  const code = redeemCode.value.trim()
  if (!code || redeeming.value) return
  redeeming.value = true
  try {
    const res = await api.redeem(code)
    toast.push(res.message, 'success')
    redeemCode.value = ''
    if (game.state) game.state.user.gold = res.gold
    await loadRedeem()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    redeeming.value = false
  }
}

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

    <section v-if="redeemEnabled" class="card p-4">
      <h3 class="text-sm font-semibold text-white">兑换码</h3>
      <p class="mt-1 text-[11px] text-ink-500">
        输入兑换码可领取金币，每个账号对同一兑换码只能兑换一次。
      </p>

      <template v-if="canRedeem">
        <div class="mt-3 flex flex-wrap gap-2">
          <input
            v-model="redeemCode"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
            placeholder="请输入兑换码"
            @keyup.enter="submitRedeem"
          />
          <button
            class="rounded-md bg-amber-500 px-4 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
            :disabled="redeeming || !redeemCode.trim()"
            @click="submitRedeem"
          >
            {{ redeeming ? '兑换中…' : `兑换 · ${formatNumber(rewardGold)} 金币` }}
          </button>
        </div>
      </template>
      <p v-else class="mt-3 text-xs text-emerald-300">你已经兑换过该兑换码了。</p>
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
