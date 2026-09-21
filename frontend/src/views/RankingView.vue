<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import PlayerProfileDialog from '@/components/PlayerProfileDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import type { RankingEntry } from '@/game/types'
import { formatNumber } from '@/utils/format'

const auth = useAuthStore()
const toast = useToastStore()

const TITLE_NAMES: Record<string, string> = Object.fromEntries(
  data.titles.titles.map((t) => [t.id, t.name]),
)

const BOARDS = [
  { id: 'level', label: '等级榜', hint: '同等级按经验降序' },
  { id: 'stage', label: '关卡榜', hint: '同关卡按通关时间升序（越早越靠前）' },
  { id: 'power', label: '战力榜', hint: '英雄总战力降序' },
  { id: 'gold', label: '金币榜', hint: '当前持有金币降序' },
  { id: 'fish_species', label: '钓鱼种类榜', hint: '钓到的鱼类种类数降序' },
  { id: 'fish_count', label: '钓鱼数量榜', hint: '累计钓鱼数量降序' },
]

const board = ref('level')
const page = ref(1)
const entries = ref<RankingEntry[]>([])
const me = ref<{ rank: number; value: number } | null>(null)
const loading = ref(false)

const current = computed(() => BOARDS.find((b) => b.id === board.value)!)

async function load() {
  loading.value = true
  try {
    const res = await api.ranking(board.value, page.value)
    entries.value = res.entries
    me.value = res.me
  } catch {
    toast.push('排行榜加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  try {
    await api.rankingRefresh()
    toast.push('排行榜已刷新', 'success')
    await load()
  } catch {
    toast.push('刷新失败，请稍后再试', 'error')
  }
}

onMounted(load)
watch([board, page], load)

function valueText(entry: RankingEntry): string {
  if (board.value === 'gold') return formatNumber(entry.value)
  if (board.value === 'stage') return entry.value > 0 ? `第 ${entry.value} 关` : '未通关'
  if (board.value === 'fish_species') return `${entry.value} 种`
  if (board.value === 'fish_count') return `${formatNumber(entry.value)} 条`
  return String(entry.value)
}

const profileId = ref<number | null>(null)

function entryTitles(entry: RankingEntry): string[] {
  const ids = entry.payload?.titles
  if (!Array.isArray(ids)) return []
  return ids.map((id) => TITLE_NAMES[String(id)] ?? String(id))
}

function openProfile(entry: RankingEntry) {
  if (!auth.isLoggedIn) {
    toast.push('登录后可查看他人装备', 'info')
    return
  }
  profileId.value = entry.userId
}
</script>

<template>
  <div class="space-y-4">
    <section class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">排行榜</h2>
        <span class="text-xs text-ink-400">{{ current.hint }}</span>
        <button class="ml-auto rounded bg-ink-700 px-2 py-1.5 text-[11px] hover:bg-ink-600" @click="refreshAll">
          手动刷新
        </button>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        服务端每 5 分钟自动刷新一次，展示前 100 名。点击任意玩家可查看其当前装备（需登录）。
        <span v-if="!auth.isLoggedIn" class="text-amber-300">未登录可查看榜单，但不会上榜。</span>
      </p>

      <div class="mt-3 flex gap-1 overflow-x-auto rounded-lg bg-ink-800 p-1 text-xs">
        <button
          v-for="b in BOARDS"
          :key="b.id"
          class="flex-1 shrink-0 rounded-md px-3 py-1.5 transition"
          :class="board === b.id ? 'bg-amber-500 text-ink-950' : 'text-ink-400 hover:text-ink-200'"
          @click="board = b.id; page = 1"
        >
          {{ b.label }}
        </button>
      </div>
    </section>

    <section class="card overflow-hidden">
      <table class="w-full text-xs">
        <thead class="bg-ink-800/80 text-ink-400">
          <tr>
            <th class="w-16 px-3 py-2 text-left">排名</th>
            <th class="px-3 py-2 text-left">玩家昵称</th>
            <th class="px-3 py-2 text-left">英雄等级</th>
            <th class="px-3 py-2 text-right">数值</th>
            <th class="w-14 px-3 py-2 text-right">装备</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="entry in entries"
            :key="entry.userId"
            class="cursor-pointer border-t border-ink-800 transition hover:bg-ink-800/60"
            title="查看该玩家当前装备"
            @click="openProfile(entry)"
          >
            <td class="px-3 py-2 font-mono" :class="entry.rank <= 3 ? 'text-amber-300' : 'text-ink-400'">
              {{ entry.rank }}
            </td>
            <td class="px-3 py-2 text-ink-100">
              {{ entry.nickname }}<span class="opacity-60">#{{ entry.username }}</span>
              <span
                v-for="t in entryTitles(entry)"
                :key="t"
                class="ml-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200"
              >{{ t }}</span>
            </td>
            <td class="px-3 py-2 text-ink-400">{{ entry.payload?.level ?? '—' }}</td>
            <td class="px-3 py-2 text-right font-mono text-ink-200">{{ valueText(entry) }}</td>
            <td class="px-3 py-2 text-right text-ink-400">查看</td>
          </tr>
          <tr v-if="!entries.length && !loading">
            <td colspan="5" class="px-3 py-10 text-center text-ink-600">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="me" class="card p-3 text-xs text-ink-300">
      我的排名：<b class="font-mono text-amber-300">第 {{ me.rank }} 名</b> · {{ valueText({ value: me.value } as RankingEntry) }}
    </div>

    <nav class="flex items-center justify-center gap-2 text-xs">
      <button class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40" :disabled="page <= 1" @click="page -= 1">
        上一页
      </button>
      <span class="text-ink-400">第 {{ page }} 页</span>
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="entries.length < 50"
        @click="page += 1"
      >
        下一页
      </button>
    </nav>

    <PlayerProfileDialog :user-id="profileId" @close="profileId = null" />
  </div>
</template>
