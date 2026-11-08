/** S11 注册/登录解包回归：星壳只看 code，data:null 是合法成功（红色「成功」bug 的锚） */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import { loginByPassword, registerAccount } from '@/api/auth'

function mockStar(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('星壳解包', () => {
  it('注册成功（code=0, data=null）不抛错——红色「成功」回归锚', async () => {
    vi.stubGlobal('fetch', mockStar(200, { code: 0, message: '成功', data: null }))
    await expect(registerAccount('u', 'p')).resolves.toBeUndefined()
  })

  it('注册失败（code≠0）抛 ApiError 且透传 message', async () => {
    vi.stubGlobal('fetch', mockStar(200, { code: 4003, message: '用户名已存在', data: null }))
    await expect(registerAccount('u', 'p')).rejects.toSatisfy((e: unknown) =>
      e instanceof ApiError && e.message === '用户名已存在')
  })

  it('登录成功取到 token；data 缺 token 视为服务异常', async () => {
    vi.stubGlobal('fetch', mockStar(200, { code: 0, message: '成功', data: { token: 'jwt-x', member: { id: 1 } } }))
    const vo = await loginByPassword('u', 'p')
    expect(vo.token).toBe('jwt-x')

    vi.stubGlobal('fetch', mockStar(200, { code: 0, message: '成功', data: null }))
    await expect(loginByPassword('u', 'p')).rejects.toSatisfy((e: unknown) =>
      e instanceof ApiError && /缺少 token/.test(e.message))
  })
})
