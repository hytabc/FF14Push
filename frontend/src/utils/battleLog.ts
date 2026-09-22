import type { ExpCalculation } from '@/game/types'

export function experienceLog(amount: number, calculation?: ExpCalculation): string {
  if (!calculation) return '获得经验 ' + amount
  const pct = calculation.totalBonusPct
  const signed = (n: number) => (n >= 0 ? '+' : '−') + Math.abs(n)
  return '获得经验 ' + amount + '（' + (pct >= 0 ? '+' : '') + pct
    + '%；结算基础 ' + calculation.base + '，效率加成 ' + signed(calculation.efficiencyBonus)
    + '，追赶加成 ' + signed(calculation.catchUpBonus) + '）'
}
