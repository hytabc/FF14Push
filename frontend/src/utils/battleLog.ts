import type { ActivityExpBreakdown, ExpCalculation, GoldCalculation } from '@/game/types'

export function experienceLog(amount: number, calculation?: ExpCalculation): string {
  if (!calculation) return '获得经验 ' + amount
  const pct = calculation.totalBonusPct
  const signed = (n: number) => (n >= 0 ? '+' : '−') + Math.abs(n)
  return '获得经验 ' + amount + '（' + (pct >= 0 ? '+' : '') + pct
    + '%；结算基础 ' + calculation.base + '，效率加成 ' + signed(calculation.efficiencyBonus)
    + '，追赶加成 ' + signed(calculation.catchUpBonus) + '）'
}

/** 战斗金币结算文案：与 `experienceLog` 同构，展示服务端结算来源明细。 */
export function goldLog(amount: number, calculation?: GoldCalculation): string {
  if (!calculation) return '获得金币 ' + amount
  const pct = calculation.totalBonusPct
  const signed = (n: number) => (n >= 0 ? '+' : '−') + Math.abs(n)
  return '获得金币 ' + amount + '（' + (pct >= 0 ? '+' : '') + pct
    + '%；结算基础 ' + calculation.base + '，收益加成 ' + signed(calculation.penaltyBonus)
    + '，药水加成 ' + signed(calculation.potionBonus) + '）'
}

/** 生产 / 采集 / 钓鱼的单次经验结算文案：基础、品阶系数与逐条经验加成来源。 */
export function activityExpLog(breakdown: ActivityExpBreakdown): string {
  const signed = (n: number) => (n >= 0 ? '+' : '−') + Math.abs(n)
  const parts = ['基础 ' + breakdown.base]
  if (Math.abs(breakdown.rarityMultiplier - 1) > 1e-6) {
    parts.push('品阶 ×' + breakdown.rarityMultiplier)
  }
  let text = '获得经验 ' + breakdown.amount + '（' + parts.join('，')
  if (breakdown.bonusPct > 0) text += '，经验加成 +' + breakdown.bonusPct + '%'
  if (breakdown.sources.length) {
    text += '：' + breakdown.sources.map((s) => s.label + ' ' + signed(s.pct) + '%').join('、')
  }
  return text + '）'
}
