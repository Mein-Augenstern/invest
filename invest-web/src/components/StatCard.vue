<!--
  指标卡：标签 + 主数值 + 副信息；tone 用于盈亏着色（danger=红涨 / success=绿跌）。
-->
<script setup lang="ts">
defineProps<{ label: string; value: string; sub?: string; tone?: string }>()
</script>

<template>
  <div class="stat panel">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value num" :class="tone">{{ value }}</div>
    <div v-if="sub" class="stat-sub">
      <slot name="sub">{{ sub }}</slot>
    </div>
  </div>
</template>

<style scoped>
.stat {
  padding: 16px 20px;
}
.stat-label {
  color: var(--iv-text-3);
  font-size: 13px;
}
.stat-value {
  font-size: 26px;
  font-weight: 600;
  margin-top: 6px;
  line-height: 1.2;
}
.stat-sub {
  margin-top: 6px;
  color: var(--iv-text-3);
  font-size: 12px;
}
</style>
