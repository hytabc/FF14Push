import data from '@shared/schema'

import type { SlotId } from '@/game/types'

/** 栏位分组：防具 / 饰品 / 武器（整行）。装备页与「查看他人装备」共用同一份定义。 */
export function equipmentSlotGroups() {
  const byId = new Map(data.slots.map((s) => [s.id as SlotId, s]))
  const pick = (ids: SlotId[]) => ids.map((id) => byId.get(id)).filter((s) => s !== undefined)
  return [
    { key: 'armor', title: '防具', slots: pick(['head', 'body', 'hands', 'legs', 'feet']), full: false },
    {
      key: 'accessory',
      title: '饰品',
      slots: pick(['necklace', 'earring', 'bracelet', 'ring1', 'ring2']),
      full: false,
    },
    { key: 'weapon', title: '武器', slots: pick(['mainHand']), full: true },
  ]
}

/** 生产 / 采集专用装备栏位分组：生产在左、采集在右。装备页 / 英雄页 / 他人装备弹窗共用。 */
export function dohdolSlotGroups() {
  const dohdolSlots = [...data.dohdolEquipment.slots].sort((a, b) => a.order - b.order)
  const pick = (kind: 'doh' | 'dol') => dohdolSlots.filter((s) => s.category.startsWith(kind))
  return [
    { key: 'doh', title: '生产', slots: pick('doh') },
    { key: 'dol', title: '采集', slots: pick('dol') },
  ]
}
