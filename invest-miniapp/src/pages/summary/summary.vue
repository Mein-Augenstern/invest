<script setup lang="ts">
import { ref, getCurrentInstance } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { getSummary, type SummaryRow } from '@/api/invest'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { fmtAmount, fmtSigned, pnlClass } from '@/utils/format'

// R3 资产总曲线（与月度统计同源的逐日市值）
const curve = ref<[number, number][]>([])
const curveRange = ref<'90' | '365' | 'all'>('365')
const instance = getCurrentInstance()

async function loadCurve() {
  try {
    const days = curveRange.value === 'all' ? 3650 : Number(curveRange.value)
    const d = await request<{ curve: [number, number][] }>({ url: '/asset-curve', params: { days } })
    curve.value = d.curve
    setTimeout(() => drawAssetCurve(), 300)
  } catch {
    /* 曲线是增强视图，失败静默 */
  }
}

function drawAssetCurve() {
  const pts = curve.value
  if (pts.length < 2) return
  const ctx = uni.createCanvasContext('assetChart', instance?.proxy)
  // 新基础库用 getWindowInfo（getSystemInfoSync 已废弃告警）
  const win = uni.getWindowInfo ? uni.getWindowInfo() : uni.getSystemInfoSync()
  const W = (win.windowWidth / 750) * 686
  const H = (win.windowWidth / 750) * 340
  const padL = 8, padR = 62, padT = 14, padB = 8
  const vs = pts.map((p) => p[1])
  let vmin = Infinity
  let vmax = -Infinity
  for (const v of vs) {
    if (v < vmin) vmin = v
    if (v > vmax) vmax = v
  }
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0] || t0 + 1
  const x = (t: number) => padL + ((t - t0) / (t1 - t0)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - vmin) / (vmax - vmin || 1)) * (H - padT - padB)
  ctx.setStrokeStyle('#e5e6eb')
  ctx.setLineWidth(0.5)
  for (let i = 0; i <= 2; i++) {
    const gy = padT + (i * (H - padT - padB)) / 2
    ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke()
  }
  ctx.setStrokeStyle('#1652a8')
  ctx.setLineWidth(1.5)
  ctx.beginPath()
  pts.forEach(([t, v], i) => (i === 0 ? ctx.moveTo(x(t), y(v)) : ctx.lineTo(x(t), y(v))))
  ctx.stroke()
  ctx.setFillStyle('#86909c')
  ctx.setFontSize(9)
  ctx.fillText(String(Math.round(vmax)), W - padR + 4, y(vmax) + 3)
  ctx.fillText(String(Math.round(vmin)), W - padR + 4, y(vmin) + 3)
  ctx.draw()
}

function switchCurve(r: '90' | '365' | 'all') {
  curveRange.value = r
  loadCurve()
}

// R4 收益日历
type ViewMode = 'list' | 'calendar'
const viewMode = ref<ViewMode>('list')
const calMonth = ref(new Date().toISOString().slice(0, 7))
const calDays = ref<Record<string, number>>({})
const calTotal = ref(0)

async function loadCalendar() {
  try {
    const d = await request<{ days: Record<string, number>; month_total: number }>({
      url: '/daily-pnl', params: { month: calMonth.value },
    })
    calDays.value = d.days
    calTotal.value = d.month_total
  } catch {
    /* 静默 */
  }
}

function switchView(v: ViewMode) {
  viewMode.value = v
  if (v === 'calendar') loadCalendar()
}

function shiftMonth(delta: number) {
  const [y, m] = calMonth.value.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  calMonth.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  loadCalendar()
}

/** 月历格子：周一开头，返回 42 格（前导空格 + 日期数字 + 当日收益） */
const calendarCells = computed(() => {
  const [y, m] = calMonth.value.split('-').map(Number)
  const first = new Date(y, m - 1, 1)
  const lead = (first.getDay() + 6) % 7 // 周一=0
  const dim = new Date(y, m, 0).getDate()
  const cells: { day: number | null; pnl: number | null; key: string }[] = []
  for (let i = 0; i < lead; i++) cells.push({ day: null, pnl: null, key: 'x' + i })
  for (let d = 1; d <= dim; d++) {
    const key = `${calMonth.value}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, pnl: key in calDays.value ? calDays.value[key] : null, key })
  }
  return cells
})

const loading = ref(true)
const months = ref<SummaryRow[]>([])
const years = ref<SummaryRow[]>([])
const range = ref(12)
const cacheTime = ref('')
const CACHE_KEY = 'invest_cache_summary'

console.warn('[summary] setup running')
function readCache() {
  try {
    const raw = uni.getStorageSync(CACHE_KEY)
    if (raw) {
      const obj = JSON.parse(raw)
      months.value = obj.months || []
      years.value = obj.years || []
      cacheTime.value = obj.at || ''
    }
  } catch {
    /* 忽略损坏缓存 */
  }
}

async function load() {
  loading.value = true
  try {
    await ensureLogin()
    const data = await getSummary(range.value)
    months.value = data.months
    years.value = data.years
    uni.setStorageSync(CACHE_KEY, JSON.stringify({ months: data.months, years: data.years, at: new Date().toTimeString().slice(0, 5) }))
    cacheTime.value = ''
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

readCache()

function switchRange(n: number) {
  range.value = n
  load()
}

function onOpenBacktest() {
  uni.navigateTo({ url: '/pages/backtest/backtest' })
}

function onOpenAnnual() {
  uni.navigateTo({ url: '/pages/annual/annual' })
}

/** 月份显示为中文月份（2026-02 → 2月） */
function monthLabel(m: string): string {
  return `${parseInt(m.slice(5, 7), 10)}月`
}

onPullDownRefresh(async () => {
  await Promise.all([load(), loadCurve()])
  uni.stopPullDownRefresh()
})
onShow(() => {
  load()
  loadCurve()
})
</script>

<template>
  <view class="page">
    <!-- R3 资产总曲线 -->
    <view class="card">
      <view class="card-title">
        总资产走势
        <text class="curve-range">
          <text :class="{ on: curveRange === '90' }" @tap="switchCurve('90')">3月</text>
          <text :class="{ on: curveRange === '365' }" @tap="switchCurve('365')">1年</text>
          <text :class="{ on: curveRange === 'all' }" @tap="switchCurve('all')">全部</text>
        </text>
      </view>
      <canvas v-if="curve.length >= 2" canvas-id="assetChart" id="assetChart" class="asset-chart" />
      <view v-else class="muted no-curve">暂无足够历史（录入流水并拉取净值后生成）</view>
    </view>

    <!-- 年度汇总卡 -->
    <view v-for="y in years" :key="y.year" class="card">
      <view class="card-title">{{ y.year }} 年汇总</view>
      <view class="year-grid">
        <view class="cell">
          <text class="muted c-label">净投入</text>
          <text class="c-val">{{ fmtAmount(y.net_invested) }}</text>
        </view>
        <view class="cell">
          <text class="muted c-label">浮盈变化</text>
          <text :class="['c-val', pnlClass(y.pnl_change)]">{{ fmtSigned(y.pnl_change) }}</text>
        </view>
        <view class="cell">
          <text class="muted c-label">现金分红</text>
          <text class="c-val">{{ fmtAmount(y.cash_div) }}</text>
        </view>
        <view class="cell">
          <text class="muted c-label">已实现</text>
          <text :class="['c-val', pnlClass(y.realized)]">{{ fmtSigned(y.realized) }}</text>
        </view>
      </view>
    </view>

    <!-- 视图切换（列表/日历）+ 回测入口 -->
    <view class="range-row">
      <text class="bt-link" @tap="onOpenBacktest">策略回测 ›</text>
      <text class="bt-link" @tap="onOpenAnnual">年度复盘 ›</text>
      <text :class="{ on: viewMode === 'list' }" @tap="switchView('list')">月度</text>
      <text :class="{ on: viewMode === 'calendar' }" @tap="switchView('calendar')">日历</text>
      <template v-if="viewMode === 'list'">
        <text :class="{ on: range === 6 }" @tap="switchRange(6)">近6月</text>
        <text :class="{ on: range === 12 }" @tap="switchRange(12)">近12月</text>
      </template>
    </view>

    <!-- R4 收益日历 -->
    <view v-if="viewMode === 'calendar'" class="card">
      <view class="cal-head">
        <text class="cal-nav" @tap="shiftMonth(-1)">‹</text>
        <text class="cal-month">{{ calMonth }}</text>
        <text class="cal-nav" @tap="shiftMonth(1)">›</text>
        <text :class="['cal-total', calTotal > 0 ? 'danger' : calTotal < 0 ? 'success' : '']">
          {{ calTotal > 0 ? '+' : '' }}{{ calTotal }}
        </text>
      </view>
      <view class="cal-grid">
        <text v-for="w in ['一','二','三','四','五','六','日']" :key="w" class="cal-week">{{ w }}</text>
        <view v-for="c in calendarCells" :key="c.key" class="cal-cell" :class="{ empty: !c.day }">
          <text v-if="c.day" class="cal-day">{{ c.day }}</text>
          <text v-if="c.pnl !== null" :class="['cal-pnl', c.pnl > 0 ? 'danger' : c.pnl < 0 ? 'success' : 'muted']">
            {{ c.pnl > 0 ? '+' : '' }}{{ Math.round(c.pnl) }}
          </text>
        </view>
      </view>
      <view class="muted note">当日收益 = Δ市值 − 当日净投入（红盈绿亏）；无净值日期不显示</view>
    </view>

    <!-- 月度列表 -->
    <view v-if="viewMode === 'list'" class="card list-card">
      <view class="m-head">
        <text class="h-month">月份</text>
        <text class="h-num">净投入</text>
        <text class="h-num">浮盈变化</text>
        <text class="h-num">期末市值</text>
      </view>
      <view v-if="!months.length && !loading" class="empty">暂无数据（先录入流水并拉取净值）</view>
      <view v-for="m in months" :key="m.month" class="m-row">
        <text class="h-month">{{ m.month.slice(0, 4).slice(2) }}年{{ monthLabel(m.month) }}</text>
        <text class="h-num">{{ fmtAmount(m.net_invested, 0) }}</text>
        <text :class="['h-num', pnlClass(m.pnl_change)]">{{ fmtSigned(m.pnl_change, 0) }}</text>
        <text class="h-num">{{ fmtAmount(m.market_value, 0) }}</text>
      </view>
      <view class="muted note">浮盈变化 = 月末市值 − 月初市值 − 当月净投入（含已实现与分红的完整口径见年度卡）</view>
    </view>
  </view>
</template>

<style scoped>
.cal-head {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-bottom: 12rpx;
}
.cal-nav {
  font-size: 36rpx;
  color: #4e5969;
  padding: 0 12rpx;
}
.cal-month {
  font-size: 30rpx;
  font-weight: 500;
}
.cal-total {
  margin-left: auto;
  font-size: 30rpx;
  font-weight: 500;
}
.cal-grid {
  display: flex;
  flex-wrap: wrap;
}
.cal-week {
  width: 14.28%;
  text-align: center;
  font-size: 22rpx;
  color: #86909c;
  padding: 8rpx 0;
}
.cal-cell {
  width: 14.28%;
  height: 88rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-bottom: 1rpx solid #f5f6f7;
}
.cal-cell.empty {
  border-bottom: none;
}
.cal-day {
  font-size: 22rpx;
  color: #86909c;
}
.cal-pnl {
  font-size: 22rpx;
  margin-top: 2rpx;
}
.curve-range {
  float: right;
  display: flex;
  gap: 16rpx;
}
.curve-range text {
  font-size: 24rpx;
  color: #86909c;
}
.curve-range text.on {
  color: #1652a8;
  font-weight: 500;
}
.asset-chart {
  width: 686rpx;
  height: 340rpx;
}
.no-curve {
  font-size: 24rpx;
  padding: 40rpx 0;
  text-align: center;
}
.year-grid {
  display: flex;
  flex-wrap: wrap;
}
.cell {
  width: 50%;
  display: flex;
  flex-direction: column;
  padding: 12rpx 0;
}
.c-label {
  font-size: 24rpx;
}
.c-val {
  font-size: 34rpx;
  font-weight: 500;
  margin-top: 6rpx;
}
.range-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 24rpx;
  margin: 20rpx 24rpx 0;
}
.bt-link {
  margin-right: auto;
  font-size: 26rpx;
  color: #1652a8;
}
.range-row text {
  font-size: 26rpx;
  color: #86909c;
  border: 1rpx solid #e5e6eb;
  border-radius: 8rpx;
  padding: 4rpx 20rpx;
}
.range-row text.on {
  color: #1652a8;
  border-color: #1652a8;
  background: #eef3fb;
}
.list-card {
  padding: 16rpx 24rpx;
}
.m-head,
.m-row {
  display: flex;
  align-items: center;
  padding: 14rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.m-head {
  color: #86909c;
  font-size: 24rpx;
}
.m-row {
  font-size: 26rpx;
}
.m-row:last-of-type {
  border-bottom: none;
}
.h-month {
  flex: 1.1;
}
.h-num {
  flex: 1;
  text-align: right;
}
.note {
  font-size: 22rpx;
  padding-top: 12rpx;
  line-height: 1.6;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 0;
}
</style>
