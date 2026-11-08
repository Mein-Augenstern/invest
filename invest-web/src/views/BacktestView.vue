<!--
  策略回测（对齐小程序 backtest）：参数表单 → POST /backtest → 六策略曲线对比 + 指标表。
-->
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import EChart from '@/components/charts/EChart.vue'
import { SERIES_COLORS, type EChartsOption } from '@/components/charts/echarts'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { errMsg } from '@/api/client'
import { runBacktest } from '@/api/invest'
import type { BacktestResult } from '@/types'
import { fmtAmount } from '@/utils/format'

const form = reactive({
  start: '2013-06-03',
  monthly: 1000,
})
const running = ref(false)
const error = ref('')
const span = ref('')
const results = ref<BacktestResult[]>([])

/** 指标列动态生成：六策略 metrics 的键并集（保持首个结果的出现顺序） */
const metricCols = computed(() => {
  const keys: string[] = []
  for (const r of results.value) {
    for (const k of Object.keys(r.metrics)) if (!keys.includes(k)) keys.push(k)
  }
  return keys
})

const chartOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => Number(v).toFixed(2) },
  legend: { top: 0, type: 'scroll' },
  grid: { left: 56, right: 24, top: 36, bottom: 48 },
  xAxis: { type: 'time', axisLabel: { formatter: '{yyyy}' } },
  yAxis: { type: 'value', name: '净值比', scale: true },
  dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8 }],
  color: SERIES_COLORS,
  series: results.value.map((r) => ({
    name: r.name,
    type: 'line',
    showSymbol: false,
    data: r.curve,
    emphasis: { focus: 'series' },
  })),
}))

async function run() {
  if (running.value) return
  running.value = true
  error.value = ''
  try {
    const res = await runBacktest({ start: form.start, monthly: form.monthly })
    span.value = res.span
    results.value = res.results
  } catch (e) {
    error.value = errMsg(e)
    ElMessage.error(errMsg(e))
  } finally {
    running.value = false
  }
}
</script>

<template>
  <PageHeader title="策略回测" :desc="span ? `区间 ${span}` : '对比六种定投策略在同区间、同投入下的净值比表现'" />

  <div class="panel">
    <div class="params">
      <span class="param-label">起始</span>
      <el-date-picker v-model="form.start" type="date" value-format="YYYY-MM-DD" :clearable="false" :disabled="running" />
      <span class="param-label">每月投入</span>
      <el-input-number v-model="form.monthly" :min="100" :max="100000" :step="500" :controls="false" :disabled="running" />
      <el-button type="primary" :loading="running" @click="run">{{ running ? '回测中…' : '运行回测' }}</el-button>
      <span class="muted hint">净值比 = 资产市值 ÷ 累计投入，>1 跑赢投入</span>
    </div>
  </div>

  <StateBlock :loading="running" :error="error" :empty="!results.length && !error" :has-data="!!results.length" empty-text="设置参数后运行回测" @retry="run">
    <template v-if="results.length">
      <div class="panel panel-gap">
        <div class="panel-title">净值比曲线</div>
        <EChart :option="chartOption" height="420px" />
      </div>

      <div class="panel panel-gap">
        <div class="panel-title">策略指标</div>
        <el-table :data="results" row-key="code">
          <el-table-column prop="name" label="策略" min-width="150" fixed="left" />
          <el-table-column prop="params" label="参数" min-width="160" show-overflow-tooltip />
          <el-table-column v-for="k in metricCols" :key="k" :label="k" align="right" min-width="110">
            <template #default="{ row }">
              {{ row.metrics[k] === null || row.metrics[k] === undefined ? '—' : row.metrics[k] }}
            </template>
          </el-table-column>
        </el-table>
      </div>

      <p class="muted note">回测基于历史净值，不构成未来收益承诺（章程：LLM 不预测、不荐股）。</p>
    </template>
  </StateBlock>
</template>

<style scoped>
.params {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.param-label {
  color: var(--iv-text-2);
  font-size: 13px;
}
.hint {
  font-size: 12px;
}
.note {
  margin-top: 12px;
  font-size: 12px;
  text-align: center;
}
</style>
