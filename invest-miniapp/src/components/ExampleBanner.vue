<template>
  <view class="example-banner" v-if="visible" @tap="goToInstruments">
    <text class="banner-icon">⚠️</text>
    <text class="banner-text">当前展示示例数据</text>
    <text class="banner-action">点击配置 →</text>
  </view>
</template>

<script setup lang="ts">
defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'navigate', page: string): void
}>()
const goToInstruments = () => emit('navigate', '/pages/instruments/instruments')
</script>

<style scoped>
.example-banner {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 16rpx 24rpx;
  margin: 16rpx 20rpx 0;
  background: #fff8e1;
  border: 1rpx solid #ffe082;
  border-radius: 12rpx;
}
.banner-icon {
  font-size: 28rpx;
}
.banner-text {
  flex: 1;
  font-size: 26rpx;
  color: #f57f17;
}
.banner-action {
  font-size: 26rpx;
  color: #1565c0;
  font-weight: 600;
}
</style>
