/**
 * star 平台登录（gateway 模式）：wx.login code → star 网关 /api/auth/wx-login → star JWT。
 * 直连 direct 模式不用本模块（LAN 静态令牌由设置页配置）。
 * 登录链路与 star-site-app 对齐（auth.ts），storage 键隔离。
 *
 * 时序设计（教训：登录与首拉并发 → 首拉 401 → 重试链在异步嵌套中丢失）：
 * - silentWxLogin 单飞：并发调用共享同一个 in-flight promise，只真实登录一次；
 * - ensureLogin：页面首拉前 await（App.onLaunch 已发起的登录直接复用），带超时兜底。
 */
import { request, ApiError, registerRelogin } from './client'
import { getMode, getToken, setToken, setMember, getMember } from './config'

interface LoginVO {
  token: string
  member: { id?: number; username?: string; nickname?: string }
}

function wxLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    uni.login({
      provider: 'weixin',
      success: (r) => resolve(r.code),
      fail: (e) => reject(new ApiError(-1, e.errMsg || 'wx.login 失败')),
    })
  })
}

let inflight: Promise<boolean> | null = null

async function doLogin(): Promise<boolean> {
  try {
    const code = await wxLoginCode()
    // star 网关统一响应壳 {code, message, data:{token, member}}（与 invest 裸 JSON 不同）
    const res = await request<{ data?: LoginVO } & LoginVO>({
      url: '/api/auth/wx-login', method: 'POST', data: { code }, rawPath: true,
    })
    const vo = res.data ?? res
    if (!vo || !vo.token) throw new ApiError(-1, '登录响应缺少 token')
    setToken(vo.token)
    setMember(vo.member)
    return true
  } catch (e) {
    console.warn('[invest] login FAIL:', e instanceof Error ? e.message : e)
    uni.setStorageSync('invest_last_login_error', e instanceof Error ? e.message : String(e))
    return false
  }
}

/** 微信静默登录（单飞）：已登录直接 true；并发调用共享同一次登录。 */
export function silentWxLogin(): Promise<boolean> {
  if (getMode() !== 'gateway') return Promise.resolve(true)
  if (getToken()) return Promise.resolve(true)
  if (!inflight) {
    inflight = doLogin().finally(() => {
      inflight = null
    })
  }
  return inflight
}

/** 页面首拉前等待登录完成（最多 timeoutMs；登录失败/超时放行，由请求层 401 兜底提示）。 */
export async function ensureLogin(timeoutMs = 8000): Promise<boolean> {
  if (getMode() !== 'gateway' || getToken()) return true
  const login = silentWxLogin()
  const timeout = new Promise<boolean>((resolve) => setTimeout(() => resolve(false), timeoutMs))
  return Promise.race([login, timeout])
}

/** 账号密码登录（H5 调试后备；生产小程序端走静默 wx.login）。 */
export async function loginByPassword(username: string, password: string): Promise<boolean> {
  const res = await request<{ data?: LoginVO } & LoginVO>({
    url: '/api/auth/login', method: 'POST', data: { username, password }, rawPath: true,
  })
  const vo = res.data ?? res
  if (!vo || !vo.token) throw new ApiError(-1, '登录响应缺少 token')
  setToken(vo.token)
  setMember(vo.member)
  return true
}

// 401 自愈钩子：client 收到 401 时已清空 token，silentWxLogin 会真实走一次登录（单飞，
// 多请求并发 401 共享同一次重登），随后 client 用新 token 重试原请求一次
registerRelogin(() => silentWxLogin())

export function isLoggedIn(): boolean {
  return getMode() === 'direct' || !!getToken()
}

export function memberLabel(): string {
  const m = getMember()
  if (!m) return ''
  return String(m.nickname || m.username || `成员${m.id ?? ''}`)
}
