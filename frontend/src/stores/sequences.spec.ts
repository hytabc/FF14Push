import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  api: {
    sequences: vi.fn(),
    saveSequence: vi.fn(),
    overwriteSequence: vi.fn(),
    deleteSequence: vi.fn(),
    importBlueprint: vi.fn(),
  },
  dohdol: {
    sequence: [] as unknown[],
    loopMode: 'once',
    loopTotal: 3,
    seqActive: false,
    loadSequence: vi.fn(),
  },
  toast: { push: vi.fn() },
}))

vi.mock('@/api', () => ({ api: mocks.api }))
vi.mock('@/stores/dohdol', () => ({ useDohDolStore: () => mocks.dohdol }))
vi.mock('@/stores/toast', () => ({ useToastStore: () => mocks.toast }))

import type { SavedSequence } from '@/game/types'
import { useSequencesStore } from './sequences'

const gatherStep = {
  kind: 'gather' as const,
  id: 'step-1',
  materialId: 'ore7',
  name: '铁矿石',
  jobId: 'MIN',
  regionId: 7,
  target: 3,
}

function saved(overrides: Partial<SavedSequence> = {}): SavedSequence {
  return {
    id: 1,
    name: '挖矿流',
    shareCode: 'ABCDEFGH',
    steps: [{ ...gatherStep }],
    loopMode: 'once',
    loopTotal: 3,
    stepCount: 1,
    createdAt: null,
    updatedAt: null,
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  mocks.dohdol.sequence = [{ ...gatherStep }]
  mocks.dohdol.loopMode = 'once'
  mocks.dohdol.loopTotal = 3
  mocks.dohdol.seqActive = false
  mocks.dohdol.loadSequence.mockReturnValue(true)
})

describe('序列库 store', () => {
  it('load 拉取本人序列并统计数量 / 是否已满', async () => {
    mocks.api.sequences.mockResolvedValue({
      sequences: Array.from({ length: 5 }, (_, i) => saved({ id: i + 1, name: `序列${i}` })),
    })
    const store = useSequencesStore()
    await store.load()
    expect(store.list).toHaveLength(5)
    expect(store.count).toBe(5)
    expect(store.full).toBe(true)
    expect(store.byName('序列2')?.id).toBe(3)
  })

  it('saveCurrent 提交当前编辑区并刷新列表', async () => {
    mocks.api.sequences.mockResolvedValue({ sequences: [saved()] })
    mocks.api.saveSequence.mockResolvedValue({ sequence: saved() })
    const store = useSequencesStore()

    expect(await store.saveCurrent(' 挖矿流 ')).toBe(true)
    expect(mocks.api.saveSequence).toHaveBeenCalledWith({
      name: '挖矿流',
      steps: mocks.dohdol.sequence,
      loopMode: 'once',
      loopTotal: 3,
    })
    expect(store.list).toHaveLength(1)
    expect(mocks.toast.push).toHaveBeenCalledWith('已保存序列「挖矿流」', 'success')
  })

  it('saveCurrent 同名时提示覆盖', async () => {
    mocks.api.sequences.mockResolvedValue({ sequences: [saved()] })
    mocks.api.saveSequence.mockResolvedValue({ sequence: saved() })
    const store = useSequencesStore()
    await store.load()

    expect(await store.saveCurrent('挖矿流')).toBe(true)
    expect(mocks.toast.push).toHaveBeenCalledWith('已覆盖序列「挖矿流」', 'success')
  })

  it('saveCurrent 编辑区为空时拒绝且不请求', async () => {
    mocks.dohdol.sequence = []
    const store = useSequencesStore()
    expect(await store.saveCurrent('空')).toBe(false)
    expect(mocks.api.saveSequence).not.toHaveBeenCalled()
    expect(mocks.toast.push).toHaveBeenCalledWith('序列为空，请先添加步骤', 'error')
  })

  it('overwriteSlot 按槽位 id 提交当前编辑区', async () => {
    mocks.api.overwriteSequence.mockResolvedValue({ sequence: saved({ id: 3 }) })
    mocks.api.sequences.mockResolvedValue({ sequences: [saved({ id: 3 })] })
    const store = useSequencesStore()

    expect(await store.overwriteSlot(saved({ id: 3 }))).toBe(true)
    expect(mocks.api.overwriteSequence).toHaveBeenCalledWith(3, {
      steps: mocks.dohdol.sequence,
      loopMode: 'once',
      loopTotal: 3,
    })
  })

  it('remove 删除后从列表移除', async () => {
    mocks.api.sequences.mockResolvedValue({ sequences: [saved({ id: 1 }), saved({ id: 2 })] })
    mocks.api.deleteSequence.mockResolvedValue({ ok: true })
    const store = useSequencesStore()
    await store.load()

    expect(await store.remove(1)).toBe(true)
    expect(store.list.map((s) => s.id)).toEqual([2])
  })

  it('readSlot 载入编辑区并关闭弹窗', () => {
    const store = useSequencesStore()
    store.open = true
    expect(store.readSlot(saved({ loopMode: 'count', loopTotal: 5 }))).toBe(true)
    expect(mocks.dohdol.loadSequence).toHaveBeenCalledWith(
      expect.objectContaining({ loopMode: 'count', loopTotal: 5 }),
    )
    expect(store.open).toBe(false)
  })

  it('readSlot 在运行中被拒绝时不关闭弹窗', () => {
    mocks.dohdol.loadSequence.mockReturnValue(false)
    const store = useSequencesStore()
    store.open = true
    expect(store.readSlot(saved())).toBe(false)
    expect(store.open).toBe(true)
  })

  it('importByCode 用大写蓝图ID导入并载入编辑区', async () => {
    mocks.api.importBlueprint.mockResolvedValue({
      sequence: {
        name: '他人的序列',
        steps: [{ ...gatherStep }],
        loopMode: 'infinite',
        loopTotal: 1,
        stepCount: 1,
      },
    })
    const store = useSequencesStore()

    expect(await store.importByCode(' abcdefgh ')).toBe(true)
    expect(mocks.api.importBlueprint).toHaveBeenCalledWith('ABCDEFGH')
    expect(mocks.dohdol.loadSequence).toHaveBeenCalledWith(
      expect.objectContaining({ loopMode: 'infinite', loopTotal: 1 }),
    )
    expect(mocks.toast.push).toHaveBeenCalledWith('已导入蓝图「他人的序列」', 'success')
  })

  it('importByCode 蓝图不存在时提示', async () => {
    mocks.api.importBlueprint.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: '蓝图ID不存在' } },
      message: 'Request failed with status code 404',
    })
    const store = useSequencesStore()

    expect(await store.importByCode('ZZZZZZZZ')).toBe(false)
    expect(mocks.toast.push).toHaveBeenCalledWith('蓝图ID不存在', 'error')
  })
})
