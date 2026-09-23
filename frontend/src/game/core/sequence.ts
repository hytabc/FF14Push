/** 采集 / 制作序列：把多个「材料 + 数量」或「物品 + 数量」编排成一条有序队列。 */
import data from '@shared/schema'

import { findGatherTarget } from '@/game/core/gather'

export interface GatherStep {
  kind: 'gather'
  id: string
  materialId: string
  name: string
  jobId: string
  regionId: number
  target: number
}

export interface ProduceStep {
  kind: 'produce'
  id: string
  recipeId: string
  name: string
  jobId: string
  target: number
}

export type SequenceStep = GatherStep | ProduceStep

export type StepStatus = 'done' | 'partial' | 'skipped' | 'interrupted'

/** 序列循环模式：不循环 / 固定轮数 / 无限。 */
export type SequenceLoopMode = 'once' | 'count' | 'infinite'

export interface StepResult {
  id: string
  name: string
  done: number
  target: number
  status: StepStatus
  reason?: string
}

/** 单条序列的步数上限。 */
export const SEQ_STEP_LIMIT = 50

let stepCounter = 0

/** 生成步骤的稳定 id（仅用于渲染 key 与增删排序）。 */
export function nextStepId(): string {
  stepCounter += 1
  return `step-${stepCounter}`
}

/** 序列步骤的稳定 key（同种目标合并时也据此判断）。 */
export function stepKey(step: SequenceStep): string {
  return step.kind === 'gather' ? `gather:${step.materialId}` : `produce:${step.recipeId}`
}

/** 把「材料 + 数量」解析成采集步：只在已解锁且等级足够的采集点里选，找不到返回 null。 */
export function resolveGatherStep(
  materialId: string,
  target: number,
  isUnlocked: (regionId: number) => boolean,
  dolLevel: number,
  id: string,
): GatherStep | null {
  const material = data.materialById[materialId]
  if (!material || material.kind !== 'gather') return null
  const found = findGatherTarget(materialId, isUnlocked, dolLevel)
  if (!found) return null
  return {
    kind: 'gather',
    id,
    materialId,
    name: material.name,
    jobId: found.jobId,
    regionId: found.regionId,
    target: Math.max(1, Math.floor(target)),
  }
}
