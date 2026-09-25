<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api'
import PlayerProfileDialog from '@/components/PlayerProfileDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { formatNumber } from '@/utils/format'

interface GrantRecord {
  id: number
  userId: number
  nickname: string
  amount: number
  note: string
  createdAt: string | null
}

const auth = useAuthStore()
const toast = useToastStore()

const PAGE_SIZE = 50
const records = ref<GrantRecord[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

const hasNext = computed(() => page.value * PAGE_SIZE < total.value)

const profileId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await api.compensationRecords(page.value)
    records.value = res.records
    total.value = res.total
  } catch {
    toast.push('补偿公示加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const time = new Date(iso)
  return Number.isNaN(time.getTime()) ? '—' : time.toLocaleString()
}

function openProfile(record: GrantRecord) {
  if (!auth.isLoggedIn) {
    toast.push('登录后可查看玩家资料', 'info')
    return
  }
  profileId.value = record.userId
}

onMounted(load)
watch(page, load)
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">补偿公示</h2>
        <span class="text-xs text-ink-400">共 {{ total }} 条</span>
        <button class="ml-auto rounded bg-ink-700 px-2 py-1.5 text-[11px] hover:bg-ink-600" @click="load">
          刷新
        </button>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        管理员为玩家发放的金币补偿记录，全服可见（含发放事由）。点击玩家昵称可查看其当前装备。
      </p>
    </section>

    <section class="card overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-ink-800/80 text-ink-400">
          <tr>
            <th class="whitespace-nowrap px-3 py-2 text-left">时间</th>
            <th class="px-3 py-2 text-left">玩家</th>
            <th class="px-3 py-2 text-right">金币</th>
            <th class="px-3 py-2 text-left">事由</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in records" :key="record.id" class="border-t border-ink-800">
            <td class="whitespace-nowrap px-3 py-2 text-ink-400">{{ formatTime(record.createdAt) }}</td>
            <td class="px-3 py-2">
              <button class="text-ink-100 transition hover:text-amber-200" @click="openProfile(record)">
                {{ record.nickname }}
              </button>
            </td>
            <td class="px-3 py-2 text-right font-mono text-amber-200">+{{ formatNumber(record.amount) }}</td>
            <td class="px-3 py-2 text-ink-300">{{ record.note || '—' }}</td>
          </tr>
          <tr v-if="!records.length && !loading">
            <td colspan="4" class="px-3 py-10 text-center text-ink-400">暂无补偿记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <nav class="flex items-center justify-center gap-2 text-xs">
      <button class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40" :disabled="page <= 1" @click="page -= 1">
        上一页
      </button>
      <span class="text-ink-400">第 {{ page }} 页</span>
      <button class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40" :disabled="!hasNext" @click="page += 1">
        下一页
      </button>
    </nav>

    <PlayerProfileDialog :user-id="profileId" @close="profileId = null" />
  </div>
</template>
