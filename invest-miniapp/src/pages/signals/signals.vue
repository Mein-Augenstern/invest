<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { getSignals, setSignalStatus } from '@/api/invest'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import type { Signal } from '@/types'

const signals = ref<Signal[]>([])
const loading = ref(false)
const evaluating = ref(false)

async function onEvaluate() {
  if (evaluating.value) return
  evaluating.value = true
  try {
    const d = await request<{ new: number }>({ url: '/signals/evaluate', method: 'POST' })
    uni.showToast({ title: `评估完成（新增 ${d.new} 条）`, icon: 'none' })
    load()
  } catch (e) {
    showApiError(e)
  } finally {
    evaluating.value = false
  }
}

async function load() {
  loading.value = true
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用）
    signals.value = (await getSignals()).signals
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

async function onStatus(s: Signal, status: '已确认' | '已忽略') {
  try {
    await setSignalStatus(s.id, status)
    s.status = status
    uni.showToast({ title: `已${status}`, icon: 'success' })
  } catch (e) {
    showApiError(e)
  }
}

function onOpenDiary() {
  uni.navigateTo({ url: '/pages/diary/diary' })
}

onShow(load)
</script>

<template>
  <view class="page">
    <view class="card note">
      信号是纪律工具而非收益保证（章程红线）。口径与规则见 docs/business/strategy-rules.md。
      <text class="diary-link" @tap="onOpenDiary">投资日记 ›</text>
      <text class="eval-link" @tap="onEvaluate">{{ evaluating ? '评估中…' : '立即评估' }}</text>
    </view>

    <view v-if="!signals.length && !loading" class="card empty">暂无信号。可在本机执行 invest signals 评估，或等待每日 cron。</view>

    <view v-for="s in signals" :key="s.id" class="card sig-card">
      <view class="sig-head">
        <view class="pos-main">
          <view class="sig-title">{{ s.instrument }}</view>
          <view class="muted sig-sub">{{ s.date }} · {{ s.rule }}</view>
        </view>
        <text class="sig-status" :class="{ active: s.status === '建议' }">{{ s.status }}</text>
      </view>
      <view class="sig-body">
        <view class="sig-line"><text class="muted">依据</text>{{ s.metric }} = {{ s.value }}</view>
        <view class="sig-line"><text class="muted">建议</text>{{ s.action }}</view>
      </view>
      <view v-if="s.status === '建议'" class="sig-actions">
        <button class="mini-btn" @tap="onStatus(s, '已忽略')">忽略</button>
        <button class="mini-btn primary" @tap="onStatus(s, '已确认')">确认</button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.note {
  color: #86909c;
  font-size: 24rpx;
}
.diary-link {
  color: #1652a8;
  margin-left: 12rpx;
}
.eval-link {
  color: #1652a8;
  float: right;
}
.sig-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.sig-title {
  font-size: 30rpx;
  font-weight: 500;
}
.sig-sub {
  font-size: 24rpx;
  margin-top: 6rpx;
}
.sig-status {
  font-size: 24rpx;
  color: #86909c;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.sig-status.active {
  color: #d46b08;
}
.sig-body {
  margin-top: 16rpx;
  border-top: 1rpx solid #f0f1f3;
  padding-top: 16rpx;
}
.sig-line {
  font-size: 26rpx;
  line-height: 1.8;
  display: flex;
  gap: 16rpx;
}
.sig-line .muted {
  width: 64rpx;
  flex-shrink: 0;
}
.sig-actions {
  display: flex;
  gap: 20rpx;
  margin-top: 20rpx;
}
.mini-btn {
  flex: 1;
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #1d2129;
  font-size: 26rpx;
  line-height: 2.2;
  padding: 0;
}
.mini-btn.primary {
  background: #1652a8;
  border-color: #1652a8;
  color: #ffffff;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
</style>
