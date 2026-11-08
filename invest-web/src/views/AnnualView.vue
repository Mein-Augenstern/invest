<!--
  年度复盘（对齐小程序 annual）：年份切换 · 指标卡两行（年度盈亏/净投入/期末市值/胜月数 · 最佳月/最差月/账户现金/现金分红）· 月度盈亏条形图（红盈绿亏）。
  口径与「统计」页同源：浮盈变化 = Δ市值 − 净投入；账户现金为缴存未申购的存量余额（从首笔流水累计至今，不按年过滤）。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import StatCard from '@/components/StatCard.vue'
import EChart from '@/components/charts/EChart.vue'
import { FALL, RISE, type EChartsOption } from '@/components/charts/echarts'
import { errMsg } from '@/api/client'
import { getAnnualReport } from '@/api/invest'
import type { AnnualReport } from '@/types'
import { fmtAmount, fmtSigned, pnlClass } from '@/utils/format'

/** 最近 3 年（含今年），倒序 */
const thisYear = new Date().getFullYear()
const YEARS = [0, 1, 2].map((i) => String(thisYear - i))
const year = ref(YEARS[0])

const data = ref<AnnualReport | null>(null)
const loading = ref(true)
const error = ref('')

/** 快速切换年份时只认最后一次请求，避免慢响应覆盖新年份 */
let reqSeq = 0

async function load() {
  const seq = ++reqSeq
  loading.value = true
  error.value = ''
  try {
    const res = await getAnnualReport(year.value)
    if (seq === reqSeq) data.value = res
  } catch (e) {
    if (seq === reqSeq) error.value = errMsg(e)
  } finally {
    if (seq === reqSeq) loading.value = false
  }
}

/** empty=true 时后端只回 {year, empty}，其余字段一律从非空报告取 */
const report = computed(() => (data.value && !data.value.empty ? data.value : null))

const winRate = computed(() => {
  const r = report.value
  return r && r.months_count ? Math.round((r.win_months / r.months_count) * 100) : 0
})

/** 后端 monthly 为新→旧，图表按月份正序 */
const monthly = computed(() => [...(report.value?.monthly ?? [])].sort((a, b) => a.month.localeCompare(b.month)))
const lastMonth = computed(() => monthly.value.at(-1)?.month ?? '')

/* ---------- 月度盈亏条形图：正 RISE 红 / 负 FALL 绿 ---------- */

/** 纵轴刻度：万元缩写，避免长数字挤压绘图区 */
function axisLabel(v: number): string {
  return Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1).replace(/\.0$/, '')}万` : String(v)
}

const chartOption = computed<EChartsOption>(() => ({
  grid: { left: 56, right: 16, top: 28, bottom: 28 },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    valueFormatter: (v: unknown) => fmtSigned(Number(v)),
  },
  xAxis: {
    type: 'category',
    data: monthly.value.map((m) => `${Number(m.month.slice(5))}月`),
    axisTick: { alignWithLabel: true },
    axisLine: { lineStyle: { color: '#c9cdd4' } },
    axisLabel: { color: '#4e5969' },
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#86909c', formatter: axisLabel },
    splitLine: { lineStyle: { color: '#f0f1f3' } },
  },
  series: [
    {
      name: '浮盈变化',
      type: 'bar',
      barMaxWidth: 40,
      label: {
        show: true,
        fontSize: 11,
        color: '#4e5969',
        formatter: (p: { value: unknown }) => fmtSigned(Number(p.value), 0),
      },
      data: monthly.value.map((m) => ({
        value: m.pnl_change,
        itemStyle: { color: m.pnl_change >= 0 ? RISE : FALL },
        label: { position: m.pnl_change >= 0 ? 'top' : 'bottom' },
      })),
    },
  ],
}))

onMounted(load)
</script>

<template>
  <PageHeader title="年度复盘" desc="浮盈变化 = Δ市值 − 净投入，与「统计」页同源口径">
    <template #actions>
      <el-select v-model="year" style="width: 120px" @change="load">
        <el-option v-for="y in YEARS" :key="y" :label="`${y} 年`" :value="y" />
      </el-select>
    </template>
  </PageHeader>

  <StateBlock
    :loading="loading"
    :error="error"
    :empty="!!data && data.empty"
    :has-data="!!report"
    empty-text="该年度暂无数据"
    @retry="load"
  >
    <template v-if="report">
      <div class="grid grid-4">
        <StatCard
          :label="`${report.year} 年度盈亏`"
          :value="fmtSigned(report.pnl_change)"
          :tone="pnlClass(report.pnl_change)"
          sub="持仓浮盈变化 = Δ市值 − 净投入"
        />
        <StatCard
          label="净投入"
          :value="fmtAmount(report.net_invested)"
          :sub="`申购 ${fmtAmount(report.invested, 0)} · 赎回 ${fmtAmount(report.returned, 0)}`"
        />
        <StatCard label="期末市值" :value="fmtAmount(report.year_end_mv)" :sub="`截至 ${lastMonth} 月末`" />
        <StatCard label="胜月数" :value="`${report.win_months} / ${report.months_count}`" :sub="`月度胜率 ${winRate}%`" />
      </div>

      <div class="grid grid-4 panel-gap">
        <StatCard
          label="最佳月"
          :value="fmtSigned(report.best_month.pnl_change)"
          :tone="pnlClass(report.best_month.pnl_change)"
          :sub="report.best_month.month"
        />
        <StatCard
          label="最差月"
          :value="fmtSigned(report.worst_month.pnl_change)"
          :tone="pnlClass(report.worst_month.pnl_change)"
          :sub="report.worst_month.month"
        />
        <StatCard label="账户现金" :value="fmtAmount(report.account_cash)" sub=" ">
          <template #sub>
            缴存未申购 · 累计至今
            <el-tag v-if="report.account_cash < 0" type="warning" size="small" class="cash-warn">缴存记录待补全</el-tag>
          </template>
        </StatCard>
        <StatCard label="现金分红" :value="fmtAmount(report.cash_div)" sub=" ">
          <template #sub>
            已实现盈亏 <span :class="pnlClass(report.realized)">{{ fmtSigned(report.realized) }}</span>
          </template>
        </StatCard>
      </div>

      <div class="panel panel-gap">
        <div class="panel-title">
          <span>月度盈亏分布 <span class="muted hint">红色盈利 · 绿色亏损</span></span>
        </div>
        <EChart :option="chartOption" height="320px" />
        <p class="note muted">持仓浮盈 = Δ市值 − 净投入；养老金账户「缴存未申购」的现金单列，不计入浮盈。回望是纪律的一部分。</p>
      </div>
    </template>
  </StateBlock>
</template>

<style scoped>
/* 全局 .panel + .panel 会给栅格内相邻卡片加上外边距，栅格内以 gap 为准 */
.grid > .panel {
  margin-top: 0;
}
.hint {
  font-size: 12px;
  font-weight: 400;
  margin-left: 8px;
}
.cash-warn {
  margin-left: 6px;
}
.note {
  font-size: 12px;
  line-height: 1.6;
  margin: 8px 0 0;
}
</style>
