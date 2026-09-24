/** 采集定位：把「某个材料」解析为「去哪个采集点采」。 */
import data from '@shared/schema'
import type { GatherNodeDef } from '@shared/schema'

export interface GatherTarget {
  jobId: string
  regionId: number
  /** 该采集点对该材料的产出权重（越大越容易采到）。 */
  weight: number
}

/**
 * 为采集材料挑一个采集点：只在**已解锁**地区里选，优先产出权重更高、地区更靠前的。
 * 传入 level 时再按采集等级过滤（避免规划到等级不够的采集点）。
 * 非采集材料（半成品 / 鱼 / 药水等）或没有可用的产出地时返回 null。
 */
export function findGatherTarget(
  materialId: string,
  isUnlocked: (regionId: number) => boolean,
  level?: number,
): GatherTarget | null {
  const material = data.materialById[materialId]
  if (!material || material.kind !== 'gather' || !material.jobId) return null

  const candidates: GatherTarget[] = []
  for (const node of data.gatherNodes.nodes as GatherNodeDef[]) {
    if (node.jobId !== material.jobId) continue
    const yieldEntry = node.yields.find((y) => y.materialId === materialId)
    if (!yieldEntry) continue
    if (!isUnlocked(node.regionId)) continue
    if (level !== undefined && node.levelReq > level) continue
    candidates.push({ jobId: node.jobId, regionId: node.regionId, weight: yieldEntry.weight })
  }
  if (candidates.length === 0) return null

  candidates.sort((a, b) => b.weight - a.weight || a.regionId - b.regionId)
  return candidates[0]
}

/** 采集受阻原因：等级不足 / 地区未解锁。 */
export type GatherBlockReason = 'level' | 'region'

export interface GatherAvailability {
  jobId: string
  regionId: number
  weight: number
  /** 当前能否采集；不能时给出原因。 */
  blocked: GatherBlockReason | null
  /** 所选采集点要求的采集等级。 */
  requiredLevel: number
}

/**
 * 宽松版采集定位：即使当前采不了也返回一个采集点（供序列规划与提示）。
 * 优先「已解锁且等级足够」的采集点（权重最高、地区最靠前）；否则回退到已解锁里
 * 等级要求最低的（blocked='level'），再退到全局等级要求最低的（blocked='region'）。
 * 非采集材料或没有任何产出地时返回 null。
 */
export function resolveGatherAvailability(
  materialId: string,
  isUnlocked: (regionId: number) => boolean,
  level?: number,
): GatherAvailability | null {
  const material = data.materialById[materialId]
  if (!material || material.kind !== 'gather' || !material.jobId) return null

  const nodes: GatherAvailability[] = []
  for (const node of data.gatherNodes.nodes as GatherNodeDef[]) {
    if (node.jobId !== material.jobId) continue
    const yieldEntry = node.yields.find((y) => y.materialId === materialId)
    if (!yieldEntry) continue
    nodes.push({
      jobId: node.jobId,
      regionId: node.regionId,
      weight: yieldEntry.weight,
      requiredLevel: node.levelReq,
      blocked: null,
    })
  }
  if (nodes.length === 0) return null

  const unlocked = nodes.filter((n) => isUnlocked(n.regionId))
  const ready = unlocked.filter((n) => level === undefined || n.requiredLevel <= level)
  if (ready.length > 0) {
    ready.sort((a, b) => b.weight - a.weight || a.regionId - b.regionId)
    return ready[0]
  }

  const pool = unlocked.length > 0 ? unlocked : nodes
  pool.sort((a, b) => a.requiredLevel - b.requiredLevel || a.regionId - b.regionId)
  return { ...pool[0], blocked: unlocked.length > 0 ? 'level' : 'region' }
}
