<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { api } from '@/api'
import { toApiError } from '@/api/client'
import InfoTip from '@/components/InfoTip.vue'
import Modal from '@/components/Modal.vue'
import PlayerProfileDialog from '@/components/PlayerProfileDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useGameStore } from '@/stores/game'
import { useToastStore } from '@/stores/toast'
import type { FriendEntry, FriendsData } from '@/game/types'
import { formatNumber } from '@/utils/format'

const auth = useAuthStore()
const game = useGameStore()
const toast = useToastStore()

const data = ref<FriendsData | null>(null)
const loading = ref(false)
const busy = ref(false)

const addCode = ref('')
const profileId = ref<number | null>(null)

const transferTarget = ref<FriendEntry | null>(null)
const transferAmount = ref<number | null>(null)
const removeTarget = ref<FriendEntry | null>(null)

// 打开页面时轮询刷新在线状态
const REFRESH_MS = 20000
let pollTimer: number | undefined

const feePct = computed(() => data.value?.feePct ?? 0)
const amountValue = computed(() => Math.max(0, Math.floor(transferAmount.value ?? 0)))
const feeValue = computed(() => Math.floor(amountValue.value * feePct.value))
const netValue = computed(() => amountValue.value - feeValue.value)
const maxAffordable = computed(() => {
  if (!data.value) return 0
  return Math.min(game.gold, data.value.remainingToday, data.value.maxAmount)
})
const transferDisabled = computed(
  () =>
    busy.value ||
    !transferTarget.value ||
    amountValue.value < (data.value?.minAmount ?? 1) ||
    amountValue.value > maxAffordable.value,
)

function formatAgo(seconds: number): string {
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function lastSeenLabel(friend: FriendEntry): string {
  if (friend.online) return '在线'
  if (friend.lastSeenSecondsAgo == null) return '从未在线'
  return `最后在线 ${formatAgo(friend.lastSeenSecondsAgo)}`
}

async function load(quiet = false) {
  if (!quiet) loading.value = true
  try {
    data.value = await api.friends()
  } catch (e) {
    if (!quiet) toast.push(toApiError(e).message, 'error')
  } finally {
    loading.value = false
  }
}

async function act(fn: () => Promise<{ message?: string }>): Promise<boolean> {
  if (busy.value) return false
  busy.value = true
  try {
    const res = await fn()
    toast.push(res.message ?? '操作成功', 'success')
    await load(true)
    return true
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
    return false
  } finally {
    busy.value = false
  }
}

function copyCode() {
  const code = data.value?.friendCode ?? auth.friendCode
  if (!code) return
  if (!navigator.clipboard) {
    toast.push(`好友码：${code}`, 'info')
    return
  }
  void navigator.clipboard.writeText(code).then(
    () => toast.push('好友码已复制', 'success'),
    () => toast.push(`复制失败，请手动复制：${code}`, 'error'),
  )
}

async function submitAdd() {
  const code = addCode.value.trim().toUpperCase()
  if (!code) return
  if (await act(() => api.friendRequest(code))) addCode.value = ''
}

function openTransfer(friend: FriendEntry) {
  transferTarget.value = friend
  transferAmount.value = null
}

function closeTransfer() {
  transferTarget.value = null
  transferAmount.value = null
}

async function submitTransfer() {
  const target = transferTarget.value
  if (!target || transferDisabled.value) return
  busy.value = true
  try {
    const res = await api.friendTransfer(target.userId, amountValue.value)
    toast.push(
      `已向 ${res.recipientNickname} 转账 ${formatNumber(res.amount)} 金币，对方实收 ${formatNumber(res.net)}`,
      'success',
    )
    closeTransfer()
    await load(true)
    // 金币一律以服务端为准
    await game.loadState()
  } catch (e) {
    toast.push(toApiError(e).message, 'error')
  } finally {
    busy.value = false
  }
}

async function confirmRemove() {
  const target = removeTarget.value
  if (!target) return
  if (await act(() => api.friendRemove(target.userId))) removeTarget.value = null
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') void load(true)
  }, REFRESH_MS)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="space-y-4">
    <!-- 我的好友码 -->
    <section class="card p-4">
      <h2 class="text-lg font-semibold text-white">好友</h2>
      <p class="mt-1 text-[11px] text-ink-500">
        把自己的好友码发给朋友，或用对方的好友码添加好友。成为好友后可查看在线状态并互相转账。
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <span class="text-xs text-ink-400">我的好友码</span>
        <code class="rounded bg-ink-800 px-3 py-1.5 font-mono text-base tracking-widest text-amber-200">
          {{ data?.friendCode ?? auth.friendCode ?? '——' }}
        </code>
        <button
          class="rounded-md bg-ink-700 px-3 py-1.5 text-xs hover:bg-ink-600"
          @click="copyCode"
        >
          复制
        </button>
      </div>
      <p v-if="data" class="mt-2 text-[11px] text-ink-500">
        转账手续费 {{ (feePct * 100).toFixed(0) }}%
        <InfoTip title="转账手续费">
          <p>手续费 =⌊转账金额 × {{ (feePct * 100).toFixed(0) }}%⌋，从转账金额中扣除后销毁。</p>
          <p>例：转账 1,000 金币 → 手续费 {{ Math.floor(1000 * feePct) }}，对方实收 {{ 1000 - Math.floor(1000 * feePct) }}。</p>
          <p>单笔限额 {{ formatNumber(data.minAmount) }} ~ {{ formatNumber(data.maxAmount) }}；每日累计上限 {{ formatNumber(data.dailyLimit) }}（近 24 小时）。</p>
          <p>今日剩余额度：{{ formatNumber(data.remainingToday) }} 金币。</p>
        </InfoTip>
      </p>
    </section>

    <!-- 添加好友 -->
    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">添加好友</h3>
      <form class="mt-3 flex flex-wrap gap-2" @submit.prevent="submitAdd">
        <input
          v-model="addCode"
          class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 font-mono text-xs uppercase tracking-widest"
          maxlength="12"
          placeholder="输入好友码"
          :disabled="busy"
        />
        <button
          type="submit"
          class="rounded-md bg-amber-500 px-4 py-1.5 text-xs font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
          :disabled="busy || !addCode.trim()"
        >
          发送申请
        </button>
      </form>

      <!-- 收到的好友申请 -->
      <div v-if="data && data.incoming.length" class="mt-4">
        <p class="mb-2 text-xs font-medium text-ink-300">好友申请（{{ data.incoming.length }}）</p>
        <ul class="space-y-2">
          <li
            v-for="req in data.incoming"
            :key="req.userId"
            class="flex flex-wrap items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-xs"
          >
            <span class="text-ink-100">{{ req.nickname }}</span>
            <span class="text-ink-500">#{{ req.username }}</span>
            <span class="ml-auto flex gap-2">
              <button
                class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
                :disabled="busy"
                @click="act(() => api.friendAccept(req.userId))"
              >
                同意
              </button>
              <button
                class="rounded bg-ink-700 px-3 py-1 hover:bg-ink-600 disabled:opacity-50"
                :disabled="busy"
                @click="act(() => api.friendReject(req.userId))"
              >
                拒绝
              </button>
            </span>
          </li>
        </ul>
      </div>

      <!-- 已发送的申请 -->
      <div v-if="data && data.outgoing.length" class="mt-4">
        <p class="mb-2 text-xs font-medium text-ink-300">已发送的申请（{{ data.outgoing.length }}）</p>
        <ul class="space-y-2">
          <li
            v-for="req in data.outgoing"
            :key="req.userId"
            class="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-xs"
          >
            <span class="text-ink-100">{{ req.nickname }}</span>
            <span class="text-ink-500">#{{ req.username }}</span>
            <span class="ml-auto text-ink-500">等待对方同意</span>
            <button
              class="rounded bg-ink-700 px-3 py-1 hover:bg-ink-600 disabled:opacity-50"
              :disabled="busy"
              @click="removeTarget = req"
            >
              撤销
            </button>
          </li>
        </ul>
      </div>
    </section>

    <!-- 好友列表 -->
    <section class="card p-4">
      <h3 class="text-sm font-semibold text-white">好友列表</h3>
      <p v-if="loading" class="py-6 text-center text-xs text-ink-500">加载中…</p>
      <p v-else-if="!data || !data.friends.length" class="py-6 text-center text-xs text-ink-500">
        还没有好友，先添加一个吧。
      </p>
      <ul v-else class="mt-3 space-y-2">
        <li
          v-for="friend in data.friends"
          :key="friend.userId"
          class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-ink-700 bg-ink-800/50 px-3 py-2 text-xs"
        >
          <span class="flex items-center gap-2">
            <span
              class="h-2 w-2 shrink-0 rounded-full"
              :class="friend.online ? 'bg-green-500' : 'bg-ink-600'"
              :title="friend.online ? '在线' : '离线'"
            />
            <span class="text-ink-100">{{ friend.nickname }}</span>
            <span class="text-ink-500">#{{ friend.username }}</span>
          </span>
          <span class="text-ink-400">
            <template v-if="friend.level != null">Lv.{{ friend.level }} · </template>
            <span :class="friend.online ? 'text-green-400' : 'text-ink-500'">
              {{ lastSeenLabel(friend) }}
            </span>
          </span>
          <span class="ml-auto flex gap-2">
            <button
              class="rounded bg-amber-500 px-3 py-1 font-medium text-ink-950 hover:bg-amber-400"
              @click="openTransfer(friend)"
            >
              转账
            </button>
            <button class="rounded bg-ink-700 px-3 py-1 hover:bg-ink-600" @click="profileId = friend.userId">
              查看装备
            </button>
            <button class="rounded bg-ink-700 px-3 py-1 hover:bg-ink-600" @click="removeTarget = friend">
              删除
            </button>
          </span>
        </li>
      </ul>
    </section>

    <!-- 转账弹窗 -->
    <Modal :open="transferTarget !== null" title="金币转账" max-width="max-w-md" @close="closeTransfer">
      <div v-if="transferTarget" class="space-y-3 text-sm">
        <p class="text-xs text-ink-400">
          转给 <span class="text-ink-100">{{ transferTarget.nickname }}</span>
          <span class="text-ink-500">#{{ transferTarget.username }}</span>
        </p>

        <label class="block text-xs text-ink-200">
          转账金额
          <span class="text-ink-500">（{{ formatNumber(data?.minAmount ?? 1) }} ~ {{ formatNumber(data?.maxAmount ?? 0) }}）</span>
        </label>
        <div class="flex flex-wrap items-center gap-2">
          <input
            v-model.number="transferAmount"
            type="number"
            min="1"
            class="min-w-0 flex-1 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-xs"
            placeholder="输入金额"
          />
          <button class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600" @click="transferAmount = maxAffordable">
            全部
          </button>
          <button class="rounded bg-ink-700 px-2 py-1 text-[11px] hover:bg-ink-600" @click="transferAmount = Math.floor(maxAffordable / 2)">
            一半
          </button>
        </div>

        <div class="rounded-lg border border-ink-700 bg-ink-800/60 p-3 text-xs">
          <p class="flex flex-wrap items-center text-ink-300">
            手续费 {{ (feePct * 100).toFixed(0) }}%：
            <span class="ml-1 font-mono text-rose-300">{{ formatNumber(feeValue) }}</span>
            <InfoTip title="手续费计算">
              <p>手续费 =⌊转账金额 × {{ (feePct * 100).toFixed(0) }}%⌋ = ⌊{{ amountValue }} × {{ feePct }}⌋ = {{ feeValue }}。</p>
              <p>手续费从转账金额中扣除并销毁，对方实收 = {{ amountValue }} − {{ feeValue }} = {{ netValue }}。</p>
            </InfoTip>
          </p>
          <p class="mt-1 text-ink-300">
            对方实收：
            <span class="font-mono text-amber-300">{{ formatNumber(netValue) }}</span>
          </p>
          <p class="mt-1 text-ink-500">
            我持有 {{ formatNumber(game.gold) }} · 今日剩余额度 {{ formatNumber(data?.remainingToday ?? 0) }}
          </p>
        </div>
        <p v-if="transferAmount && amountValue > maxAffordable" class="text-[11px] text-rose-300">
          超出可转账额度（金币余额 / 今日剩余额度 / 单笔上限的最小值）。
        </p>
      </div>

      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="closeTransfer">
          取消
        </button>
        <button
          class="rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-ink-950 hover:bg-amber-400 disabled:opacity-50"
          :disabled="transferDisabled"
          @click="submitTransfer"
        >
          {{ busy ? '处理中…' : '确认转账' }}
        </button>
      </template>
    </Modal>

    <!-- 删除 / 撤销确认 -->
    <Modal
      :open="removeTarget !== null"
      :title="data && data.friends.some((f) => f.userId === removeTarget?.userId) ? '删除好友' : '撤销申请'"
      @close="removeTarget = null"
    >
      <p class="text-sm text-ink-200">
        <template v-if="data && data.friends.some((f) => f.userId === removeTarget?.userId)">
          确定删除好友 {{ removeTarget?.nickname }}？删除后将无法互相转账，需要重新添加。
        </template>
        <template v-else>
          确定撤销发给 {{ removeTarget?.nickname }} 的好友申请？
        </template>
      </p>
      <template #footer>
        <button class="rounded-md bg-ink-700 px-3 py-2 text-sm hover:bg-ink-600" @click="removeTarget = null">
          取消
        </button>
        <button
          class="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-500 disabled:opacity-50"
          :disabled="busy"
          @click="confirmRemove"
        >
          确定
        </button>
      </template>
    </Modal>

    <PlayerProfileDialog :user-id="profileId" @close="profileId = null" />
  </div>
</template>
