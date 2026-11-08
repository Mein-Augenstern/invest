/**
 * 统一请求封装（PC 端）：fetch + 超时，搬运自 invest-miniapp/src/api/client.ts 的契约。
 * - 恒为同源相对路径：开发期 vite 代理 /api，生产期 Cloudflare Pages _redirects 同 zone 代理（S10 AC-2）
 * - 401：清 token 并触发 unauthorized 钩子（路由层跳登录页，S10 AC-1）
 * - 错误语义沿用后端 {"error": "..."}，保证提示文案与小程序一致
 */
import { clearToken, getToken } from './config'

export const BASE_PATH = '/api/invest'

/**
 * API 基地址：缺省同源相对路径（开发期 vite 代理 / 生产期同域反代）。
 * S10 过渡形态（无自有域名）：VITE_API_BASE 指向 trycloudflare 隧道 HTTPS 地址，
 * 前端 pages.dev 与 API 跨域，靠后端 INVEST_ALLOWED_ORIGINS 单点放行。
 */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || ''

const DEFAULT_TIMEOUT_MS = 20_000

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** 401 钩子由 router 注册（避免 client ↔ router 循环依赖） */
type UnauthorizedHook = () => void
let unauthorizedHook: UnauthorizedHook | null = null
export function onUnauthorized(hook: UnauthorizedHook): void {
  unauthorizedHook = hook
}

type Method = 'GET' | 'POST' | 'DELETE'

export interface RequestOptions {
  url: string
  method?: Method
  data?: unknown
  params?: Record<string, string | number | undefined>
  timeoutMs?: number
  /** true = url 为网关完整路径（如 /api/auth/**），不拼 invest 业务前缀 */
  rawPath?: boolean
}

export function buildUrl(url: string, params?: RequestOptions['params'], rawPath = false): string {
  let full = rawPath ? url : `${API_BASE}${BASE_PATH}${url}`
  if (params) {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join('&')
    if (qs) full += `?${qs}`
  }
  return full
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function errorFrom(res: Response): Promise<ApiError> {
  if (res.status === 401) {
    clearToken()
    unauthorizedHook?.()
    return new ApiError(401, '登录已失效，请重新输入 token')
  }
  let msg = `请求失败（HTTP ${res.status}）`
  try {
    const body = (await res.json()) as { error?: string; message?: string } | null
    msg = body?.error || body?.message || msg
  } catch {
    /* 非 JSON 错误体（如网关 502 HTML）保留通用文案 */
  }
  return new ApiError(res.status, msg)
}

async function send(input: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    return await fetch(input, { ...init, signal: ctrl.signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw new ApiError(-1, '请求超时，请稍后重试')
    throw new ApiError(-1, '网络错误：无法连接服务器')
  } finally {
    clearTimeout(timer)
  }
}

export async function request<T = unknown>(opts: RequestOptions): Promise<T> {
  const method = opts.method || 'GET'
  const headers: Record<string, string> = { ...authHeaders() }
  let body: string | undefined
  if (opts.data !== undefined) {
    headers['content-type'] = 'application/json'
    body = JSON.stringify(opts.data)
  }
  const res = await send(buildUrl(opts.url, opts.params, opts.rawPath ?? false), { method, headers, body }, opts.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

/** multipart 上传（OCR / 截图解析）：字段名与后端约定为 file */
export async function upload<T = unknown>(url: string, file: File, timeoutMs = 60_000): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  const res = await send(buildUrl(url), { method: 'POST', headers: authHeaders(), body: form }, timeoutMs)
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

/** 二进制下载（备份导出）：需携带 Bearer，故不能用裸链接，取 blob 后触发浏览器保存 */
export async function download(url: string, fallbackName: string, timeoutMs = 120_000): Promise<void> {
  const res = await send(buildUrl(url), { method: 'GET', headers: authHeaders() }, timeoutMs)
  if (!res.ok) throw await errorFrom(res)
  const disposition = res.headers.get('content-disposition') || ''
  const matched = /filename="?([^";]+)"?/.exec(disposition)
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = matched?.[1] || fallbackName
  a.click()
  URL.revokeObjectURL(href)
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
