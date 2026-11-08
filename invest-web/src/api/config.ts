/**
 * PC 端鉴权存储：token 仅存浏览器 localStorage（S10 AC-8：产物不内置任何 token）。
 * 与小程序 config.ts 的区别：PC 端恒为同源直连，无服务器地址/网关模式配置。
 */
const TOKEN_KEY = 'invest_web_token'

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

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function hasToken(): boolean {
  return getToken().length > 0
}
