/** 接入配置：双模式（P13 star 集成）
 * - gateway（默认）：star 网关 + 微信登录（wx-login → star JWT），业务走 /api/invest/**
 * - direct：本机直连 invest 服务（LAN + 静态令牌）
 * storage 键一律 invest_ 前缀，与其它小程序项目隔离
 *
 * 构建期默认值（G2 公网化）：.env.production.local 的 VITE_INVEST_PUBLIC_*（gitignore，
 * 不入库）经 import.meta.env 注入——体验版用户免配置首开即连公网；设置页改动仍以
 * storage 为最高优先（覆盖链 storage > 构建期默认 > 内置缺省）。 */

const SERVER_KEY = 'invest_server' // gateway=网关地址(:8080)；direct=invest 地址(:8790)
const TOKEN_KEY = 'invest_token' // gateway=star JWT；direct=LAN 静态令牌
const MODE_KEY = 'invest_auth_mode' // 'gateway' | 'direct'
const MEMBER_KEY = 'invest_member' // gateway 模式登录后的成员信息（JSON）

/** 构建期公网默认值（VITE_INVEST_PUBLIC_*，本地 .env.production.local 提供；未定义为空串） */
const ENV_SERVER: string = (import.meta.env.VITE_INVEST_PUBLIC_SERVER as string | undefined) ?? ''
const ENV_MODE: string = (import.meta.env.VITE_INVEST_PUBLIC_MODE as string | undefined) ?? ''
const ENV_TOKEN: string = (import.meta.env.VITE_INVEST_PUBLIC_TOKEN as string | undefined) ?? ''

export type AuthMode = 'gateway' | 'direct'

export function getMode(): AuthMode {
  const v = uni.getStorageSync(MODE_KEY)
  if (v === 'direct' || v === 'gateway') {
    return v
  }
  // storage 未设置：采用构建期默认（体验版直连公网场景）；无默认则 gateway
  return ENV_MODE === 'direct' ? 'direct' : 'gateway'
}

export function setMode(v: AuthMode) {
  uni.setStorageSync(MODE_KEY, v)
}

export function getServer(): string {
  return uni.getStorageSync(SERVER_KEY) || ENV_SERVER
}

export function setServer(v: string) {
  uni.setStorageSync(SERVER_KEY, v.trim().replace(/\/$/, ''))
}

export function getToken(): string {
  return uni.getStorageSync(TOKEN_KEY) || ENV_TOKEN
}

export function setToken(v: string) {
  uni.setStorageSync(TOKEN_KEY, v.trim())
}

export function clearToken() {
  uni.removeStorageSync(TOKEN_KEY)
}

export interface StarMember {
  id?: number
  username?: string
  nickname?: string
  [k: string]: unknown
}

export function getMember(): StarMember | null {
  try {
    const raw = uni.getStorageSync(MEMBER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setMember(m: StarMember) {
  uni.setStorageSync(MEMBER_KEY, JSON.stringify(m))
}
