<template>
  <view class="error-card" v-if="visible">
    <view class="error-icon">
      <text class="icon-text">⚠️</text>
    </view>
    <text class="error-title">{{ title }}</text>
    <text class="error-desc">{{ description }}</text>
    <button
      class="retry-btn"
      size="mini"
      type="primary"
      :loading="loading"
      :disabled="loading"
      @tap="$emit('retry')"
    >
      {{ loading ? '重试中...' : '点击重试' }}
    </button>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  title?: string
  description?: string
  loading?: boolean
}>()

defineEmits<{
  (e: 'retry'): void
}>()
</script>

<style scoped>
.error-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80rpx 40rpx;
  background: #fff;
  border-radius: 16rpx;
  margin: 20rpx;
}
.error-icon {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  background: #fef2f2;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
}
.icon-text {
  font-size: 48rpx;
}
.error-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 12rpx;
}
.error-desc {
  font-size: 26rpx;
  color: #6b7280;
  margin-bottom: 32rpx;
  text-align: center;
}
.retry-btn {
  min-width: 200rpx;
}
</style>
