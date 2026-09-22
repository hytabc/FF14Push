import { afterEach, describe, expect, it, vi } from 'vitest'
import { requestKey } from './requestKey'

afterEach(() => vi.unstubAllGlobals())
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('requestKey', () => {
  it('使用浏览器原生 UUID', () => {
    const randomUUID = vi.fn(() => 'native-uuid')
    vi.stubGlobal('crypto', { randomUUID })
    expect(requestKey()).toBe('native-uuid')
    expect(randomUUID).toHaveBeenCalledOnce()
  })
  it('HTTP 环境只有 getRandomValues 时生成不同的合法 UUID', () => {
    let seed = 0
    const getRandomValues = vi.fn((bytes: Uint8Array) => bytes.fill(++seed))
    vi.stubGlobal('crypto', { getRandomValues })
    const keys = Array.from({ length: 100 }, requestKey)
    keys.forEach(key => expect(key).toMatch(uuid))
    expect(new Set(keys).size).toBe(keys.length)
    expect(getRandomValues).toHaveBeenCalledTimes(100)
  })
  it('缺少 Web Crypto 时仍可生成请求幂等键', () => {
    vi.stubGlobal('crypto', undefined)
    expect(requestKey()).toMatch(uuid)
    expect(requestKey()).not.toBe(requestKey())
  })
})
