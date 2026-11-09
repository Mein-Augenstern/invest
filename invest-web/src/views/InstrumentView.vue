<!--
  标的详情（钻取页，对齐小程序 instrument）：指标卡 / 净值曲线（成本线 + 交易事件）/ 基准估值 / PE 分位带 /
  基金透视 / 交易事件时间线 / 该标的信号；理财（wealth）可「记净值」。
  路由 /instrument/:id：AppLayout 以 fullPath 作 router-view key，换标的会重建组件，无需 watch id。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { EditPen, Tickets } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import StatCard from '@/components/StatCard.vue'
import EChart from '@/components/charts/EChart.vue'
import { FALL, RISE, SERIES_COLORS, type EChartsOption } from '@/components/charts/echarts'
import { ApiError, errMsg } from '@/api/client'
import { addNav, getInstrumentDetail } from '@/api/invest'
import type { HoldingDetail, Signal, TradeEvent } from '@/types'
import { fmtAmount, fmtPct, fmtPlainPct, fmtQty, fmtSigned, fmtTs, localDate, pnlClass } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)

/** 只读大数组直接交给 ECharts：shallowRef 避免深层代理；整体替换即可触发更新 */
const data = shallowRef<HoldingDetail | null>(null)
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const title = ref('标的详情')

async function load() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    data.value = await getInstrumentDetail(id)
    title.value = data.value.name
  } catch (e) {
    notFound.value = e instanceof ApiError && e.status === 404
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

const desc = computed(() => {
  const d = data.value
  if (!d) return ''
  return [d.code && `代码 ${d.code}`, d.nav_start && `行情起始 ${d.nav_start}`].filter(Boolean).join(' · ')
})

function goTrades() {
  router.push({ name: 'trades', query: { instrument: id } })
}

/* ---------- 图表公共：轴样式 / 时间轴 / 数值工具 ---------- */

const MUTED = '#86909c'
const AXIS_LABEL = { color: MUTED }
const AXIS_LINE = { lineStyle: { color: '#c9cdd4' } }
const SPLIT_LINE = { lineStyle: { color: '#f0f1f3' } }

/** 时间轴：十字准星 x 标签与 tooltip 标题统一为 YYYY-MM-DD（ECharts 默认随刻度粒度，跨年会降成「年-月」） */
function timeAxis() {
  return {
    type: 'time',
    axisLine: AXIS_LINE,
    axisLabel: AXIS_LABEL,
    splitLine: { show: false },
    axisPointer: { label: { formatter: (p: { value: number | string }) => fmtTs(Number(p.value)) } },
  }
}

function fixed(v: unknown, digits: number): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—'
}

function extentOf(values: number[]): [number, number] {
  let min = Infinity
  let max = -Infinity
  for (const v of values) {
    if (v < min) min = v
    if (v > max) max = v
  }
  return [min, max]
}

/** 固定 y 轴范围时外扩到整刻度并留 4% 边距：避免轴端零碎标签、折线贴边 */
function niceBounds(lo: number, hi: number): [number, number] {
  const span = hi - lo || Math.abs(hi) || 1
  const step = 10 ** Math.floor(Math.log10(span / 5))
  const digits = Math.max(0, -Math.floor(Math.log10(step)))
  const min = Math.floor((lo - span * 0.04) / step) * step
  const max = Math.ceil((hi + span * 0.04) / step) * step
  return [Number(min.toFixed(digits)), Number(max.toFixed(digits))]
}

/** #rrggbb → rgba：分位带背景用低透明度的红 / 绿语义色 */
function rgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/* ---------- 交易事件 ---------- */

/** 红买绿卖（与流水页动作标签一致），分红等其余动作用辅助橙 */
function eventColor(kind: string): string {
  if (kind === 'buy') return RISE
  if (kind === 'sell') return FALL
  return SERIES_COLORS[1]
}

const eventsDesc = computed(() => [...(data.value?.events ?? [])].sort((a, b) => b.ts - a.ts))

/* ---------- 净值曲线：成本线 markLine + 交易事件 markPoint ---------- */

const navSeries = computed(() => data.value?.nav_series ?? [])

/** 区间涨跌（首 → 尾，对齐小程序 periodChange） */
const periodChange = computed(() => {
  const s = navSeries.value
  if (s.length < 2 || s[0][1] <= 0) return null
  return s[s.length - 1][1] / s[0][1] - 1
})

/** 事件落点：在折线上线性插值（序列已降采样，事件日未必是采样点），保证标记压在曲线上 */
function valueAt(series: [number, number][], ts: number): number {
  let lo = 0
  let hi = series.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (series[mid][0] <= ts) lo = mid
    else hi = mid
  }
  const [t0, v0] = series[lo]
  const [t1, v1] = series[hi]
  return t1 === t0 ? v0 : v0 + ((v1 - v0) * (ts - t0)) / (t1 - t0)
}

/** 只画落在净值序列时间范围内的事件；同日多笔合并为一个点（悬停显示明细） */
const eventMarks = computed(() => {
  const s = navSeries.value
  if (s.length < 2) return []
  const start = s[0][0]
  const end = s[s.length - 1][0]
  const byTs = new Map<number, TradeEvent[]>()
  for (const ev of data.value?.events ?? []) {
    if (ev.ts < start || ev.ts > end) continue
    const list = byTs.get(ev.ts)
    if (list) list.push(ev)
    else byTs.set(ev.ts, [ev])
  }
  return [...byTs].map(([ts, evs]) => ({
    name: `${fmtTs(ts)} ${evs.map((e) => e.label).join('；')}`,
    coord: [ts, valueAt(s, ts)],
    itemStyle: { color: eventColor(evs[0].kind) },
  }))
})

const navOption = computed<EChartsOption>(() => {
  const s = navSeries.value
  const avg = data.value?.row.avg_cost ?? null
  const [vmin, vmax] = extentOf(s.map((p) => p[1]))
  // markLine 不参与 y 轴范围计算：成本价落在净值区间外时外扩坐标轴，保证成本线可见
  const bounds = avg !== null && (avg < vmin || avg > vmax) ? niceBounds(Math.min(vmin, avg), Math.max(vmax, avg)) : null
  return {
    color: SERIES_COLORS,
    grid: { left: 12, right: 24, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      valueFormatter: (v: unknown) => fixed(v, 4),
    },
    xAxis: timeAxis(),
    yAxis: {
      type: 'value',
      scale: true,
      min: bounds?.[0],
      max: bounds?.[1],
      axisLabel: AXIS_LABEL,
      splitLine: SPLIT_LINE,
      axisPointer: { label: { precision: 4 } },
    },
    series: [
      {
        name: '净值/价格',
        type: 'line',
        data: s,
        showSymbol: false,
        lineStyle: { width: 1.5 },
        markLine:
          avg === null
            ? undefined
            : {
                silent: true,
                symbol: 'none',
                lineStyle: { type: 'dashed', color: MUTED, width: 1 },
                label: { position: 'insideStartTop', color: MUTED, formatter: `成本 ${avg.toFixed(4)}` },
                data: [{ yAxis: avg }],
              },
        markPoint: {
          symbol: 'circle',
          symbolSize: 8,
          label: { show: false },
          emphasis: {
            label: {
              show: true,
              position: 'top',
              formatter: '{b}',
              color: '#1d2129',
              backgroundColor: '#ffffff',
              borderColor: '#e5e6eb',
              borderWidth: 1,
              borderRadius: 4,
              padding: [4, 8],
            },
          },
          data: eventMarks.value,
        },
      },
      // 基准对比线（归一化到同一起点，蛋卷式叠加）
      ...(data.value?.benchmark_series && data.value.benchmark_series.length >= 2
        ? [{
            name: `${data.value?.benchmark?.name || '基准'}（归一化）`,
            type: 'line' as const,
            data: data.value.benchmark_series,
            showSymbol: false,
            lineStyle: { width: 1, type: 'dashed' as const, color: MUTED },
            itemStyle: { color: MUTED },
          }]
        : []),
    ],
  }
})

/* ---------- PE 分位带：近 5 年 PE 的 20% / 80% 分位划分低估 / 中性 / 高估 ----------
 * 阈值同策略规则书 §1 低估线 / 高估线（pe_percentile_low/high = 20/80），窗口同 pct_5y（近 5 年）。
 * 后端 pe_series 是 PE 原值（非分位），分位线在前端按降采样序列求得，属近似值。 */

const PE_LOW_Q = 0.2
const PE_HIGH_Q = 0.8
const FIVE_YEARS_MS = 5 * 365 * 86_400_000
const BAND = { low: rgba(FALL, 0.1), mid: rgba(MUTED, 0.08), high: rgba(RISE, 0.1) }
const SWATCH = { low: rgba(FALL, 0.4), mid: rgba(MUTED, 0.3), high: rgba(RISE, 0.4) }

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

const peBand = computed(() => {
  const s = data.value?.pe_series ?? []
  if (!s.length) return null
  const cutoff = s[s.length - 1][0] - FIVE_YEARS_MS
  const win = s
    .filter((p) => p[0] >= cutoff)
    .map((p) => p[1])
    .sort((a, b) => a - b)
  const [lo, hi] = niceBounds(...extentOf(s.map((p) => p[1])))
  return { series: s, low: quantile(win, PE_LOW_Q), high: quantile(win, PE_HIGH_Q), lo, hi, current: s[s.length - 1][1] }
})

const peOption = computed<EChartsOption>(() => {
  const b = peBand.value
  if (!b) return {}
  return {
    grid: { left: 12, right: 24, top: 20, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      valueFormatter: (v: unknown) => fixed(v, 2),
    },
    xAxis: timeAxis(),
    yAxis: {
      type: 'value',
      min: b.lo,
      max: b.hi,
      axisLabel: AXIS_LABEL,
      splitLine: SPLIT_LINE,
      axisPointer: { label: { precision: 2 } },
    },
    series: [
      {
        name: 'PE(TTM)',
        type: 'line',
        data: b.series,
        showSymbol: false,
        lineStyle: { width: 1.5, color: SERIES_COLORS[0] },
        itemStyle: { color: SERIES_COLORS[0] },
        markArea: {
          silent: true,
          data: [
            [{ yAxis: b.lo, itemStyle: { color: BAND.low } }, { yAxis: b.low }],
            [{ yAxis: b.low, itemStyle: { color: BAND.mid } }, { yAxis: b.high }],
            [{ yAxis: b.high, itemStyle: { color: BAND.high } }, { yAxis: b.hi }],
          ],
        },
      },
    ],
  }
})

/* ---------- 基准 / 基金透视 / 信号（表格数据走 computed，避免每次渲染新建数组触发表格重排） ---------- */

const benchmarkRows = computed(() => (data.value?.benchmark ? [data.value.benchmark] : []))
const topHoldings = computed(() => data.value?.lookthrough?.holdings.slice(0, 10) ?? [])
const signals = computed(() => data.value?.signals.slice(0, 10) ?? [])

function barWidth(pct: number): string {
  return `${Math.min(100, Math.max(0, pct))}%`
}

function statusType(status: string): 'success' | 'info' | 'warning' {
  if (status === '已确认') return 'success'
  if (status === '已忽略') return 'info'
  return 'warning'
}

/* ---------- 记净值（仅理财 wealth；同日重录覆盖，后端幂等） ---------- */

const navDialog = ref(false)
const navSaving = ref(false)
const navForm = reactive({ date: localDate(), nav: undefined as number | undefined })

function openNav() {
  navForm.date = localDate()
  navForm.nav = data.value?.row.price ?? undefined
  navDialog.value = true
}

function disabledFuture(d: Date): boolean {
  return d.getTime() > Date.now()
}

async function submitNav() {
  if (!navForm.nav || navForm.nav <= 0) return ElMessage.warning('净值需为正数')
  navSaving.value = true
  try {
    await addNav({ instrument_id: id, date: navForm.date, value: navForm.nav })
    ElMessage.success('净值已记录')
    navDialog.value = false
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    navSaving.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader :title="title" :desc="desc">
    <template #tags>
      <template v-if="data">
        <el-tag effect="plain">{{ data.row.type_label }}</el-tag>
        <el-tag v-if="data.account_name" type="info" effect="plain">{{ data.account_name }}</el-tag>
        <el-tag v-if="data.row.state === 'empty'" type="info" effect="light">已清仓</el-tag>
        <el-tag v-else-if="data.row.state === 'noprice'" type="warning" effect="light">缺行情</el-tag>
        <el-tooltip v-if="data.stale" content="行情源超时，当前展示的是本地缓存数据" placement="bottom">
          <el-tag type="warning" effect="light">数据延迟</el-tag>
        </el-tooltip>
      </template>
    </template>
    <template #actions>
      <template v-if="data">
        <el-button :icon="Tickets" @click="goTrades">查看流水</el-button>
        <el-button v-if="data.type === 'wealth'" type="primary" :icon="EditPen" @click="openNav">记净值</el-button>
      </template>
    </template>
  </PageHeader>

  <StateBlock :loading="loading" :error="error" :has-data="!!data" @retry="load">
    <template v-if="data">
      <!-- 指标卡：价格 / 持仓 4 张 + 收益 3 张 -->
      <div class="grid grid-4">
        <el-tooltip :content="data.row.price_date ? `价格日期 ${data.row.price_date}` : '暂无行情'" placement="top">
          <StatCard
            label="最新价"
            :value="data.row.price === null ? '—' : fmtAmount(data.row.price, 4)"
            :sub="data.row.price_date ? `截至 ${data.row.price_date}` : '暂无行情'"
          />
        </el-tooltip>
        <StatCard label="持仓份额" :value="fmtQty(data.row.quantity)" :sub="data.row.state === 'empty' ? '已清仓（留痕）' : '当前持有'" />
        <StatCard label="平均成本" :value="data.row.avg_cost === null ? '—' : fmtAmount(data.row.avg_cost, 4)" sub="持仓均价" />
        <StatCard label="市值" :value="fmtAmount(data.row.market_value)" sub="份额 × 最新价" />
      </div>
      <div class="grid grid-3 panel-gap">
        <StatCard label="浮动盈亏" :value="fmtSigned(data.row.unrealized)" :tone="pnlClass(data.row.unrealized)" sub="收益率">
          <template #sub>
            收益率 <span class="num" :class="pnlClass(data.row.unrealized_pct)">{{ fmtPct(data.row.unrealized_pct) }}</span>
          </template>
        </StatCard>
        <StatCard label="已实现盈亏" :value="fmtSigned(data.row.realized_pnl)" :tone="pnlClass(data.row.realized_pnl)" sub="累计分红">
          <template #sub>
            累计现金分红 <span class="num">{{ fmtAmount(data.row.cash_dividend) }}</span>
          </template>
        </StatCard>
        <el-tooltip content="现金流不足以求解年化" placement="top" :disabled="!data.row.xirr_error">
          <StatCard
            label="XIRR"
            :value="data.row.xirr_error ? '—' : fmtPct(data.row.xirr)"
            :tone="data.row.xirr_error ? '' : pnlClass(data.row.xirr)"
            sub="资金加权年化收益"
          />
        </el-tooltip>
      </div>

      <!-- 标的概况 + 业绩表现 -->
      <div v-if="data.profile || data.performance" class="grid grid-2 panel-gap">
        <div v-if="data.profile" class="panel">
          <div class="panel-title">
            {{ data.profile.title }}概况
            <el-tag size="small" effect="plain" :type="data.type === 'wealth' ? 'success' : data.type === 'bond' ? 'warning' : data.type === 'stock' ? 'danger' : 'primary'">
              {{ data.profile.type_label }}
            </el-tag>
          </div>
          <div class="profile-grid">
            <div v-for="f in data.profile.fields" :key="f.label" class="profile-field">
              <span class="pf-label muted">{{ f.label }}</span>
              <span class="pf-value num">{{ f.value }}</span>
            </div>
          </div>
        </div>
        <div v-if="data.performance && Object.keys(data.performance.returns || {}).length" class="panel">
          <div class="panel-title">
            业绩表现
            <el-tag v-if="data.performance.trend" :type="data.performance.trend === '上行' ? 'danger' : data.performance.trend === '下行' ? 'success' : 'info'" size="small">
              {{ data.performance.trend }}
            </el-tag>
          </div>
          <div class="perf-grid">
            <div v-for="(val, key) in data.performance.returns" :key="key" class="perf-item">
              <span class="pf-label muted">{{ { m1: '近1月', m3: '近3月', m6: '近6月', y1: '近1年', y3: '近3年', all: '成立以来' }[key] || key }}</span>
              <span class="pf-value num" :class="pnlClass(val)">{{ fmtPct(val) }}</span>
            </div>
          </div>
          <div class="risk-row">
            <span v-if="data.performance.risk_level" class="muted">风险等级 <el-tag size="small" :type="data.performance.risk_level.startsWith('R1') || data.performance.risk_level.startsWith('R2') ? 'success' : data.performance.risk_level.startsWith('R3') ? 'warning' : 'danger'">{{ data.performance.risk_level }}</el-tag></span>
            <span v-if="data.performance.sharpe !== null" class="muted">夏普比率 <b class="num">{{ data.performance.sharpe }}</b></span>
            <span v-if="data.performance.volatility !== null" class="muted">年化波动 <b class="num">{{ (data.performance.volatility * 100).toFixed(1) }}%</b></span>
            <span v-if="data.performance.max_drawdown !== null" class="muted">最大回撤 <b class="num" :class="pnlClass(data.performance.max_drawdown)">{{ (data.performance.max_drawdown * 100).toFixed(1) }}%</b></span>
          </div>
        </div>
      </div>

      <!-- 净值曲线 -->
      <div class="panel panel-gap">
        <div class="panel-title">
          <span>净值 / 价格走势 <span class="muted hint">灰色虚线为持仓成本，圆点为交易事件（悬停查看）</span></span>
          <span v-if="periodChange !== null" class="hint">
            区间涨跌 <b class="num" :class="pnlClass(periodChange)">{{ fmtPct(periodChange) }}</b>
          </span>
        </div>
        <EChart v-if="navSeries.length >= 2" :option="navOption" height="400px" />
        <el-empty v-else :image-size="80" description="暂无净值 / 行情序列（需先拉数或录入净值，至少 2 个点）">
          <el-button v-if="data.type === 'wealth'" type="primary" @click="openNav">记净值</el-button>
        </el-empty>
      </div>

      <!-- 基准估值 -->
      <div v-if="data.benchmark" class="panel panel-gap">
        <div class="panel-title">
          基准估值
          <el-button link type="primary" @click="router.push('/valuation')">全部指数</el-button>
        </div>
        <el-table :data="benchmarkRows" size="small">
          <el-table-column label="指数" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.name }}<span v-if="row.code" class="muted code">{{ row.code }}</span>
            </template>
          </el-table-column>
          <el-table-column label="收盘" align="right" min-width="100">
            <template #default="{ row }">{{ fmtAmount(row.close) }}</template>
          </el-table-column>
          <el-table-column label="PE(TTM)" align="right" min-width="90">
            <template #default="{ row }">{{ fixed(row.pe_ttm, 2) }}</template>
          </el-table-column>
          <el-table-column label="5年分位" align="right" min-width="90">
            <template #default="{ row }">{{ fmtPlainPct(row.pct_5y, 0) }}</template>
          </el-table-column>
          <el-table-column label="全历史分位" align="right" min-width="100">
            <template #default="{ row }">{{ fmtPlainPct(row.pct_all, 0) }}</template>
          </el-table-column>
          <el-table-column label="股息率" align="right" min-width="90">
            <template #default="{ row }">{{ fmtPlainPct(row.dyield, 2) }}</template>
          </el-table-column>
          <el-table-column label="5年回撤" align="right" min-width="90">
            <template #default="{ row }">{{ row.drawdown_5y === null ? '—' : (row.drawdown_5y * 100).toFixed(1) + '%' }}</template>
          </el-table-column>
        </el-table>
      </div>

      <!-- PE 分位带 -->
      <div v-if="peBand" class="panel panel-gap">
        <div class="panel-title">
          <span>
            PE(TTM) 分位带
            <span class="muted hint">{{ data.benchmark?.name }} · 按近 5 年 PE 的 20% / 80% 分位划分</span>
          </span>
          <span class="hint">当前 PE <b class="num">{{ peBand.current.toFixed(2) }}</b></span>
        </div>
        <EChart :option="peOption" height="300px" />
        <div class="band-legend">
          <span><i :style="{ background: SWATCH.low }" />低估区 PE ≤ {{ peBand.low.toFixed(2) }}</span>
          <span><i :style="{ background: SWATCH.mid }" />中性区</span>
          <span><i :style="{ background: SWATCH.high }" />高估区 PE ≥ {{ peBand.high.toFixed(2) }}</span>
        </div>
      </div>

      <!-- 基金透视 -->
      <div v-if="data.lookthrough" class="panel panel-gap">
        <div class="panel-title">
          <span>基金透视 <span class="muted hint">{{ data.lookthrough.period }} 季报披露</span></span>
          <span class="hint">行业配置合计占净值 <b class="num">{{ fmtPlainPct(data.lookthrough.industry_total_pct) }}</b></span>
        </div>
        <div class="grid grid-2">
          <div>
            <div class="sub-title">前十大持仓</div>
            <el-table :data="topHoldings" size="small" empty-text="暂无持仓披露">
              <el-table-column prop="rank" label="#" width="48" align="center" />
              <el-table-column prop="code" label="代码" width="90" />
              <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
              <el-table-column label="占净值" align="right" width="90">
                <template #default="{ row }">{{ fmtPlainPct(row.weight_pct, 2) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div>
            <div class="sub-title">行业分布</div>
            <div v-if="data.lookthrough.industry.length" class="industry">
              <div v-for="it in data.lookthrough.industry" :key="it.name" class="ind-row">
                <span class="ind-name" :title="it.name">{{ it.name }}</span>
                <span class="ind-track"><span class="ind-bar" :style="{ width: barWidth(it.weight_pct) }" /></span>
                <span class="ind-pct num">{{ fmtPlainPct(it.weight_pct, 2) }}</span>
              </div>
            </div>
            <el-empty v-else :image-size="60" description="暂无行业披露" />
          </div>
        </div>
      </div>

      <!-- 分红历史 -->
      <div v-if="data.dividends && data.dividends.length" class="panel panel-gap">
        <div class="panel-title">
          分红历史
          <span class="muted hint">共 {{ data.dividends.length }} 次，累计 {{ fmtAmount(data.dividends.reduce((s, d) => s + d.amount, 0)) }} 元</span>
        </div>
        <el-table :data="data.dividends" size="small">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="row.type === '现金分红' ? 'success' : 'primary'" size="small" effect="plain">{{ row.type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="份额" align="right" width="100">
            <template #default="{ row }">{{ fmtQty(row.quantity) }}</template>
          </el-table-column>
          <el-table-column label="每份分红" align="right" width="100">
            <template #default="{ row }">{{ fmtAmount(row.price, 4) }}</template>
          </el-table-column>
          <el-table-column label="金额" align="right" width="110">
            <template #default="{ row }">
              <span class="num" :class="pnlClass(row.amount)">{{ fmtSigned(row.amount) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        </el-table>
      </div>

      <!-- 交易事件 + 该标的信号 -->
      <div class="grid grid-2 panel-gap">
        <div class="panel">
          <div class="panel-title">
            <span>交易事件 <span class="muted hint">共 {{ eventsDesc.length }} 笔</span></span>
            <el-button link type="primary" @click="goTrades">查看流水</el-button>
          </div>
          <div v-if="eventsDesc.length" class="timeline">
            <el-timeline>
              <el-timeline-item v-for="(ev, i) in eventsDesc" :key="`${ev.ts}-${i}`" :timestamp="fmtTs(ev.ts)" :color="eventColor(ev.kind)">
                {{ ev.label }}
              </el-timeline-item>
            </el-timeline>
          </div>
          <el-empty v-else :image-size="60" description="暂无交易事件" />
        </div>
        <div class="panel">
          <div class="panel-title">
            该标的信号
            <el-button link type="primary" @click="router.push('/signals')">全部信号</el-button>
          </div>
          <el-table :data="signals" size="small" empty-text="暂无该标的信号">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column prop="action" label="建议" min-width="160" show-overflow-tooltip />
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="statusType((row as Signal).status)" size="small" effect="plain">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </template>
  </StateBlock>

  <!-- 404：StateBlock 错误态只带「重试」，标的不存在时补一个返回入口 -->
  <div v-if="notFound && !loading" class="not-found">
    <el-button type="primary" plain @click="router.push('/')">返回总览</el-button>
  </div>

  <el-dialog v-model="navDialog" :title="`记净值 · ${title}`" width="420px" :close-on-click-modal="false">
    <el-form label-width="64px" @submit.prevent>
      <el-form-item label="日期">
        <el-date-picker
          v-model="navForm.date"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          :disabled-date="disabledFuture"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="净值">
        <el-input-number v-model="navForm.nav" :min="0" :precision="4" :controls="false" placeholder="如 1.0234" style="width: 100%" />
      </el-form-item>
    </el-form>
    <div class="muted dialog-hint">同一日期重复录入会覆盖原值</div>
    <template #footer>
      <el-button @click="navDialog = false">取消</el-button>
      <el-button type="primary" :loading="navSaving" @click="submitNav">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
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
.pf-label {
  font-size: 12px;
}
.pf-value {
  font-size: 15px;
  font-weight: 600;
}
.risk-row {
  display: flex;
  gap: 24px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--iv-border);
  font-size: 13px;
}
/* 全局 .panel + .panel 的叠放间距不适用于栅格内并排的面板 / 指标卡（否则第 2 列起整体下沉） */
.grid > .panel {
  margin-top: 0;
}
.hint {
  font-size: 12px;
  font-weight: 400;
}
.hint b {
  margin-left: 4px;
  font-weight: 600;
}
.code {
  margin-left: 6px;
  font-size: 12px;
}
.sub-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--iv-text-2);
  margin-bottom: 10px;
}
.band-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--iv-text-2);
}
.band-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.band-legend i {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
}
.industry {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ind-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) 64px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.ind-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--iv-text-2);
}
.ind-track {
  display: block;
  height: 10px;
  border-radius: 5px;
  overflow: hidden;
  background: #f2f3f5;
}
.ind-bar {
  display: block;
  height: 100%;
  border-radius: 5px;
  background: var(--iv-primary);
}
.ind-pct {
  text-align: right;
}
.timeline {
  max-height: 420px;
  overflow-y: auto;
  padding: 4px 8px 0 2px;
}
.not-found {
  display: flex;
  justify-content: center;
}
.dialog-hint {
  font-size: 12px;
  padding-left: 64px;
}
</style>
