<template>
  <view class="onboarding-overlay" v-if="visible">
    <swiper class="onboarding-swiper" :current="step" @change="onStepChange" :indicator-dots="true" indicator-color="rgba(255,255,255,0.3)" indicator-active-color="#388bfd">
      <!-- Step 1: 配置服务器 -->
      <swiper-item>
        <view class="onboarding-card">
          <text class="step-badge">1 / 3</text>
          <text class="step-icon">🌐</text>
          <text class="step-title">配置服务器</text>
          <text class="step-desc">连接到你的投资数据后端</text>
          <view class="server-preview" v-if="defaultServer">
            <text class="server-label">默认服务器</text>
            <text class="server-url">{{ defaultServer }}</text>
          </view>
          <button class="step-btn" type="primary" @tap="useDefaultServer" v-if="defaultServer">使用默认</button>
          <button class="step-btn" plain @tap="goToSettings">手动配置</button>
        </view>
      </swiper-item>

      <!-- Step 2: 登录 -->
      <swiper-item>
        <view class="onboarding-card">
          <text class="step-badge">2 / 3</text>
          <text class="step-icon">🔐</text>
          <text class="step-title">登录</text>
          <text class="step-desc">{{ modeText }}</text>
          <button class="step-btn" type="primary" @tap="tryLogin">{{ loginBtnText }}</button>
          <text class="skip-hint" @tap="skipLogin">跳过此步</text>
        </view>
      </swiper-item>

      <!-- Step 3: 记第一笔 -->
      <swiper-item>
        <view class="onboarding-card">
          <text class="step-badge">3 / 3</text>
          <text class="step-icon">📝</text>
          <text class="step-title">记第一笔投资</text>
          <text class="step-desc">录入你的第一笔交易，开始跟踪收益</text>
          <button class="step-btn" type="primary" @tap="goToTrades">开始记账</button>
          <button class="step-btn" plain @tap="finishOnboarding">稍后再说</button>
        </view>
      </swiper-item>
    </swiper>
    <text class="skip-all" @tap="finishOnboarding">跳过引导</text>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { getMode, getServer, setOnboarded, hasServer } from '@/api/config'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'navigate', page: string): void
}>()

const step = ref(0)
const defaultServer = ref('')
const mode = ref<'gateway' | 'direct'>('gateway')

// 从构建时注入的默认值读取
const envServer = (import.meta as any).env?.VITE_INVEST_PUBLIC_SERVER || ''
defaultServer.value = envServer
mode.value = ((import.meta as any).env?.VITE_INVEST_PUBLIC_MODE === 'direct' ? 'direct' : 'gateway')

const modeText = computed(() =>
  mode.value === 'gateway' ? '通过微信静默登录（推荐）' : '输入访问令牌连接后端'
)
const loginBtnText = computed(() =>
  mode.value === 'gateway' ? '微信一键登录' : '输入令牌'
)

const onStepChange = (e: any) => { step.value = e.detail.current }

const useDefaultServer = () => {
  // 构建时已有默认值，直接进入下一步
  step.value = 1
}

const goToSettings = () => {
  emit('navigate', '/pages/settings/settings')
  finishOnboarding()
}

const tryLogin = () => {
  if (mode.value === 'gateway') {
    // gateway 模式下 app.ts 已有自动登录逻辑
    emit('close')
  } else {
    // direct 模式跳转设置页输令牌
    emit('navigate', '/pages/settings/settings')
  }
  finishOnboarding()
}

const skipLogin = () => { step.value = 2 }

const goToTrades = () => {
  emit('navigate', '/pages/trades/trades')
  finishOnboarding()
}

const finishOnboarding = () => {
  setOnboarded()
  emit('close')
}
</script>

<style scoped>
.onboarding-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.onboarding-swiper {
  width: 100%;
  height: 700rpx;
}
.onboarding-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60rpx 40rpx;
  margin: 0 40rpx;
  background: #161b22;
  border-radius: 20rpx;
  border: 1px solid #30363d;
}
.step-badge {
  position: absolute;
  top: 24rpx;
  right: 24rpx;
  font-size: 24rpx;
  color: #8b949e;
}
.step-icon {
  font-size: 80rpx;
  margin-bottom: 30rpx;
}
.step-title {
  font-size: 40rpx;
  font-weight: bold;
  color: #f0f6fc;
  margin-bottom: 16rpx;
}
.step-desc {
  font-size: 28rpx;
  color: #8b949e;
  margin-bottom: 40rpx;
  text-align: center;
}
.server-preview {
  width: 100%;
  padding: 20rpx;
  background: #0d1117;
  border-radius: 12rpx;
  margin-bottom: 24rpx;
}
.server-label {
  font-size: 24rpx;
  color: #8b949e;
  display: block;
  margin-bottom: 8rpx;
}
.server-url {
  font-size: 26rpx;
  color: #58a6ff;
  word-break: break-all;
}
.step-btn {
  width: 100%;
  margin-bottom: 16rpx;
}
.skip-hint {
  font-size: 26rpx;
  color: #8b949e;
  margin-top: 10rpx;
}
.skip-all {
  position: absolute;
  bottom: 60rpx;
  font-size: 28rpx;
  color: #8b949e;
}
</style>
