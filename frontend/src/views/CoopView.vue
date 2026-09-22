<script setup lang="ts">
import { jobName } from '@/utils/format'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { http, toApiError } from '@/api/client'
import { useGameStore } from '@/stores/game'
import { useAuthStore } from '@/stores/auth'
import { type Dungeon, type Room, type RoomBrief, type Roster, type Mode, type Registration, type BattleState, modes, roles, difficulties, actions, seatQuota, remaining, mergeEvents } from '@/game/multiplayer'
const game = useGameStore(), auth = useAuthStore()
const uid = computed(() => game.state?.user.id ?? 0)
const dungeons = ref<Dungeon[]>([]), rooms = ref<RoomBrief[]>([]), mine = ref<RoomBrief[]>([])
const roster = ref<Roster | null>(null), registrations = ref<Registration[]>([]), room = ref<Room | null>(null)
const error = ref(''), notice = ref(''), busy = ref(false), mode = ref<Mode>('solo'), code = ref(''), filter = ref('normal')
const choices = ref<Record<number, string>>({}), strategies = ref<Record<number, string>>({}), selected = ref<number[]>([])
const registerId = ref<number>(), values = ref<Record<number, number>>({}), receipt = ref<null | { firstClear: boolean; goldGained: number; exp: { heroId: number; exp: number }[] }>(null)
const state = computed(() => room.value?.battle?.state)
const available = computed(() => dungeons.value.filter(d => d.difficulty === filter.value))
const mySeats = computed(() => room.value?.seats.filter(s => s.controllerId === uid.value) ?? [])
let interval: ReturnType<typeof setInterval> | undefined, socket: WebSocket | undefined, disposed = false, polling = false, connecting = false
function key() { return crypto.randomUUID() }
async function act(fn: () => Promise<unknown>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await fn() } catch (e) { error.value = toApiError(e).message } finally { busy.value = false }
}
async function load() {
  const [ds, rs, hs, regs] = await Promise.all([
    http.get<{ dungeons: Dungeon[] }>('/coop/dungeons'), http.get<{ rooms: RoomBrief[]; mine: RoomBrief[] }>('/coop/rooms'),
    http.get<Roster>('/heroes'), http.get<{ registrations: Registration[] }>('/registrations?kind=clone')])
  dungeons.value = ds.data.dungeons; rooms.value = rs.data.rooms; mine.value = rs.data.mine; roster.value = hs.data; registrations.value = regs.data.registrations
}
async function connect() {
  if (connecting || disposed || !room.value || room.value.status !== 'running' || (socket && socket.readyState < 2)) return
  connecting = true
  const id = room.value.id
  try {
    const ticket = (await http.post<{ ticket: string }>(`/coop/rooms/${id}/ticket`)).data.ticket
    if (disposed || room.value?.id !== id) return
    const url = new URL(`${http.defaults.baseURL}/coop/ws`, location.origin)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; url.searchParams.set('ticket', ticket)
    socket = new WebSocket(url)
    socket.onmessage = event => {
      if (!room.value || room.value.id !== id) return
      const msg = JSON.parse(event.data) as { state: BattleState; sequence: number; battleId: number; type: string }
      if (room.value.battle && msg.sequence < room.value.battle.sequence) return
      msg.state.events = mergeEvents(room.value.battle?.state.events ?? [], msg.state.events)
      room.value.battle = { id: msg.battleId, sequence: msg.sequence, state: msg.state }; room.value.status = msg.state.status
    }
    socket.onerror = () => { notice.value = '连接恢复中，正在通过房间快照同步。' }
  } catch (e) { error.value = toApiError(e).message } finally { connecting = false }
}
async function open(id: number) {
  socket?.close(); receipt.value = null
  room.value = (await http.get<Room>(`/coop/rooms/${id}`)).data
  localStorage.setItem(`coop.room.${uid.value}`, String(id)); selected.value = mySeats.value.map(s => s.slot)
  await http.post(`/coop/rooms/${id}/heartbeat`); await connect()
}
async function create(d: Dungeon) {
  await act(async () => { const result = await http.post<Room>('/coop/rooms', { dungeonId: d.id, mode: mode.value }); await open(result.data.id) })
}
async function join() { await act(async () => { const r = await http.post<Room>('/coop/rooms/join', { code: code.value.trim() }); await open(r.data.id) }) }
async function refreshRoom() {
  if (!room.value) return
  const next = (await http.get<Room>(`/coop/rooms/${room.value.id}`)).data
  if (next.battle && room.value.battle && next.battle.sequence < room.value.battle.sequence) return
  room.value = next
}
async function assign(slot: number) {
  const choice = choices.value[slot]; if (!choice || !room.value) return
  const [kind, id] = choice.split(':')
  await act(async () => {
    room.value = (await http.put<Room>(`/coop/rooms/${room.value!.id}/seat`, {
      slot, controllerId: uid.value, heroId: kind === 'h' ? Number(id) : null,
      registrationId: kind === 'r' ? Number(id) : null, strategy: strategies.value[slot] ?? 'manual',
    })).data; selected.value = mySeats.value.map(s => s.slot)
  })
}
async function ready() { await act(async () => { room.value = (await http.post<Room>(`/coop/rooms/${room.value!.id}/ready`, { ready: !room.value?.members.find(m => m.userId === uid.value)?.ready })).data }) }
async function start() {
  await act(async () => { await game.stopBattle(true); await game.stopRaid(true); room.value = (await http.post<Room>(`/coop/rooms/${room.value!.id}/start`)).data; await connect() })
}
async function send(mechanic: { id: string; action: string }) {
  await act(async () => {
    for (const slot of selected.value) await http.post(`/coop/rooms/${room.value!.id}/commands`, {
      key: key(), slots: [slot], mechanicId: mechanic.id, action: mechanic.action,
      value: values.value[slot] ?? (mechanic.action === 'spread' ? slot : mechanic.action === 'stack' ? slot % 2 : 0),
    })
    notice.value = '指令已提交，执行结果见战斗日志。'
  })
}
async function target(id: number) { await act(() => http.post(`/coop/rooms/${room.value!.id}/commands`, { key: key(), slots: selected.value, action: 'target', target: id })) }
async function claim() { await act(async () => { receipt.value = (await http.post(`/coop/rooms/${room.value!.id}/claim`)).data; await game.loadState() }) }
async function back(leave = false) {
  await act(async () => {
    if (leave && room.value) await http.post(`/coop/rooms/${room.value.id}/leave`)
    socket?.close(); room.value = null; localStorage.removeItem(`coop.room.${uid.value}`); await load()
  })
}
async function heartbeat() {
  if (!room.value || disposed || polling || !auth.isLoggedIn) return
  polling = true
  try {
    await http.post(`/coop/rooms/${room.value.id}/heartbeat`)
    await refreshRoom(); await connect()
  } catch (e) { error.value = toApiError(e).message } finally { polling = false }
}
onMounted(() => act(async () => {
  interval = setInterval(() => void heartbeat(), 5000)
  await game.loadState(); await load()
  const saved = Number(localStorage.getItem(`coop.room.${uid.value}`)); if (saved) await open(saved)
}))
onUnmounted(() => { disposed = true; clearInterval(interval); socket?.close() })
</script>
<template>
  <main class="dlc">
    <header><p class="eyebrow">八英雄远征 · 合作大厅</p><h1>{{ room ? room.dungeon.name : '集结，向更深处进发' }}</h1>
      <p>普通副本 2 英雄 / 最多 2 人 · 高难 8 英雄 / 2 坦 2 治疗 4 输出 · 自动技能与机制指令</p></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <template v-if="!room">
      <div class="toolbar"><select v-model="mode" aria-label="挑战模式"><option v-for="(label,id) in modes" :key="id" :value="id">{{ label }}</option></select>
        <input v-model="code" placeholder="输入房间码" aria-label="房间码" maxlength="12"><button :disabled="busy || !code" @click="join">加入房间</button><RouterLink to="/roster">管理英雄 →</RouterLink></div>
      <p>{{ mode === 'solo' ? '使用自己的英雄，伤害、治疗与护盾降低15%。' : mode === 'offline' ? '与登记克隆体组队，克隆体伤害、治疗与护盾降低20%。' : '全员在线准备后开战，掉线英雄临时克隆化，重连恢复。' }}</p>
      <div class="toolbar"><button v-for="(label,id) in difficulties" :key="id" :class="{ primary: filter === id }" @click="filter = id">{{ label }}</button></div>
      <div class="cards"><article v-for="d in available" :key="d.id" class="panel"><span class="badge">Lv.{{ d.requiredLevel }} · {{ d.seats }} 英雄</span><h2>{{ d.name }}</h2><p>{{ d.phases.map(p => p.name).join(' → ') }}</p><p>狂暴 {{ Math.round(d.enrageSeconds / 60) }} 分钟</p><p v-if="d.prerequisite">前置：{{ dungeons.find(x => x.id === d.prerequisite)?.name }}</p><button class="primary" :disabled="busy" @click="create(d)">创建{{ modes[mode] }}</button></article></div>
      <section class="panel"><h2>克隆登记</h2><p>登记当前配装与通关资格，更新或撤回不会影响已经开始的战斗。外部克隆不领取奖励。</p>
        <select v-model="registerId" aria-label="登记英雄"><option :value="undefined">选择英雄</option><option v-for="h in roster?.heroes" :key="h.id" :value="h.id">{{ h.name }} Lv.{{ h.level }} · {{ jobName(h.jobId) }}</option></select>
        <button :disabled="busy || !registerId" @click="act(async () => { await http.post('/registrations', { heroId: registerId, kind: 'clone' }); await load() })">登记 / 更新克隆</button>
        <div v-for="r in registrations.filter(r => r.userId === uid)" :key="r.id" class="row"><span>{{ r.snapshot.name }} · {{ roles[r.snapshot.role] }}</span><button :disabled="busy" @click="act(async () => { await http.delete(`/registrations/${r.id}`); await load() })">撤回</button></div>
      </section>
      <div class="cards"><section class="panel"><h2>公开房间</h2><p v-if="!rooms.length">暂无公开房间，创建一个邀请伙伴吧。</p><div v-for="r in rooms" :key="r.id" class="row"><span>{{ dungeons.find(d => d.id === r.dungeonId)?.name }} · {{ r.code }}</span><button :disabled="busy" @click="code = r.code; join()">加入</button></div></section>
        <section class="panel"><h2>我的房间与战报</h2><div v-for="r in mine" :key="r.id" class="row"><span>{{ r.code }} · {{ modes[r.mode] }} · {{ r.status }}</span><button :disabled="busy" @click="act(() => open(r.id))">打开</button></div></section></div>
    </template>
    <template v-else>
      <div class="toolbar"><span class="badge">{{ modes[room.mode] }}</span><span class="badge">房间码 {{ room.code }}</span><button @click="back()">返回大厅</button><button v-if="room.status === 'lobby' || room.status === 'running'" :disabled="busy" @click="back(true)">{{ room.status === 'running' ? '离开（转克隆）' : '退出 / 关闭房间' }}</button></div>
      <section v-if="room.status === 'lobby'" class="panel"><h2>编队准备</h2><p>当前 {{ room.members.length }} 人，每人提供 {{ seatQuota(room.dungeon.seats, room.members.length) }} 名英雄。各玩家选择自己英雄，房主可移除席位后重新安排。</p>
        <div class="toolbar"><span v-for="m in room.members" :key="m.userId" class="badge">玩家 #{{ m.userId }} · {{ m.online ? '在线' : '离线' }} · {{ m.ready ? '已准备' : '未准备' }}</span></div>
        <div v-for="slot in room.dungeon.seats" :key="slot" class="seat"><h3>席位 {{ slot }}</h3>
          <template v-if="room.seats.find(s => s.slot === slot - 1)"><p>{{ room.seats.find(s => s.slot === slot - 1)?.snapshot.name }} · {{ roles[room.seats.find(s => s.slot === slot - 1)!.snapshot.role] }} · 玩家 #{{ room.seats.find(s => s.slot === slot - 1)?.controllerId }} {{ room.seats.find(s => s.slot === slot - 1)?.registrationId ? '（登记克隆）' : '' }}</p><button :disabled="busy" @click="act(async () => { await http.delete(`/coop/rooms/${room!.id}/seats/${slot - 1}`); await refreshRoom() })">移除</button></template>
          <template v-else><select v-model="choices[slot - 1]" aria-label="席位英雄"><option :value="undefined">选择英雄或克隆</option><optgroup label="我的英雄"><option v-for="h in roster?.heroes" :key="h.id" :value="`h:${h.id}`">{{ h.name }} Lv.{{ h.level }} · {{ jobName(h.jobId) }}</option></optgroup><optgroup v-if="room.mode === 'offline'" label="登记克隆"><option v-for="r in registrations.filter(r => r.userId !== uid)" :key="r.id" :value="`r:${r.id}`">{{ r.snapshot.name }} Lv.{{ r.snapshot.level }} · {{ roles[r.snapshot.role] }}</option></optgroup></select>
            <select v-model="strategies[slot - 1]" aria-label="战前策略"><option :value="undefined">手动机制指令</option><option value="manual">手动机制指令</option><option value="assist">自动执行标准编队策略</option></select><button :disabled="busy || !choices[slot - 1]" @click="assign(slot - 1)">加入席位</button></template>
        </div>
        <details v-if="room.entryFailures.length" open><summary>开战检查</summary><ul><li v-for="e in room.entryFailures" :key="e">{{ e }}</li></ul></details>
        <button :disabled="busy" @click="ready">{{ room.members.find(m => m.userId === uid)?.ready ? '取消准备' : '准备完成' }}</button><button v-if="room.ownerId === uid" class="primary" :disabled="busy || room.entryFailures.length > 0" @click="start">开始挑战</button>
      </section>
      <template v-if="state">
        <section class="panel"><div class="row"><h2>{{ state.status === 'cleared' ? '挑战成功' : state.status === 'failed' ? '挑战失败' : `阶段 ${state.phase + 1}` }}</h2><span>{{ (state.elapsedMs / 1000).toFixed(1) }} 秒 / {{ room.dungeon.enrageSeconds }} 秒</span></div><p v-if="state.reason" class="error">{{ state.reason }}</p>
          <p>死亡 5 秒复活 · 衰弱 60 秒（输出 / 治疗 / 护盾减半） · 全员死亡立即失败</p>
          <div v-for="b in state.bosses" :key="b.id" class="boss"><div class="row"><strong>{{ b.name }}</strong><small>{{ Math.ceil(b.hp).toLocaleString() }} / {{ Math.ceil(b.maxHp).toLocaleString() }}</small><button :disabled="busy || !selected.length || state.status !== 'running'" @click="target(b.id)">选中英雄集火</button></div><progress :value="b.hp" :max="b.maxHp" /></div>
          <div v-for="m in state.mechanics.filter(m => m.opened && !m.resolved)" :key="m.id" class="mechanic"><h3>{{ m.name }} · {{ remaining(m.deadline, state.elapsedMs) }} 秒</h3><p>{{ actions[m.action] }}：散开使用各英雄独立位置；分摊使用0/1两组；集火使用相同目标编号。</p><button class="primary" :disabled="busy || !selected.length" @click="send(m)">向选中英雄下达{{ actions[m.action] }}指令</button></div>
          <p v-if="state.trial && !state.trialDone">个人职责检查中：{{ remaining(state.trial.endsAt, state.elapsedMs) }} 秒，各英雄必须独立完成。</p>
        </section>
        <div class="heroes"><article v-for="h in state.heroes" :key="h.slot" class="hero-card" :class="{ selected: selected.includes(h.slot) }"><div class="row"><label><input v-if="h.controllerId === uid && !h.registeredClone" v-model="selected" type="checkbox" :value="h.slot"> {{ h.slot + 1 }}. {{ h.snapshot.name }}</label><small>{{ roles[h.snapshot.role] }}</small></div><span v-if="h.clone" class="badge">克隆 · 效能80%</span><span v-if="h.hp <= 0" class="badge danger">复活 {{ remaining(h.deadUntil, state.elapsedMs) }}秒</span><span v-else-if="h.weakUntil > state.elapsedMs" class="badge danger">衰弱 {{ remaining(h.weakUntil, state.elapsedMs) }}秒</span>
          <progress :value="h.hp" :max="h.snapshot.stats.max_hp" /><small>HP {{ Math.round(h.hp).toLocaleString() }} · MP {{ Math.round(h.mp) }}</small><p>输出 {{ Math.round(h.damage).toLocaleString() }} · 治疗 {{ Math.round(h.healing).toLocaleString() }}</p><small>{{ h.trialPassed ? '职责检查通过' : '职责检查待完成' }} · 死亡 {{ h.deaths }}</small><div v-if="h.controllerId === uid"><label>位置 / 分摊组 <input v-model.number="values[h.slot]" type="number" min="0" max="7" :placeholder="String(h.slot)" style="width:70px"></label></div></article></div>
        <section class="panel" style="margin-top:16px"><h2>战斗日志</h2><div class="logs"><div v-for="e in state.events.slice().reverse()" :key="e.seq">[{{ (e.at / 1000).toFixed(1) }}s] {{ e.text }}</div></div></section>
        <section v-if="state.status === 'cleared'" class="panel"><h2>远征奖励</h2><p>{{ state.hadClone ? '含克隆体通关' : '全程真实英雄通关' }} · 奖励按账号领取，经验仅分配给真实参战英雄。</p><button :disabled="busy || !!receipt" class="primary" @click="claim">{{ receipt ? '奖励已领取' : '领取奖励' }}</button><p v-if="receipt">{{ receipt.firstClear ? '首次通关' : '重复通关' }} · 金币 +{{ receipt.goldGained }} · 总经验 +{{ receipt.exp.reduce((sum, x) => sum + x.exp, 0) }}</p></section>
        <button v-if="state.status !== 'running'" :disabled="busy" @click="create(room.dungeon)">从头创建新挑战</button>
      </template>
    </template>
  </main>
</template>
