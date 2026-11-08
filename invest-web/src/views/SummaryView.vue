<!--
  统计（对齐小程序 summary）：总资产曲线（90天 / 365天 / 全部，周期切换在页头）· 日盈亏日历（按月）·
  年度汇总 · 月度明细（近 24 月）。三类数据独立请求、各自三态，互不阻塞。
-->
<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import EChart from '@/components/charts/EChart.vue'
import { SERIES_COLORS, type EChartsOption } from '@/components/charts/echarts'
import { errMsg } from '@/api/client'
import { getAssetCurve, getDailyPnl, getSummary } from '@/api/invest'
import type { AssetCurve, DailyPnl, SummaryPayload } from '@/types'
import { fmtAmount, fmtSigned, fmtTs, localDate, pnlClass } from '@/utils/format'

/* ---------- 总资产曲线 ---------- */

const RANGES = [
  { label: '90天', days: 90 },
  { label: '365天', days: 365 },
  { label: '全部', days: 3650 },
]

const curveDays = ref(365)
/** 只读数组直接交给 ECharts：shallowRef 避免深层代理 */
const curve = shallowRef<AssetCurve | null>(null)
const curveLoading = ref(true)
const curveError = ref('')
let curveSeq = 0 // 快速切换周期时丢弃过期响应

async function loadCurve() {
  const seq = ++curveSeq
  curveLoading.value = true
  curveError.value = ''
  try {
    const res = await getAssetCurve(curveDays.value)
    if (seq === curveSeq) curve.value = res
  } catch (e) {
    if (seq === curveSeq) curveError.value = errMsg(e)
  } finally {
    if (seq === curveSeq) curveLoading.value = false
  }
}

watch(curveDays, loadCurve)

const points = computed(() => curve.value?.curve ?? [])

const curveSub = computed(() => {
  const c = curve.value
  const p = points.value
  if (!c || p.length < 2) return ''
  return `${c.start} 至 ${c.end} · 期初 ${fmtAmount(p[0][1])} → 期末 ${fmtAmount(p[p.length - 1][1])}`
})

/** y 轴标签：≥ 1 万显示「x.x万」 */
function fmtWan(v: number): string {
  return Math.abs(v) >= 10_000 ? `${Number((v / 10_000).toFixed(1))}万` : String(v)
}

const curveOption = computed<EChartsOption>(() => ({
  color: [SERIES_COLORS[0]],
  grid: { left: 12, right: 24, top: 24, bottom: 8, containLabel: true },
  tooltip: {
    trigger: 'axis',
    valueFormatter: (v: unknown) => (typeof v === 'number' ? fmtAmount(v) : '—'),
  },
  xAxis: {
    type: 'time',
    axisLine: { lineStyle: { color: '#c9cdd4' } },
    axisLabel: { color: '#86909c' },
    splitLine: { show: false },
    // tooltip 标题取 x 轴 axisPointer 标签：固定 YYYY-MM-DD（默认随刻度粒度，跨年会显示成「年-月」）
    axisPointer: { label: { formatter: (p: { value: number | string }) => fmtTs(Number(p.value)) } },
  },
  yAxis: {
    type: 'value',
    scale: true,
    axisLabel: { color: '#86909c', formatter: fmtWan },
    splitLine: { lineStyle: { color: '#f0f1f3' } },
  },
  series: [
    {
      name: '总资产',
      type: 'line',
      data: points.value,
      showSymbol: false,
      lineStyle: { width: 1.5 },
      areaStyle: { color: SERIES_COLORS[0], opacity: 0.08 },
    },
  ],
}))

/* ---------- 年度 / 月度（近 24 月） ---------- */

const SUMMARY_MONTHS = 24
const summary = shallowRef<SummaryPayload | null>(null)
const sumLoading = ref(true)
const sumError = ref('')

async function loadSummary() {
  sumLoading.value = true
  sumError.value = ''
  try {
    summary.value = await getSummary(SUMMARY_MONTHS)
  } catch (e) {
    sumError.value = errMsg(e)
  } finally {
    sumLoading.value = false
  }
}

/** 后端已按时间倒序返回，这里显式再排一次，不依赖返回顺序 */
const months = computed(() => [...(summary.value?.months ?? [])].sort((a, b) => b.month.localeCompare(a.month)))
const years = computed(() => [...(summary.value?.years ?? [])].sort((a, b) => b.year.localeCompare(a.year)))

/* ---------- 日盈亏日历 ---------- */

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
const thisMonth = localDate().slice(0, 7)
const calMonth = ref(thisMonth)
/** 记下数据所属月份：切月加载期间不把上个月的数字 / 合计串到新月份上 */
const cal = shallowRef<{ month: string; data: DailyPnl } | null>(null)
const calLoading = ref(true)
const calError = ref('')
let calSeq = 0

async function loadCal() {
  const seq = ++calSeq
  const month = calMonth.value
  calLoading.value = true
  calError.value = ''
  try {
    const res = await getDailyPnl(month)
    if (seq === calSeq) cal.value = { month, data: res }
  } catch (e) {
    if (seq === calSeq) calError.value = errMsg(e)
  } finally {
    if (seq === calSeq) calLoading.value = false
  }
}

watch(calMonth, loadCal)

function shiftMonth(delta: number) {
  const [y, m] = calMonth.value.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  calMonth.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function disabledMonth(d: Date): boolean {
  return localDate(d).slice(0, 7) > thisMonth
}

const calDays = computed<Record<string, number>>(() => (cal.value?.month === calMonth.value ? cal.value.data.days : {}))
const calTotal = computed(() => (cal.value?.month === calMonth.value ? cal.value.data.month_total : null))
const calEmpty = computed(() => !Object.keys(calDays.value).length)

interface CalCell {
  key: string
  day: number
  inMonth: boolean
  pnl: number | null
  today: boolean
  future: boolean
}

/** 周一开头的 7 列月历：前补上月灰格、尾补下月灰格凑满整周 */
const calCells = computed<CalCell[]>(() => {
  const [y, m] = calMonth.value.split('-').map(Number)
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7 // 周一 = 0
  const dim = new Date(y, m, 0).getDate()
  const prevDim = new Date(y, m - 1, 0).getDate()
  const today = localDate()
  const days = calDays.value
  const pad = (key: string, day: number): CalCell => ({ key, day, inMonth: false, pnl: null, today: false, future: false })
  const cells: CalCell[] = []
  for (let i = lead - 1; i >= 0; i--) cells.push(pad(`prev-${i}`, prevDim - i))
  for (let d = 1; d <= dim; d++) {
    const key = `${calMonth.value}-${String(d).padStart(2, '0')}`
    cells.push({ key, day: d, inMonth: true, pnl: key in days ? days[key] : null, today: key === today, future: key > today })
  }
  for (let d = 1; cells.length % 7 !== 0; d++) cells.push(pad(`next-${d}`, d))
  return cells
})

/** 0 / 无数据显示灰，其余红盈绿亏 */
function cellClass(c: CalCell): string {
  return c.pnl === null || c.pnl === 0 ? 'muted' : pnlClass(c.pnl)
}

onMounted(() => {
  loadCurve()
  loadSummary()
  loadCal()
})
</script>

<template>
  <PageHeader title="统计" desc="盈亏口径：期末市值 − 期初市值 − 期间净投入（红盈绿亏）">
    <template #actions>
      <span class="muted range-label">资产曲线</span>
      <el-radio-group v-model="curveDays">
        <el-radio-button v-for="r in RANGES" :key="r.days" :value="r.days">{{ r.label }}</el-radio-button>
      </el-radio-group>
    </template>
  </PageHeader>

  <!-- 总资产曲线 -->
  <div class="panel">
    <div class="panel-title">
      <span>总资产走势</span>
      <span v-if="curveSub" class="muted hint num">{{ curveSub }}</span>
    </div>
    <StateBlock
      :loading="curveLoading"
      :error="curveError"
      :empty="points.length < 2"
      :has-data="!!curve"
      empty-text="暂无足够历史（录入流水并拉取净值后生成）"
      @retry="loadCurve"
    >
      <EChart :option="curveOption" height="360px" />
    </StateBlock>
  </div>

  <!-- 日盈亏日历 -->
  <div class="panel panel-gap">
    <div class="panel-title">
      <span>
        日盈亏日历
        <span v-if="calTotal !== null && !calEmpty" class="hint">
          月合计 <b class="num" :class="pnlClass(calTotal)">{{ fmtSigned(calTotal) }}</b>
        </span>
      </span>
      <span class="cal-tools">
        <el-button :icon="ArrowLeft" circle size="small" @click="shiftMonth(-1)" />
        <el-date-picker
          v-model="calMonth"
          type="month"
          value-format="YYYY-MM"
          :clearable="false"
          :editable="false"
          :disabled-date="disabledMonth"
          size="small"
          style="width: 130px"
        />
        <el-button :icon="ArrowRight" circle size="small" :disabled="calMonth >= thisMonth" @click="shiftMonth(1)" />
      </span>
    </div>
    <StateBlock
      :loading="calLoading"
      :error="calError"
      :empty="calEmpty"
      :has-data="!!cal"
      :empty-text="`${calMonth} 暂无逐日收益（该月没有净值数据或尚未建仓）`"
      @retry="loadCal"
    >
      <div class="cal-grid">
        <div v-for="w in WEEKDAYS" :key="w" class="cal-week">{{ w }}</div>
        <div v-for="c in calCells" :key="c.key" class="cal-cell" :class="{ out: !c.inMonth, today: c.today }">
          <span class="cal-day">{{ c.day }}</span>
          <span v-if="c.inMonth && !c.future" class="cal-pnl num" :class="cellClass(c)">
            {{ c.pnl === null ? '—' : fmtSigned(c.pnl) }}
          </span>
        </div>
      </div>
      <div class="muted note">当日盈亏 = 当日市值 − 前一估值日市值 − 当日净投入；周末、节假日等无净值的日期显示 —</div>
    </StateBlock>
  </div>

  <!-- 年度汇总 -->
  <div class="panel panel-gap">
    <div class="panel-title">
      <span>年度汇总 <span class="muted hint">按近 {{ SUMMARY_MONTHS }} 个月数据汇总，最早一年可能不完整</span></span>
    </div>
    <StateBlock
      :loading="sumLoading"
      :error="sumError"
      :empty="!years.length"
      :has-data="!!summary"
      empty-text="暂无数据（先录入流水并拉取净值）"
      @retry="loadSummary"
    >
      <el-table :data="years">
        <el-table-column prop="year" label="年份" width="100" />
        <el-table-column label="净投入" align="right" min-width="130">
          <template #default="{ row }">{{ fmtAmount(row.net_invested) }}</template>
        </el-table-column>
        <el-table-column label="年度盈亏" align="right" min-width="130">
          <template #default="{ row }"><span :class="pnlClass(row.pnl_change)">{{ fmtSigned(row.pnl_change) }}</span></template>
        </el-table-column>
        <el-table-column label="现金分红" align="right" min-width="120">
          <template #default="{ row }">{{ fmtAmount(row.cash_div) }}</template>
        </el-table-column>
        <el-table-column label="已实现" align="right" min-width="120">
          <template #default="{ row }"><span :class="pnlClass(row.realized)">{{ fmtSigned(row.realized) }}</span></template>
        </el-table-column>
        <el-table-column label="期末市值" align="right" min-width="140">
          <template #default="{ row }">{{ fmtAmount(row.market_value) }}</template>
        </el-table-column>
      </el-table>
    </StateBlock>
  </div>

  <!-- 月度明细 -->
  <div class="panel panel-gap">
    <div class="panel-title">
      <span>月度明细 <span class="muted hint">近 {{ SUMMARY_MONTHS }} 个月 · 月度盈亏 = 月末市值 − 月初市值 − 当月净投入</span></span>
    </div>
    <StateBlock
      :loading="sumLoading"
      :error="sumError"
      :empty="!months.length"
      :has-data="!!summary"
      empty-text="暂无数据（先录入流水并拉取净值）"
      @retry="loadSummary"
    >
      <el-table :data="months">
        <el-table-column prop="month" label="月份" width="100" />
        <el-table-column label="期末市值" align="right" min-width="130">
          <template #default="{ row }">{{ fmtAmount(row.market_value) }}</template>
        </el-table-column>
        <el-table-column label="净投入" align="right" min-width="120">
          <template #default="{ row }">{{ fmtAmount(row.net_invested) }}</template>
        </el-table-column>
        <el-table-column label="投入" align="right" min-width="120">
          <template #default="{ row }">{{ fmtAmount(row.invested) }}</template>
        </el-table-column>
        <el-table-column label="收回" align="right" min-width="120">
          <template #default="{ row }">{{ fmtAmount(row.returned) }}</template>
        </el-table-column>
        <el-table-column label="现金分红" align="right" min-width="110">
          <template #default="{ row }">{{ fmtAmount(row.cash_div) }}</template>
        </el-table-column>
        <el-table-column label="已实现" align="right" min-width="110">
          <template #default="{ row }"><span :class="pnlClass(row.realized)">{{ fmtSigned(row.realized) }}</span></template>
        </el-table-column>
        <el-table-column prop="pnl_change" label="月度盈亏" align="right" min-width="130" sortable>
          <template #default="{ row }"><span :class="pnlClass(row.pnl_change)">{{ fmtSigned(row.pnl_change) }}</span></template>
        </el-table-column>
      </el-table>
    </StateBlock>
  </div>
</template>

<style scoped>
.range-label {
  align-self: center;
  font-size: 13px;
}
.hint {
  font-size: 12px;
  font-weight: 400;
}
.hint b {
  margin-left: 4px;
  font-weight: 600;
}
.cal-tools {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}
.cal-week {
  text-align: center;
  font-size: 12px;
  color: var(--iv-text-3);
  padding: 2px 0 4px;
}
.cal-cell {
  min-height: 64px;
  padding: 8px 10px;
  border: 1px solid var(--iv-border);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.cal-cell.out {
  background: #f7f8fa;
  border-color: #f2f3f5;
}
.cal-cell.out .cal-day {
  color: #c9cdd4;
}
.cal-cell.today {
  border-color: var(--iv-primary);
}
.cal-day {
  font-size: 12px;
  color: var(--iv-text-2);
}
.cal-pnl {
  font-size: 14px;
  font-weight: 600;
  text-align: right;
  white-space: nowrap;
}
.cal-pnl.muted {
  font-weight: 400;
}
.note {
  font-size: 12px;
  margin-top: 12px;
}
</style>
