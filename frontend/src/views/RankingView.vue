<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import data from '@shared/schema'

import { api } from '@/api'
import CoopRecordDialog from '@/components/CoopRecordDialog.vue'
import PlayerProfileDialog from '@/components/PlayerProfileDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { modes, roles, type CoopClearPayload, type CoopPartyMember } from '@/game/multiplayer'
import type { RankingEntry } from '@/game/types'
import { formatDuration, formatNumber, formatPlaytime, jobName } from '@/utils/format'

const auth = useAuthStore()
const toast = useToastStore()

const TITLE_NAMES: Record<string, string> = Object.fromEntries(
  data.titles.titles.map((t) => [t.id, t.name]),
)

const BOARDS = [
  { id: 'level', label: '等级榜', hint: '同等级按经验降序' },
  { id: 'stage', label: '关卡榜', hint: '难度优先；同难度按关卡降序，同关卡按通关时间升序（越早越靠前）' },
  { id: 'power', label: '战力榜', hint: '英雄总战力降序' },
  { id: 'gold', label: '金币榜', hint: '当前持有金币降序' },
  { id: 'playtime', label: '游玩时间榜', hint: '累计在线时长降序' },
  { id: 'fish_species', label: '钓鱼种类榜', hint: '钓到的鱼类种类数降序' },
  { id: 'fish_count', label: '钓鱼数量榜', hint: '累计钓鱼数量降序' },
  { id: 'doh_exp', label: '生产经验榜', hint: '累计生产经验降序（满级后仍继续累计）' },
  { id: 'dol_exp', label: '采集经验榜', hint: '累计采集经验降序（含钓鱼，满级后仍继续累计）' },
  { id: 'dohdol_attr', label: '生产 / 采集属性榜', hint: '已装备生产 / 采集专用装备属性总值降序（左：生产，右：采集）' },
  { id: 'coop', label: '远征榜', hint: '同副本按通关时长升序（越小越快）' },
]

const DOHDOL_BOARDS = ['doh_exp', 'dol_exp', 'doh_attr', 'dol_attr']

/** 生产 / 采集属性榜：前端把两个实时榜并排成一个对比榜（左生产、右采集）。 */
const COMPARE_BOARD = 'dohdol_attr'
const COMPARE_PARTS = [
  { board: 'doh_attr', label: '生产属性榜' },
  { board: 'dol_attr', label: '采集属性榜' },
] as const

interface RankingPane {
  board: string
  label: string
  entries: RankingEntry[]
  me: { rank: number; value: number } | null
}

const board = ref('level')
const page = ref(1)
const panes = ref<RankingPane[]>([])
const loading = ref(false)
const dungeons = ref<{ id: string; name: string; difficulty: string }[]>([])
const dungeon = ref('')

const current = computed(() => BOARDS.find((b) => b.id === board.value)!)

async function load() {
  loading.value = true
  try {
    if (board.value === COMPARE_BOARD) {
      const results = await Promise.all(COMPARE_PARTS.map((part) => api.ranking(part.board, page.value)))
      panes.value = COMPARE_PARTS.map((part, index) => ({
        board: part.board,
        label: part.label,
        entries: results[index].entries,
        me: results[index].me,
      }))
    } else {
      const res = await api.ranking(board.value, page.value, board.value === 'coop' ? dungeon.value : undefined)
      panes.value = [{ board: board.value, label: current.value.label, entries: res.entries, me: res.me }]
      if (res.dungeons) {
        dungeons.value = res.dungeons
        if (!dungeon.value && res.dungeon) dungeon.value = res.dungeon
      }
    }
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

/** 关卡榜 value = 难度 × 基数 + 地区（与后端 `ranking.STAGE_REGION_BASE` 一致）。 */
const STAGE_REGION_BASE = 1000

function valueText(boardId: string, entry: RankingEntry): string {
  if (boardId === 'gold') return formatNumber(entry.value)
  if (boardId === 'stage') {
    if (entry.value <= 0) return '未通关'
    const difficulty = Math.floor(entry.value / STAGE_REGION_BASE)
    const region = entry.value % STAGE_REGION_BASE
    return `难度 ${difficulty} · 第 ${region} 关`
  }
  if (boardId === 'playtime') return formatPlaytime(entry.value)
  if (boardId === 'fish_species') return `${entry.value} 种`
  if (boardId === 'fish_count') return `${formatNumber(entry.value)} 条`
  if (boardId === 'doh_exp' || boardId === 'dol_exp') return `${formatNumber(entry.value)} 经验`
  if (boardId === 'doh_attr' || boardId === 'dol_attr') return `${formatNumber(entry.value)} 属性`
  if (boardId === 'coop') return formatDuration(entry.value)
  return String(entry.value)
}

/** 我的排名：对比榜会给出两组（生产 / 采集各一条）。 */
const myRanks = computed(() =>
  panes.value
    .filter((pane) => pane.me)
    .map((pane) => ({
      board: pane.board,
      label: pane.label,
      rank: pane.me!.rank,
      text: valueText(pane.board, { value: pane.me!.value } as RankingEntry),
    })),
)

/** 每行都展示的累计在线时长（所有榜单通用，来自 payload）。 */
function playtimeText(entry: RankingEntry): string {
  return formatPlaytime(Number(entry.payload?.playSeconds ?? 0))
}

const profileId = ref<number | null>(null)
const record = ref<CoopClearPayload | null>(null)

function entryTitles(entry: RankingEntry): string[] {
  const ids = entry.payload?.titles
  if (!Array.isArray(ids)) return []
  return ids.map((id) => TITLE_NAMES[String(id)] ?? String(id))
}

const FISH_REGION_TOTAL = data.fish.regions.length

/** 钓鱼种类榜：按「普通 / 鱼王 / 鱼皇」拆分的种类数（后端实时聚合）。 */
function fishBreakdown(entry: RankingEntry): { normal: number; king: number; emperor: number } {
  return {
    normal: Number(entry.payload?.fishNormal ?? 0),
    king: Number(entry.payload?.fishKing ?? 0),
    emperor: Number(entry.payload?.fishEmperor ?? 0),
  }
}

/** 生产/采集榜：行内展示生产 / 采集等级（来自 payload）。 */
function dohdolLevels(entry: RankingEntry): { doh: number; dol: number } {
  return {
    doh: Number(entry.payload?.dohLevel ?? 1),
    dol: Number(entry.payload?.dolLevel ?? 1),
  }
}

function openProfile(entry: RankingEntry, boardId: string) {
  if (boardId === 'coop') {
    record.value = entry.payload as unknown as CoopClearPayload
    return
  }
  if (!auth.isLoggedIn) {
    toast.push('登录后可查看他人装备', 'info')
    return
  }
  profileId.value = entry.userId
}

/** 远征榜：该行的通关阵容（服务端权威数据）。 */
function partyOf(entry: RankingEntry): CoopPartyMember[] {
  const party = (entry.payload as unknown as CoopClearPayload)?.party
  return Array.isArray(party) ? party : []
}

const ROLE_DOT: Record<string, string> = {
  tank: 'bg-sky-400',
  healer: 'bg-emerald-400',
  dps: 'bg-rose-400',
}

function roleDot(role: string): string {
  return ROLE_DOT[role] ?? 'bg-ink-500'
}

function modeLabel(entry: RankingEntry): string {
  const mode = (entry.payload as unknown as CoopClearPayload)?.mode
  return mode ? modes[mode] ?? String(mode) : '—'
}

function hadClone(entry: RankingEntry): boolean {
  return Boolean((entry.payload as unknown as CoopClearPayload)?.hadClone)
}

function dungeonName(id?: string): string {
  return dungeons.value.find((d) => d.id === id)?.name ?? id ?? ''
}

function pickDungeon(id: string) {
  dungeon.value = id
  page.value = 1
  load()
}
</script>

<template>
  <div class="space-y-4">
    <section data-tutorial="ranking" class="card p-4">
      <div class="flex flex-wrap items-center gap-3">
        <h2 class="text-lg font-semibold text-white">排行榜</h2>
        <span class="text-xs text-ink-400">{{ current.hint }}</span>
        <button class="ml-auto rounded bg-ink-700 px-2 py-1.5 text-[11px] hover:bg-ink-600" @click="refreshAll">
          手动刷新
        </button>
      </div>
      <p class="mt-1 text-[11px] text-ink-500">
        <template v-if="board === 'coop'">
          按副本统计各玩家最快通关时长（越小越快），刚通关即可见。点击任意记录可查看该次通关的阵容与分角色输出。
        </template>
        <template v-else>
          服务端每 5 分钟自动刷新一次，展示前 100 名。点击任意玩家可查看其当前装备（需登录）。
        </template>
        <span v-if="!auth.isLoggedIn" class="text-amber-300">未登录可查看榜单，但不会上榜。</span>
      </p>

      <!-- 移动端：下拉切换榜单（11 个榜在手机上放不下，下拉更省空间） -->
      <select
        v-model="board"
        aria-label="选择排行榜"
        class="mt-3 w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2.5 text-base text-ink-100 outline-none focus:border-amber-400 md:hidden"
        @change="page = 1"
      >
        <option v-for="b in BOARDS" :key="b.id" :value="b.id">{{ b.label }}</option>
      </select>

      <!-- 桌面端：页签切换 -->
      <div class="mt-3 hidden gap-1 overflow-x-auto rounded-lg bg-ink-800 p-1 text-xs md:flex">
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

      <!-- 远征榜：按副本筛选 -->
      <div v-if="board === 'coop'" class="mt-3 flex flex-wrap items-center gap-2">
        <label class="text-xs text-ink-400">副本</label>
        <select
          :value="dungeon"
          aria-label="选择副本"
          class="rounded-lg border border-ink-600 bg-ink-900 px-3 py-1.5 text-sm text-ink-100 outline-none focus:border-amber-400"
          @change="pickDungeon(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="d in dungeons" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </div>
    </section>

    <section class="grid gap-3" :class="panes.length > 1 ? 'md:grid-cols-2' : ''">
      <div v-for="pane in panes" :key="pane.board" class="card overflow-x-auto">
        <p
          v-if="panes.length > 1"
          class="border-b border-ink-800 px-3 py-2 text-xs font-medium text-ink-200"
        >
          {{ pane.label }}
        </p>
        <table class="w-full text-xs">
          <thead class="bg-ink-800/80 text-ink-400">
            <tr>
              <th class="w-12 px-3 py-2 text-left sm:w-16">排名</th>
              <th class="px-3 py-2 text-left">玩家昵称</th>
              <th class="hidden px-3 py-2 text-left sm:table-cell">英雄等级</th>
              <th class="px-3 py-2 text-right">数值</th>
              <th class="hidden whitespace-nowrap px-3 py-2 text-right sm:table-cell">游玩时间</th>
              <th class="hidden w-14 px-3 py-2 text-right sm:table-cell">装备</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="entry in pane.entries"
              :key="entry.userId"
              class="cursor-pointer border-t border-ink-800 transition hover:bg-ink-800/60"
              :title="pane.board === 'coop' ? '查看该次通关阵容与输出' : '查看该玩家当前装备'"
              @click="openProfile(entry, pane.board)"
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
                <!-- 远征榜：行内展示该次通关的阵容 -->
                <div v-if="pane.board === 'coop' && partyOf(entry).length" class="mt-1 flex flex-wrap gap-1">
                  <span
                    v-for="m in partyOf(entry)"
                    :key="m.slot"
                    class="inline-flex items-center gap-1 rounded bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-300"
                    :title="`${roles[m.role]} · Lv.${m.level}`"
                  >
                    <span class="inline-block h-1.5 w-1.5 rounded-full" :class="roleDot(m.role)" />
                    {{ jobName(m.jobId) }}
                  </span>
                </div>
              </td>
              <td class="hidden px-3 py-2 text-ink-400 sm:table-cell">{{ entry.payload?.level ?? '—' }}</td>
              <td class="px-3 py-2 text-right">
                <div class="font-mono text-ink-200">{{ valueText(pane.board, entry) }}</div>
                <div v-if="pane.board === 'coop'" class="mt-0.5 text-[10px] text-ink-500">
                  {{ modeLabel(entry) }}<span v-if="hadClone(entry)"> · 含克隆</span>
                </div>
                <div v-if="pane.board === 'fish_species'" class="mt-0.5 text-[10px] text-ink-500">
                  普通 {{ fishBreakdown(entry).normal }} ·
                  鱼王 {{ fishBreakdown(entry).king }}/{{ FISH_REGION_TOTAL }} ·
                  鱼皇 {{ fishBreakdown(entry).emperor }}/{{ FISH_REGION_TOTAL }}
                </div>
                <div v-if="DOHDOL_BOARDS.includes(pane.board)" class="mt-0.5 text-[10px] text-ink-500">
                  生产 Lv.{{ dohdolLevels(entry).doh }} · 采集 Lv.{{ dohdolLevels(entry).dol }}
                </div>
              </td>
              <td class="hidden whitespace-nowrap px-3 py-2 text-right text-ink-400 sm:table-cell">{{ playtimeText(entry) }}</td>
              <td class="hidden px-3 py-2 text-right text-ink-400 sm:table-cell">{{ pane.board === 'coop' ? '阵容' : '查看' }}</td>
            </tr>
            <tr v-if="!pane.entries.length && !loading">
              <td colspan="6" class="px-3 py-10 text-center text-ink-600">暂无数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="myRanks.length" class="card p-3 text-xs text-ink-300">
      <p v-for="pane in myRanks" :key="pane.board">
        我的排名<span v-if="panes.length > 1" class="text-ink-500">（{{ pane.label }}）</span>：<b class="font-mono text-amber-300">第 {{ pane.rank }} 名</b> · {{ pane.text }}
      </p>
    </div>

    <nav class="flex items-center justify-center gap-2 text-xs">
      <button class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40" :disabled="page <= 1" @click="page -= 1">
        上一页
      </button>
      <span class="text-ink-400">第 {{ page }} 页</span>
      <button
        class="rounded bg-ink-700 px-3 py-1.5 disabled:opacity-40"
        :disabled="!panes.some((p) => p.entries.length >= 50)"
        @click="page += 1"
      >
        下一页
      </button>
    </nav>

    <PlayerProfileDialog :user-id="profileId" @close="profileId = null" />
    <CoopRecordDialog
      :open="record !== null"
      :dungeon-name="dungeonName(record?.dungeonId)"
      :clear-ms="record?.clearMs"
      :mode="record?.mode"
      :had-clone="record?.hadClone"
      :created-at="record?.createdAt"
      :party="record?.party ?? []"
      @close="record = null"
    />
  </div>
</template>
