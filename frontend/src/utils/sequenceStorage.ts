/**
 * 采集 / 生产序列的本地持久化（断点续传）。
 *
 * 序列队列与「运行断点」按账号存到 localStorage（键 `eorzea.sequence.<userId>`），
 * 整页刷新 / 版本更新重载后由 store 恢复；服务端不保存序列概念。
 * 存储读写的防御式写法仿 `stores/announcement.ts`（Node / 隐私模式安全）。
 */
import type {
  SequenceLoopMode,
  SequenceStep,
  StepResult,
  StepStatus,
} from '@/game/core/sequence'
import { SEQ_STEP_LIMIT } from '@/game/core/sequence'

const PREFIX = 'eorzea.sequence.'
/** 快照结构版本：不匹配时直接忽略（防止旧结构被误解析）。 */
const SCHEMA = 1

export interface PersistedSequence {
  v: number
  steps: SequenceStep[]
  loopMode: SequenceLoopMode
  loopTotal: number
  /** 是否处于运行中。 */
  active: boolean
  /** 当前步骤下标（未运行为 -1）。 */
  index: number
  /** 当前轮次，从 1 起。 */
  round: number
  /** 当前采集步「序列开始后」新采到的目标材料数量。 */
  gatherGained: number
  /** 当前制作步已制造数量（跨会话累计）。 */
  produceDone: number
  results: StepResult[]
  savedAt: number
}

export function sequenceKey(userId: number): string {
  return `${PREFIX}${userId}`
}

const LOOP_MODES: SequenceLoopMode[] = ['once', 'count', 'infinite']
const STEP_STATUSES: StepStatus[] = ['done', 'partial', 'skipped', 'interrupted']

function toCount(value: unknown, fallback = 0): number {
  const n = Math.floor(Number(value))
  return Number.isFinite(n) && n >= 0 ? n : fallback
}

function sanitizeStep(raw: unknown): SequenceStep | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const id = typeof r.id === 'string' ? r.id : ''
  const name = typeof r.name === 'string' ? r.name : ''
  const jobId = typeof r.jobId === 'string' ? r.jobId : ''
  const target = Math.max(1, toCount(r.target, 1))
  if (!id || !jobId) return null
  if (r.kind === 'gather') {
    const materialId = typeof r.materialId === 'string' ? r.materialId : ''
    if (!materialId) return null
    return {
      kind: 'gather',
      id,
      materialId,
      name,
      jobId,
      regionId: toCount(r.regionId),
      target,
      blocked: null,
      requiredLevel: r.requiredLevel === undefined ? undefined : toCount(r.requiredLevel),
    }
  }
  if (r.kind === 'produce') {
    const recipeId = typeof r.recipeId === 'string' ? r.recipeId : ''
    if (!recipeId) return null
    return { kind: 'produce', id, recipeId, name, jobId, target }
  }
  return null
}

function sanitizeResult(raw: unknown): StepResult | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const id = typeof r.id === 'string' ? r.id : ''
  const status = STEP_STATUSES.includes(r.status as StepStatus) ? (r.status as StepStatus) : null
  if (!id || !status) return null
  return {
    id,
    name: typeof r.name === 'string' ? r.name : '',
    done: toCount(r.done),
    target: toCount(r.target),
    status,
    reason: typeof r.reason === 'string' ? r.reason : undefined,
  }
}

/** 读取并校验快照；结构不符 / 解析失败返回 null。 */
export function readSequence(userId: number): PersistedSequence | null {
  try {
    if (typeof localStorage === 'undefined') return null
    const raw = localStorage.getItem(sequenceKey(userId))
    if (!raw) return null
    const data = JSON.parse(raw) as Record<string, unknown>
    if (!data || typeof data !== 'object' || data.v !== SCHEMA) return null
    const steps = (Array.isArray(data.steps) ? data.steps : [])
      .map(sanitizeStep)
      .filter((s): s is SequenceStep => s !== null)
      .slice(0, SEQ_STEP_LIMIT)
    const results = (Array.isArray(data.results) ? data.results : [])
      .map(sanitizeResult)
      .filter((r): r is StepResult => r !== null)
    return {
      v: SCHEMA,
      steps,
      loopMode: LOOP_MODES.includes(data.loopMode as SequenceLoopMode)
        ? (data.loopMode as SequenceLoopMode)
        : 'once',
      loopTotal: Math.max(1, toCount(data.loopTotal, 3)),
      active: data.active === true,
      index: Number.isInteger(data.index) ? (data.index as number) : -1,
      round: Math.max(1, toCount(data.round, 1)),
      gatherGained: toCount(data.gatherGained),
      produceDone: toCount(data.produceDone),
      results,
      savedAt: toCount(data.savedAt),
    }
  } catch {
    return null
  }
}

export function writeSequence(userId: number, data: PersistedSequence): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(sequenceKey(userId), JSON.stringify(data))
  } catch {
    /* 隐私模式 / 配额不足时忽略 */
  }
}

export function clearStoredSequence(userId: number): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(sequenceKey(userId))
  } catch {
    /* 忽略 */
  }
}
