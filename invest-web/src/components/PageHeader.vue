<!--
  统一页头：标题 + 说明 + 标签位（tags）+ 右侧操作区（actions）。每个视图顶部使用。
-->
<script setup lang="ts">
defineProps<{ title: string; desc?: string }>()
</script>

<template>
  <div class="page-header">
    <div class="ph-left">
      <h1 class="ph-title">
        {{ title }}
        <span class="ph-tags"><slot name="tags" /></span>
      </h1>
      <p v-if="desc" class="ph-desc">{{ desc }}</p>
    </div>
    <div class="ph-actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.ph-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}
.ph-tags {
  display: inline-flex;
  gap: 6px;
}
.ph-desc {
  margin: 6px 0 0;
  color: var(--iv-text-3);
  font-size: 13px;
}
.ph-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
</style>
