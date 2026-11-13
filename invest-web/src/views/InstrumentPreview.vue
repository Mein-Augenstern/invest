<!--
  标的预览（完整页面）：与 /instrument/:id 同布局，数据来自预览端点（首次拉取后持久化）。
  preview 模式：隐藏写操作（记一笔/记净值），显示「加入我的标的」。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import StatCard from '@/components/StatCard.vue'
import EChart from '@/components/charts/EChart.vue'
import { SERIES_COLORS, type EChartsOption } from '@/components/charts/echarts'
import { errMsg } from '@/api/client'
import { previewInstrument } from '@/api/invest'
import { fmtAmount, fmtPct, pnlClass } from '@/utils/format'
import type { InstrumentPerformance, InstrumentProfile } from '@/types'

const route = useRoute()
const router = useRouter()

const data = ref<Awaited<ReturnType<typeof previewInstrument>> | null>(null)
const loading = ref(true)
const error = ref('')
const itype = computed(() => (route.query.type as string) || 'fund')
const code = computed(() => route.params.code as string)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await previewInstrument(code.value, itype.value)
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

const navOption = computed<EChartsOption>(() => {
  const s = data.value?.nav_series || []
  if (s.length < 2) return {}
  return {
    grid: { left: 12, right: 24, top: 28, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', scale: true },
    series: [{ type: 'line', data: s, showSymbol: false, lineStyle: { width: 1.5, color: SERIES_COLORS[0] } }],
  }
})

const typeTagColor = computed<'primary' | 'success' | 'danger' | 'warning' | 'info'>(() => {
  const map: Record<string, 'primary' | 'success' | 'danger' | 'warning' | 'info'> = { fund: 'primary', etf: 'success', stock: 'danger', bond: 'warning', wealth: 'info' }
  return map[itype.value] || 'info'
})

const typeLabelMap: Record<string, string> = { fund: '基金', etf: 'ETF', stock: '股票', bond: '债券', wealth: '理财', index: '指数' }

function goAdd() {
  router.push({ name: 'instruments' })
  ElMessage.info('请到标的管理 → 新增标的 → 搜索后添加')
}

onMounted(load)
</script>

<template>
  <PageHeader :title="data?.name || code" :desc="data ? `代码 ${data.code} · ${typeLabelMap[data.type] || data.type}` : '加载中…'">
    <template #tags>
      <el-tag :type="typeTagColor" effect="light">{{ typeLabelMap[itype] || itype }}</el-tag>
      <el-tag v-if="data?.performance?.trend" :type="data.performance.trend === '上行' ? 'danger' : data.performance.trend === '下行' ? 'success' : 'info'">
        {{ data.performance.trend }}
      </el-tag>
    </template>
    <template #actions>
      <el-button @click="router.back()">返回目录</el-button>
      <el-button type="primary" :icon="Plus" @click="goAdd">加入我的标的</el-button>
    </template>
  </PageHeader>

  <StateBlock :loading="loading" :error="error" :empty="!data?.has_data" :has-data="!!data?.has_data" empty-text="暂无行情数据" @retry="load">
    <template v-if="data?.has_data">
      <!-- 指标卡 -->
      <div class="grid grid-4">
        <StatCard label="最新净值/价格" :value="data.row.price !== null ? fmtAmount(data.row.price, 4) : '—'" :sub="`截至 ${data.row.price_date}`" />
        <StatCard v-for="(val, key) in (data.performance?.returns || {})" :key="key" :label="{ m1: '近1月', m3: '近3月', m6: '近6月', y1: '近1年', y3: '近3年', all: '成立以来' }[key] || key" :value="fmtPct(val)" :tone="pnlClass(val)" />
      </div>

      <!-- 净值曲线 -->
      <div class="panel panel-gap">
        <div class="panel-title">净值 / 价格走势</div>
        <EChart v-if="data.nav_series.length >= 2" :option="navOption" height="400px" />
        <el-empty v-else description="数据不足" :image-size="80" />
      </div>

      <!-- 概况 + 业绩 -->
      <div v-if="data.profile || data.performance" class="grid grid-2 panel-gap">
        <div v-if="data.profile" class="panel">
          <div class="panel-title">{{ data.profile.title }}概况</div>
          <div class="profile-grid">
            <div v-for="f in data.profile.fields" :key="f.label" class="profile-field">
              <span class="pf-label muted">{{ f.label }}</span>
              <span class="pf-value num">{{ f.value }}</span>
            </div>
          </div>
        </div>
        <div v-if="data.performance && Object.keys(data.performance.returns || {}).length" class="panel">
          <div class="panel-title">业绩表现</div>
          <div class="perf-grid">
            <div v-for="(val, key) in data.performance.returns" :key="key" class="perf-item">
              <span class="pf-label muted">{{ { m1: '近1月', m3: '近3月', m6: '近6月', y1: '近1年', y3: '近3年', all: '成立以来' }[key] || key }}</span>
              <span class="pf-value num" :class="pnlClass(val)">{{ fmtPct(val) }}</span>
            </div>
          </div>
          <div v-if="data.performance.volatility !== null || data.performance.max_drawdown !== null" class="risk-row">
            <span v-if="data.performance.risk_level">
              风险等级 <el-tag size="small" :type="data.performance.risk_level.startsWith('R1') || data.performance.risk_level.startsWith('R2') ? 'success' : data.performance.risk_level.startsWith('R3') ? 'warning' : 'danger'">{{ data.performance.risk_level }}</el-tag>
            </span>
            <span v-if="data.performance.sharpe !== null" class="muted">夏普 <b class="num">{{ data.performance.sharpe }}</b></span>
            <span v-if="data.performance.volatility !== null" class="muted">年化波动 <b class="num">{{ (data.performance.volatility * 100).toFixed(1) }}%</b></span>
            <span v-if="data.performance.max_drawdown !== null" class="muted">最大回撤 <b class="num" :class="pnlClass(data.performance.max_drawdown)">{{ (data.performance.max_drawdown * 100).toFixed(1) }}%</b></span>
          </div>
        </div>
      </div>

      <!-- 提示 -->
      <el-alert type="info" :closable="false" class="panel-gap">
        <template #title>这是预览模式</template>
        加入我的标的后，将自动拉取行情、跟踪持仓、计算 XIRR 和信号。当前看到的是公开行情数据。
      </el-alert>
    </template>
  </StateBlock>
</template>

<style scoped>
.grid > .panel {
  margin-top: 0;
}
.profile-grid, .perf-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.profile-field, .perf-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pf-label { font-size: 12px; }
.pf-value { font-size: 15px; font-weight: 600; }
.risk-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--iv-border);
  font-size: 13px;
}
</style>
