<!--
  登录页（S10 AC-1）：输入 token → 校验 → 回跳原路由。token 仅存本机浏览器。
-->
<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock } from '@element-plus/icons-vue'
import { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const token = ref('')
const loading = ref(false)
const error = ref(route.query.expired ? '登录已失效，请重新输入 token' : '')

async function submit() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    await auth.login(token.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    // 仅允许站内相对路径回跳，防开放重定向
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
          <h1>invest 个人投研台</h1>
          <p class="muted">记账 · 统计 · 估值 · 纪律信号</p>
        </div>
      </div>
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input
            v-model="token"
            type="password"
            show-password
            size="large"
            placeholder="访问 token"
            :prefix-icon="Lock"
            autocomplete="current-password"
            autofocus
          />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="err" />
        <el-button type="primary" size="large" class="submit" :loading="loading" native-type="submit">
          进入
        </el-button>
      </el-form>
      <p class="hint muted">token 仅保存在本机浏览器，退出登录即清除。</p>
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
.hint {
  margin: 16px 0 0;
  font-size: 12px;
  text-align: center;
}
</style>
