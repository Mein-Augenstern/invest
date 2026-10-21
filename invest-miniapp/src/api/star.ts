/**
 * star 平台服务直连（L4 提醒集成）：family 成员 + reminder 用户规则。
 * 前端直连 star 网关（复用统一 JWT），invest 后端不包一层——基础设施复用的最直接形态。
 */
import { request } from './client'

export interface FamilyMember {
  id: number
  name: string
  relation?: string
  [k: string]: unknown
}

export interface ReminderRule {
  id: number
  familyMemberId: number
  title: string
  firstRemindAt: string
  repeatType: 'NONE' | 'WEEKLY' | 'MONTHLY' | 'ANNUAL'
  repeatUntil?: string | null
  [k: string]: unknown
}

/** star 响应壳 {code, message, data} 解包 */
function unwrap<T>(d: { data?: T } & T): T {
  return (d.data ?? d) as T
}

export async function listFamilyMembers(): Promise<FamilyMember[]> {
  const raw = await request<{ data?: FamilyMember[] } & FamilyMember[]>({ url: '/api/family/members', rawPath: true })
  const list = unwrap<FamilyMember[]>(raw as never)
  return Array.isArray(list) ? list : []
}

export async function listReminderRules(): Promise<ReminderRule[]> {
  const raw = await request<{ data?: ReminderRule[] } & ReminderRule[]>({ url: '/api/reminder/rules', rawPath: true })
  const list = unwrap<ReminderRule[]>(raw as never)
  return Array.isArray(list) ? list : []
}

export function createReminderRule(payload: {
  familyMemberId: number
  title: string
  firstRemindAt: string
  repeatType: 'NONE' | 'WEEKLY' | 'MONTHLY' | 'ANNUAL'
}): Promise<ReminderRule> {
  return request({
    url: '/api/reminder/rules',
    method: 'POST',
    data: payload,
    rawPath: true,
  })
}

export function deleteReminderRule(id: number): Promise<void> {
  return request({ url: `/api/reminder/rules/${id}`, method: 'DELETE', rawPath: true })
}

/** invest 预设提醒标题前缀（列表过滤用） */
export const INVEST_RULE_PREFIX = '[投资]'
