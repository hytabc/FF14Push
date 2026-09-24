import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => vi.unstubAllGlobals())

async function freshModule() {
  vi.resetModules()
  return await import('./device')
}

describe('device fingerprint', () => {
  it('返回稳定且非空的设备标识', async () => {
    const { getDeviceId } = await freshModule()
    const id = getDeviceId()
    expect(id).toMatch(/^fp-[0-9a-f]{16}$/)
    expect(getDeviceId()).toBe(id)
  })

  it('不同设备信号得到不同标识', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'UA-A',
      language: 'zh-CN',
      platform: 'Win32',
      hardwareConcurrency: 8,
    })
    const a = (await freshModule()).getDeviceId()

    vi.stubGlobal('navigator', {
      userAgent: 'UA-B',
      language: 'en-US',
      platform: 'MacIntel',
      hardwareConcurrency: 4,
    })
    const b = (await freshModule()).getDeviceId()

    expect(a).not.toBe(b)
  })

  it('localStorage 不可用时仍返回标识', async () => {
    vi.stubGlobal('localStorage', undefined)
    const { getDeviceId } = await freshModule()
    expect(getDeviceId()).toMatch(/^fp-/)
  })
})
