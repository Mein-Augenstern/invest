/**
 * 统一请求封装：uni.request 包装为 Promise。
 * - 双模式：gateway=star 网关（/api/invest/**，star JWT）；direct=本机直连（LAN 令牌）
 * - 401 自愈（gateway 模式）：清 token → 复用 auth 的单飞静默重登 → 重试一次；
 *   登录端点自身豁免（防 hook 等待自己的死锁），direct 模式豁免（静态令牌重试无意义）
 * - H5 端经 vite 代理 /api；小程序端直连完整地址
 */
import { getToken, getServer, getMode, clearToken } from './config'

// 业务前缀两模式一致（后端路由对齐 star 网关规范 /api/<域>/**）
export const BASE_PATH = '/api/invest'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** 401 自愈钩子由 auth.ts 注册（避免 client↔auth 循环依赖；未注册时退化为直接抛错） */
type ReloginHook = () => Promise<boolean>
let reloginHook: ReloginHook | null = null
export function registerRelogin(hook: ReloginHook) {
  reloginHook = hook
}

interface RawResp {
  status: number
  body: unknown
}

function rawRequest(url: string, method: 'GET' | 'POST' | 'DELETE', data: unknown): Promise<RawResp> {
  const header: Record<string, string> = { 'content-type': 'application/json' }
  const token = getToken()
  if (token) header.Authorization = `Bearer ${token}`
  return new Promise((resolve, reject) => {
    uni.request({
      url,
      method,
      data,
      header,
      success: (res) => resolve({ status: res.statusCode, body: res.data }),
      fail: (e) => reject(new ApiError(-1, `网络错误：${e.errMsg || '无法连接服务器'}`)),
    })
  })
}

export async function request<T = unknown>(opts: {
  url: string
  method?: 'GET' | 'POST' | 'DELETE'
  data?: unknown
  params?: Record<string, string | number>
  rawPath?: boolean // true=url 为网关完整路径（如 /api/auth/**），不拼 invest 业务前缀
}): Promise<T> {
  const server = getServer()
  if (!server) {
    throw new ApiError(0, '未配置服务器地址，请到设置页填写')
  }
  let url = `${server.replace(/\/$/, '')}${opts.rawPath ? '' : BASE_PATH}${opts.url}`
  const params = opts.params
  if (params) {
    const qs = Object.entries(params)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&')
    if (qs) url += `?${qs}`
  }
  const method = opts.method || 'GET'
  // 登录链路自身走网关裸路径，401 不能再触发重登（hook 会等待自己，死锁）
  const isAuthPath = !!opts.rawPath && opts.url.startsWith('/api/auth/')

  let res = await rawRequest(url, method, opts.data)
  if (res.status === 401 && !isAuthPath && getMode() === 'gateway' && reloginHook) {
    clearToken()
    const ok = await reloginHook()
    if (ok) res = await rawRequest(url, method, opts.data)
  }

  if (res.status >= 200 && res.status < 300) {
    return res.body as T
  }
  if (res.status === 401) {
    throw new ApiError(401, '登录已过期，请到设置页重新登录')
  }
  const msg =
    ((res.body as { error?: string } | null)?.error || (res.body as { message?: string } | null)?.message) ||
    `请求失败（HTTP ${res.status}）`
  throw new ApiError(res.status, msg)
}

export function showApiError(e: unknown) {
  const msg = e instanceof Error ? e.message : String(e)
  uni.showToast({ title: msg, icon: 'none', duration: 2500 })
}
