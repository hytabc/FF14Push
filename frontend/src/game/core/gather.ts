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
 * 非采集材料（半成品 / 鱼 / 药水等）或没有已解锁产出地时返回 null。
 */
export function findGatherTarget(
  materialId: string,
  isUnlocked: (regionId: number) => boolean,
): GatherTarget | null {
  const material = data.materialById[materialId]
  if (!material || material.kind !== 'gather' || !material.jobId) return null

  const candidates: GatherTarget[] = []
  for (const node of data.gatherNodes.nodes as GatherNodeDef[]) {
    if (node.jobId !== material.jobId) continue
    const yieldEntry = node.yields.find((y) => y.materialId === materialId)
    if (!yieldEntry) continue
    if (!isUnlocked(node.regionId)) continue
    candidates.push({ jobId: node.jobId, regionId: node.regionId, weight: yieldEntry.weight })
  }
  if (candidates.length === 0) return null

  candidates.sort((a, b) => b.weight - a.weight || a.regionId - b.regionId)
  return candidates[0]
}
