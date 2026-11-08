/**
 * 鉴权状态（S10 AC-1）：token 输入 → 以需鉴权的轻量端点校验 → 持久化。
 * 校验选 /pull/status 而非 /overview：后者会在数据过期时触发后台自动拉数（副作用）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError } from '@/api/client'
import { clearToken, getToken, setToken } from '@/api/config'
import { getPullStatus } from '@/api/invest'

export const useAuthStore = defineStore('auth', () => {
  const authed = ref(getToken().length > 0)

  async function login(token: string): Promise<void> {
    const t = token.trim()
    if (!t) throw new ApiError(0, '请输入 token')
    setToken(t)
    try {
      await getPullStatus()
      authed.value = true
    } catch (e) {
      clearToken()
      authed.value = false
      if (e instanceof ApiError && e.status === 401) throw new ApiError(401, 'token 无效，请核对后重试')
      throw e
    }
  }

  function logout(): void {
    clearToken()
    authed.value = false
  }

  /** client 收到 401 时同步状态（token 已被 client 清除） */
  function markExpired(): void {
    authed.value = false
  }

  return { authed, login, logout, markExpired }
})
