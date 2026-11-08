<!--
  ECharts 通用容器：传入 option 即渲染；容器尺寸变化自动 resize（ResizeObserver），卸载时释放实例。
  用法：<EChart :option="opt" height="360px" @chart-click="onClick" />
-->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { echarts, type EChartsOption } from './echarts'

const props = withDefaults(defineProps<{ option: EChartsOption; height?: string }>(), {
  height: '320px',
})
const emit = defineEmits<{ (e: 'chart-click', params: unknown): void }>()

const el = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let observer: ResizeObserver | null = null

onMounted(() => {
  if (!el.value) return
  chart.value = echarts.init(el.value)
  chart.value.setOption(props.option)
  chart.value.on('click', (p) => emit('chart-click', p))
  observer = new ResizeObserver(() => chart.value?.resize())
  observer.observe(el.value)
})

watch(
  () => props.option,
  (opt) => chart.value?.setOption(opt, { notMerge: true }),
  { deep: true },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.dispose()
})
</script>

<template>
  <div ref="el" class="echart" :style="{ height }" />
</template>

<style scoped>
.echart {
  width: 100%;
}
</style>
