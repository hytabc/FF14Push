<script setup lang="ts">
import { requestKey } from '@/utils/requestKey'
import JobIcon from '@/components/JobIcon.vue'
import HealthBar from '@/components/HealthBar.vue'
import { jobName } from '@/utils/format'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { http, toApiError } from '@/api/client'
import { useGameStore } from '@/stores/game'
import type { Registration, Roster, Snapshot } from '@/game/multiplayer'
import { roles } from '@/game/multiplayer'
interface Report { fighters: Snapshot[]; winner: number | null; result: string; durationMs: number; events: { at: number; actor: number; skill: string; damage: number; hp: number[]; shield: number[] }[] }
const game = useGameStore(), roster = ref<Roster | null>(null), registrations = ref<Registration[]>([])
const heroId = ref<number>(), busy = ref(false), error = ref(''), report = ref<Report | null>(null), cursor = ref(0), playing = ref(false)
const history = ref<{ id: number; attackerId: number; defenderId: number; result: string }[]>([])
const uid = computed(() => game.state?.user.id ?? 0), frame = computed(() => report.value?.events[cursor.value])
let timer: ReturnType<typeof setInterval> | undefined
async function load() {
  await game.loadState()
  const [h, r, b] = await Promise.all([http.get<Roster>('/heroes'), http.get<{ registrations: Registration[] }>('/registrations?kind=pvp'), http.get<{ battles: typeof history.value }>('/pvp')])
  roster.value = h.data; heroId.value ??= h.data.activeHeroId ?? undefined; registrations.value = r.data.registrations; history.value = b.data.battles
}
async function act(fn: () => Promise<unknown>) { busy.value = true; error.value = ''; try { await fn() } catch (e) { error.value = toApiError(e).message } finally { busy.value = false } }
async function challenge(id: number) { await act(async () => { await game.stopBattle(true); await game.stopRaid(true); report.value = (await http.post<{ report: Report }>('/pvp/challenge', { heroId: heroId.value, registrationId: id, key: requestKey() })).data.report; cursor.value = 0; playing.value = true; await load() }) }
async function replay(id: number) { await act(async () => { report.value = (await http.get<{ report: Report }>(`/pvp/${id}`)).data.report; cursor.value = 0; playing.value = false }) }
onMounted(() => { void act(load); timer = setInterval(() => { if (playing.value && report.value) { if (cursor.value < report.value.events.length - 1) cursor.value++; else playing.value = false } }, 150) })
onUnmounted(() => clearInterval(timer))
</script>
<template>
  <main class="dlc"><header><p class="eyebrow">八英雄远征 · 异步竞技场</p><h1>留下一位对手，迎接下一次挑战</h1><p>登记英雄与装备快照供其他玩家挑战。全自动1对1，180秒平局，无复活，无金币装备奖励。</p></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <section class="panel"><h2>我的挑战英雄</h2><select v-model="heroId" aria-label="竞技场英雄"><option v-for="h in roster?.heroes" :key="h.id" :value="h.id">{{ h.name }} Lv.{{ h.level }} · {{ jobName(h.jobId) }}</option></select><button :disabled="busy || !heroId" @click="act(async () => { await http.post('/registrations', { heroId, kind: 'pvp' }); await load() })">登记 / 更新防守快照</button><div v-for="r in registrations.filter(r => r.userId === uid)" :key="r.id" class="row"><p><JobIcon :job-id="r.snapshot.jobId" :size="20" /> {{ r.snapshot.name }} · Lv.{{ r.snapshot.level }} · 已登记防守</p><button :disabled="busy" @click="act(async () => { await http.delete(`/registrations/${r.id}`); await load() })">撤回</button></div></section>
    <section v-if="report" class="panel"><h2>战报回放 · {{ report.result === 'draw' ? '平局' : report.fighters[report.winner!]?.name + ' 获胜' }}</h2><p>战斗时长 {{ (report.durationMs / 1000).toFixed(1) }}秒</p><div class="cards"><div v-for="(f,i) in report.fighters" :key="i"><h3><JobIcon :job-id="f.jobId" :size="20" /> {{ f.name }} · {{ roles[f.role] }}</h3><HealthBar :value="frame?.hp[i] ?? f.stats.max_hp" :max="f.stats.max_hp" :shield="frame?.shield?.[i] ?? 0" height="h-2.5" fill-class="bg-emerald-500"/><small>{{ frame?.hp[i] ?? Math.round(f.stats.max_hp) }} HP</small></div></div><input v-model.number="cursor" type="range" min="0" :max="Math.max(0, report.events.length - 1)" aria-label="回放进度" style="width:100%"><button @click="playing = !playing">{{ playing ? '暂停' : '播放' }}</button><p v-if="frame">{{ (frame.at / 1000).toFixed(1) }}秒 · {{ report.fighters[frame.actor]?.name }} 使用 {{ frame.skill }}，造成 {{ frame.damage }}伤害</p></section>
    <h2>已登记对手</h2><p v-if="!registrations.some(r => r.userId !== uid)">暂无其他玩家登记，邀请伙伴登记防守英雄后即可挑战。</p><div class="cards"><article v-for="r in registrations.filter(r => r.userId !== uid)" :key="r.id" class="panel"><span class="badge">玩家 #{{ r.userId }}</span><h2>{{ r.snapshot.name }}</h2><p>Lv.{{ r.snapshot.level }} · {{ roles[r.snapshot.role] }} · <JobIcon :job-id="r.snapshot.jobId" :size="20" /> {{ jobName(r.snapshot.jobId) }}</p><p>生命 {{ Math.round(r.snapshot.stats.max_hp).toLocaleString() }} · 配装 {{ r.snapshot.items.length }}件</p><button class="primary" :disabled="busy || !heroId" @click="challenge(r.id)">挑战快照</button></article></div>
    <section class="panel"><h2>挑战与防守历史</h2><p v-if="!history.length">尚无战报。</p><div v-for="b in history" :key="b.id" class="row"><p>#{{ b.id }} · {{ b.attackerId === uid ? '主动挑战' : '防守挑战' }} · {{ b.result === 'draw' ? '平局' : (b.result === 'attacker') === (b.attackerId === uid) ? '胜利' : '失败' }}</p><button :disabled="busy" @click="replay(b.id)">查看回放</button></div></section>
  </main>
</template>
