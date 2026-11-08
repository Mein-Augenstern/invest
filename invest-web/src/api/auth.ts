/**
 * star 会员认证（S11）：经同源 /api/auth/**（nginx → star 网关 → member 服务）。
 * 响应为 star 网关统一壳 {code, message, data}；code !== 0 视为失败。
 */
import { ApiError, request } from './client'

export interface StarMember {
  id: number
  username?: string
  nickname?: string
  avatar?: string
  [k: string]: unknown
}

interface LoginVO {
  token: string
  expiresIn?: number
  member: StarMember
}

interface StarEnvelope<T> {
  code: number
  message?: string
  data?: T
}

async function unwrap<T>(p: Promise<StarEnvelope<T>>): Promise<T> {
  const res = await p
  if (res.code !== 0 || !res.data) throw new ApiError(res.code || -1, res.message || '登录服务异常')
  return res.data
}

export function loginByPassword(username: string, password: string): Promise<LoginVO> {
  return unwrap(
    request<StarEnvelope<LoginVO>>({ url: '/api/auth/login', method: 'POST', data: { username, password }, rawPath: true, timeoutMs: 15_000 }),
  )
}

export async function registerAccount(username: string, password: string, nickname?: string): Promise<void> {
  await unwrap(
    request<StarEnvelope<null>>({ url: '/api/auth/register', method: 'POST', data: { username, password, nickname }, rawPath: true, timeoutMs: 15_000 }),
  )
}
