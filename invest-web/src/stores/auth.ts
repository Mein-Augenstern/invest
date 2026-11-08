/**
 * 鉴权状态（S11）：star 会员账密登录 → JWT 存本机 localStorage。
 * 校验用需鉴权的轻量端点（/pull/status，无副作用——/overview 会触发后台拉数）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, errMsg } from '@/api/client'
import { loginByPassword } from '@/api/auth'
import { clearToken, getMember, getToken, setMember, setToken, type StoredMember } from '@/api/config'
import { getPullStatus } from '@/api/invest'

export const useAuthStore = defineStore('auth', () => {
  const authed = ref(getToken().length > 0)
  const member = ref<StoredMember | null>(getMember())

  async function login(username: string, password: string): Promise<void> {
    if (!username.trim() || !password) throw new ApiError(0, '请输入账号与密码')
    const vo = await loginByPassword(username.trim(), password)
    setToken(vo.token)
    setMember({ id: vo.member.id, username: vo.member.username, nickname: vo.member.nickname })
    try {
      await getPullStatus()
      authed.value = true
      member.value = getMember()
    } catch (e) {
      clearToken()
      authed.value = false
      if (e instanceof ApiError && e.status === 401) throw new ApiError(401, '登录成功但服务校验失败，请稍后重试')
      throw e
    }
  }

  function logout(): void {
    clearToken()
    authed.value = false
    member.value = null
  }

  /** client 收到 401 时同步状态（token 已被 client 清除） */
  function markExpired(): void {
    authed.value = false
  }

  return { authed, member, login, logout, markExpired, errMsg }
})
