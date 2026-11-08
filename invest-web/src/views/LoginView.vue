<!--
  登录页（S11）：star 会员账号密码登录 + 注册。JWT 仅存本机浏览器。
-->
<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { errMsg } from '@/api/client'
import { registerAccount } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref(route.query.expired ? '登录已失效，请重新登录' : '')
const mode = ref<'login' | 'register'>('login')
const confirm = ref('')

async function submit() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    if (mode.value === 'register') {
      if (password.value !== confirm.value) throw new Error('两次输入的密码不一致')
      await registerAccount(username.value.trim(), password.value, username.value.trim())
      // 注册成功的经典后续：绿色提示 → 自动登录 → 进入产品
      ElMessage.success('注册成功，正在进入…')
    }
    await auth.login(username.value, password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/')
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="login-card panel">
      <div class="brand">
        <span class="brand-mark">iv</span>
        <div>
          <h1>invest 投研管理台</h1>
          <p class="muted">记账 · 统计 · 估值 · 纪律信号</p>
        </div>
      </div>
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" size="large" placeholder="账号" :prefix-icon="User" autofocus autocomplete="username" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            show-password
            size="large"
            placeholder="密码"
            :prefix-icon="Lock"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
          />
        </el-form-item>
        <el-form-item v-if="mode === 'register'">
          <el-input v-model="confirm" type="password" show-password size="large" placeholder="确认密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="err" />
        <el-button type="primary" size="large" class="submit" :loading="loading" native-type="submit">
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </el-button>
      </el-form>
      <div class="switch muted">
        <span v-if="mode === 'login'">
          还没有账号？
          <el-link type="primary" :underline="false" @click="mode = 'register'; error = ''">注册</el-link>
        </span>
        <span v-else>
          已有账号？
          <el-link type="primary" :underline="false" @click="mode = 'login'; error = ''">返回登录</el-link>
        </span>
      </div>
      <p class="hint muted">登录凭据仅保存在本机浏览器；微信端打开小程序将自动登录。</p>
    </div>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}
.login-card {
  width: 400px;
  padding: 36px 32px 28px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
}
.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--iv-primary);
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 18px;
  flex-shrink: 0;
}
.brand h1 {
  font-size: 20px;
  margin: 0 0 4px;
}
.brand p {
  margin: 0;
  font-size: 13px;
}
.err {
  margin-bottom: 16px;
}
.submit {
  width: 100%;
}
.switch {
  margin-top: 14px;
  text-align: center;
  font-size: 13px;
}
.hint {
  margin: 14px 0 0;
  font-size: 12px;
  text-align: center;
}
</style>
