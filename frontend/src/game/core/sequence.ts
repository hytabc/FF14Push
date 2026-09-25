/** 采集 / 制作序列：把多个「材料 + 数量」或「物品 + 数量」编排成一条有序队列。 */
import data from '@shared/schema'
import type { RecipeDef } from '@shared/schema'

import { resolveGatherAvailability, type GatherBlockReason } from '@/game/core/gather'

export interface GatherStep {
  kind: 'gather'
  id: string
  materialId: string
  name: string
  jobId: string
  regionId: number
  target: number
  /** 加入时的采集受阻原因快照（等级不足 / 地区未解锁）；实时判定见 gatherStepIssue。 */
  blocked?: GatherBlockReason | null
  /** 受阻时所需采集等级（提示用）。 */
  requiredLevel?: number
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

/** 恢复持久化队列时调用：把 id 计数器抬到已有 `step-N` 的最大值，避免新增步骤与恢复的步骤 id 冲突。 */
export function seedStepIds(steps: SequenceStep[]): void {
  for (const step of steps) {
    const match = /^step-(\d+)$/.exec(step.id)
    if (match) stepCounter = Math.max(stepCounter, Number(match[1]))
  }
}

/** 序列步骤的稳定 key（同种目标合并时也据此判断）。 */
export function stepKey(step: SequenceStep): string {
  return step.kind === 'gather' ? `gather:${step.materialId}` : `produce:${step.recipeId}`
}

/** 把「材料 + 数量」解析成采集步：即使当前采不了也返回带 blocked 标记的步骤，找不到采集点返回 null。 */
export function resolveGatherStep(
  materialId: string,
  target: number,
  isUnlocked: (regionId: number) => boolean,
  dolLevel: number,
  id: string,
): GatherStep | null {
  const material = data.materialById[materialId]
  if (!material || material.kind !== 'gather') return null
  const found = resolveGatherAvailability(materialId, isUnlocked, dolLevel)
  if (!found) return null
  return {
    kind: 'gather',
    id,
    materialId,
    name: material.name,
    jobId: found.jobId,
    regionId: found.regionId,
    target: Math.max(1, Math.floor(target)),
    blocked: found.blocked,
    requiredLevel: found.requiredLevel,
  }
}

/** 采集步当前能否执行：不可执行时返回中文原因，否则 null。 */
export function gatherStepIssue(
  step: GatherStep,
  isUnlocked: (regionId: number) => boolean,
  dolLevel: number,
): string | null {
  const found = resolveGatherAvailability(step.materialId, isUnlocked, dolLevel)
  if (!found) return '无法采集该材料'
  if (found.blocked === 'region') return '所在地区未解锁'
  if (found.blocked === 'level') return `需要采集等级 Lv.${found.requiredLevel}（当前 Lv.${dolLevel}）`
  return null
}

/** 产出材料 id → 生产它的配方（合成树展开用；同种产出取首个配方）。 */
const recipeByOutputMaterial: Record<string, RecipeDef> = {}
for (const recipe of data.recipes.recipes as RecipeDef[]) {
  const out = recipe.output
  if (out.kind === 'material' && out.itemId && !recipeByOutputMaterial[out.itemId]) {
    recipeByOutputMaterial[out.itemId] = recipe
  }
}

/** 配方产出的展示名。 */
function recipeOutputName(recipe: RecipeDef): string {
  const out = recipe.output
  if (out.itemId) {
    return data.materialById[out.itemId]?.name ?? data.consumableById[out.itemId]?.name ?? out.itemId
  }
  if (out.baseId) return data.baseItemById[out.baseId]?.name ?? out.baseId
  return recipe.id
}

export interface ExpandContext {
  isUnlocked: (regionId: number) => boolean
  dolLevel: number
  nextId: () => string
}

export interface ExpandResult {
  steps: SequenceStep[]
  warnings: string[]
}

/**
 * 把「配方 + 数量」递归展开为完整合成队列：依赖优先（先采集、先中间品，最后目标）。
 * 同种采集 / 同个配方会合并数量；不存在的材料或无法采集的材料会记入 warnings。
 */
export function expandRecipeSteps(recipeId: string, target: number, ctx: ExpandContext): ExpandResult {
  const root = data.recipeById[recipeId]
  if (!root) return { steps: [], warnings: [`未找到配方 ${recipeId}`] }

  const gatherSteps: GatherStep[] = []
  const gatherByMaterial = new Map<string, GatherStep>()
  const produceSteps: ProduceStep[] = []
  const produceByRecipe = new Map<string, ProduceStep>()
  const visiting = new Set<string>()
  const warnings: string[] = []
  const warn = (text: string) => {
    if (!warnings.includes(text)) warnings.push(text)
  }

  function addGather(materialId: string, qty: number) {
    const existing = gatherByMaterial.get(materialId)
    if (existing) {
      existing.target += qty
      return
    }
    const material = data.materialById[materialId]
    const found = material ? resolveGatherAvailability(materialId, ctx.isUnlocked, ctx.dolLevel) : null
    if (!material || !found) {
      warn(`「${material?.name ?? materialId}」无法采集，未加入序列`)
      return
    }
    const step: GatherStep = {
      kind: 'gather',
      id: ctx.nextId(),
      materialId,
      name: material.name,
      jobId: found.jobId,
      regionId: found.regionId,
      target: qty,
      blocked: found.blocked,
      requiredLevel: found.requiredLevel,
    }
    gatherByMaterial.set(materialId, step)
    gatherSteps.push(step)
  }

  function ensureInput(itemId: string, needed: number) {
    const material = data.materialById[itemId]
    if (material?.kind === 'gather') {
      addGather(itemId, needed)
      return
    }
    if (material?.kind === 'fish') {
      warn(`「${material.name}」需通过钓鱼获取，未加入序列`)
      return
    }
    const producer = recipeByOutputMaterial[itemId]
    if (producer) {
      const perCraft = Math.max(1, Math.floor(producer.output.count ?? 1))
      scheduleProduce(producer, Math.ceil(needed / perCraft))
      return
    }
    warn(`「${material?.name ?? itemId}」没有可用配方，未加入序列`)
  }

  function scheduleProduce(producer: RecipeDef, crafts: number) {
    if (crafts <= 0) return
    const existing = produceByRecipe.get(producer.id)
    if (existing) {
      existing.target += crafts
    } else if (visiting.has(producer.id)) {
      warn(`配方「${recipeOutputName(producer)}」存在循环依赖，已跳过`)
      return
    } else {
      visiting.add(producer.id)
      for (const input of producer.inputs) ensureInput(input.itemId, input.count * crafts)
      visiting.delete(producer.id)
      const step: ProduceStep = {
        kind: 'produce',
        id: ctx.nextId(),
        recipeId: producer.id,
        name: recipeOutputName(producer),
        jobId: producer.jobId,
        target: crafts,
      }
      produceByRecipe.set(producer.id, step)
      produceSteps.push(step)
      return
    }
    // 已存在：只补新增数量的依赖（不会产生新的步骤位置）。
    for (const input of producer.inputs) ensureInput(input.itemId, input.count * crafts)
  }

  scheduleProduce(root, Math.max(1, Math.floor(target)))
  return { steps: [...gatherSteps, ...produceSteps], warnings }
}
