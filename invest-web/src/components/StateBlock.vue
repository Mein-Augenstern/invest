<!--
  三态容器（S06 模式 / S10 AC-4）：加载中 / 错误+重试 / 空态，数据就绪时渲染默认插槽。
  - 首次加载显示骨架；已有数据时的刷新只在内容上叠加 loading，不闪白
  用法：<StateBlock :loading="loading" :error="error" :empty="!rows.length" @retry="load">…</StateBlock>
-->
<script setup lang="ts">
withDefaults(
  defineProps<{
    loading: boolean
    error?: string
    empty?: boolean
    emptyText?: string
    /** 已有数据（刷新场景）：loading 时不替换内容，只叠加遮罩 */
    hasData?: boolean
  }>(),
  { error: '', empty: false, emptyText: '暂无数据', hasData: false },
)
defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div v-if="loading && !hasData" class="state-skeleton">
    <el-skeleton :rows="5" animated />
  </div>
  <el-result v-else-if="error" icon="error" title="加载失败" :sub-title="error">
    <template #extra>
      <el-button type="primary" @click="$emit('retry')">重试</el-button>
    </template>
  </el-result>
  <el-empty v-else-if="empty && !loading" :description="emptyText">
    <slot name="empty-action" />
  </el-empty>
  <div v-else v-loading="loading">
    <slot />
  </div>
</template>

<style scoped>
.state-skeleton {
  padding: 8px 0;
}
</style>
