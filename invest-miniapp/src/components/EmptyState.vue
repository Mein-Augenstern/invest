<template>
  <view class="empty-state" v-if="visible">
    <view class="empty-icon">
      <text class="icon-text">📭</text>
    </view>
    <text class="empty-message">{{ message }}</text>
    <button
      v-if="actionText"
      class="action-btn"
      size="mini"
      type="primary"
      @tap="$emit('action')"
    >
      {{ actionText }}
    </button>
  </view>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  message: string
  actionText?: string
}>()

defineEmits<{
  (e: 'action'): void
}>()
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80rpx 40rpx;
  background: #fff;
  border-radius: 16rpx;
  margin: 20rpx;
}
.empty-icon {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24rpx;
}
.icon-text {
  font-size: 48rpx;
}
.empty-message {
  font-size: 28rpx;
  color: #6b7280;
  margin-bottom: 24rpx;
  text-align: center;
}
.action-btn {
  min-width: 200rpx;
}
</style>
