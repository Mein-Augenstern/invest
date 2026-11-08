<!--
  登录页（H5）：账号密码 → star 会员 JWT（经同源 /api/auth/login）。
  小程序端走 wx.login 静默登录，不经过本页；direct 调试模式也不经过本页。
-->
<script setup lang="ts">
import { ref } from 'vue'
import { loginByPassword } from '@/api/auth'
import { showApiError } from '@/api/client'
import { setMode } from '@/api/config'

const username = ref('')
const password = ref('')
const busy = ref(false)

async function submit() {
  if (busy.value) return
  if (!username.value.trim() || !password.value) {
    uni.showToast({ title: '请输入账号与密码', icon: 'none' })
    return
  }
  busy.value = true
  try {
    setMode('gateway')
    await loginByPassword(username.value.trim(), password.value)
    uni.showToast({ title: '登录成功', icon: 'success' })
    setTimeout(() => uni.reLaunch({ url: '/pages/overview/overview' }), 400)
  } catch (e) {
    showApiError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <view class="page">
    <view class="card login-card">
      <view class="title">invest 投研</view>
      <view class="muted sub">账号密码登录（star 会员）</view>
      <view class="form-row">
        <input v-model="username" class="input" placeholder="账号" :maxlength="32" />
      </view>
      <view class="form-row">
        <input
          v-model="password"
          class="input"
          password
          placeholder="密码"
          :maxlength="64"
          @confirm="submit"
        />
      </view>
      <button class="btn" :loading="busy" :disabled="busy" @tap="submit">登录</button>
      <view class="muted foot">微信端打开将自动登录，无需本页</view>
    </view>
  </view>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  background: #f5f6f7;
}
.login-card {
  width: 640rpx;
  margin: 0 auto;
  padding: 48rpx 40rpx;
}
.title {
  font-size: 40rpx;
  font-weight: 700;
}
.sub {
  font-size: 24rpx;
  margin: 8rpx 0 32rpx;
}
.form-row {
  margin-bottom: 24rpx;
}
.input {
  background: #f5f6f7;
  border: 1rpx solid #e5e6eb;
  border-radius: 10rpx;
  height: 84rpx;
  padding: 0 24rpx;
  font-size: 28rpx;
}
.btn {
  margin-top: 16rpx;
  background: #1652a8;
  color: #ffffff;
  border-radius: 10rpx;
  font-size: 30rpx;
}
.foot {
  font-size: 22rpx;
  margin-top: 24rpx;
  text-align: center;
}
</style>
