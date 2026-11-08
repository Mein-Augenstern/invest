/**
 * star 会员资料（S11 完整账号功能）：经同源 /api/member/**（nginx → star 网关 → member 服务）。
 * 方法用 PUT（后端 MemberController @PutMapping）。
 */
import { ApiError, request } from './client'
import type { StarEnvelope } from './auth'

export interface MemberProfile {
  id: number
  username?: string
  nickname?: string
  avatar?: string
  email?: string
  phone?: string
  gender?: number
  bio?: string
  createdAt?: string
}

async function unwrap<T>(p: Promise<StarEnvelope<T>>): Promise<T | null> {
  const res = await p
  if (res.code !== 0) throw new ApiError(res.code || -1, res.message || '会员服务异常')
  return res.data ?? null
}

export async function getProfile(): Promise<MemberProfile> {
  const p = await unwrap(request<StarEnvelope<MemberProfile>>({ url: '/api/member/me', rawPath: true, timeoutMs: 10_000 }))
  if (!p || !p.id) throw new ApiError(-1, '获取会员信息失败')
  return p
}

export async function updateProfile(data: Partial<Pick<MemberProfile, 'nickname' | 'bio'>>): Promise<MemberProfile | null> {
  return unwrap(
    request<StarEnvelope<MemberProfile>>({ url: '/api/member/me', method: 'PUT', data, rawPath: true, timeoutMs: 10_000 }),
  )
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await unwrap(
    request<StarEnvelope<null>>({
      url: '/api/member/me/password',
      method: 'PUT',
      data: { oldPassword, newPassword },
      rawPath: true,
      timeoutMs: 10_000,
    }),
  )
}
