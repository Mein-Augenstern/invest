/**
 * PC 端鉴权存储：token 仅存浏览器 localStorage（S10 AC-8：产物不内置任何 token）。
 * 与小程序 config.ts 的区别：PC 端恒为同源直连，无服务器地址/网关模式配置。
 */
const TOKEN_KEY = 'invest_web_token'
const MEMBER_KEY = 'invest_web_member'

export interface StoredMember {
  id: number
  username?: string
  nickname?: string
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token.trim())
}

export function getMember(): StoredMember | null {
  try {
    const raw = localStorage.getItem(MEMBER_KEY)
    return raw ? (JSON.parse(raw) as StoredMember) : null
  } catch {
    return null
  }
}

export function setMember(m: StoredMember): void {
  localStorage.setItem(MEMBER_KEY, JSON.stringify(m))
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(MEMBER_KEY)
}

export function hasToken(): boolean {
  return getToken().length > 0
}
