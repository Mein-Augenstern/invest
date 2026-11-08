/** client 适配层：URL 拼装 / 401 清 token 回调 / 错误文案提取（mock fetch，jsdom 环境） */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, buildUrl, request } from '@/api/client'
import { clearToken, getToken, setToken } from '@/api/config'

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

beforeEach(() => {
  clearToken()
  vi.restoreAllMocks()
})

describe('buildUrl', () => {
  it('拼业务前缀 + 查询串', () => {
    expect(buildUrl('/trades', { limit: 100, instrument_id: 'a' })).toBe('/api/invest/trades?limit=100&instrument_id=a')
  })
  it('空/undefined 参数被过滤', () => {
    expect(buildUrl('/trades', { instrument_id: '', limit: undefined })).toBe('/api/invest/trades')
  })
})

describe('request', () => {
  it('携带 Bearer token', async () => {
    setToken('tk123')
    const fn = mockFetch(200, { ok: true })
    vi.stubGlobal('fetch', fn)
    await request({ url: '/ping' })
    const init = fn.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tk123')
  })

  it('错误体 {"error"} 透传为 ApiError.message', async () => {
    vi.stubGlobal('fetch', mockFetch(422, { error: '份额必须为正数' }))
    await expect(request({ url: '/trades', method: 'POST', data: {} })).rejects.toSatisfy((e: unknown) => {
      return e instanceof ApiError && e.status === 422 && e.message === '份额必须为正数'
    })
  })

  it('S10 AC-1：401 清 token 并触发 unauthorized 回调', async () => {
    setToken('expired')
    const hook = vi.fn()
    const { onUnauthorized } = await import('@/api/client')
    onUnauthorized(hook)
    vi.stubGlobal('fetch', mockFetch(401, { error: 'unauthorized' }))
    await expect(request({ url: '/overview' })).rejects.toBeInstanceOf(ApiError)
    expect(getToken()).toBe('')
    expect(hook).toHaveBeenCalledOnce()
  })

  it('网络异常 → status -1 的 ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    await expect(request({ url: '/ping' })).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === -1)
  })
})
