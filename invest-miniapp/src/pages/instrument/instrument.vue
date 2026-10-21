<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getCurrentInstance } from 'vue'
import { getInstrumentDetail, addNav } from '@/api/invest'
import { showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { fmtAmount, fmtSigned, fmtPct, pnlClass, fmtQty } from '@/utils/format'
import type { HoldingDetail } from '@/types'

const d = ref<HoldingDetail | null>(null)
const loading = ref(true)
const instance = getCurrentInstance()
// 十字线读数（P12）：canvas 内画竖线+点，具体数值渲染成下方文本（比 canvas 小字可读）
const crossLabel = ref('')

// 净值曲线期间涨跌（首→尾）
const periodChange = computed(() => {
  const s = d.value?.nav_series || []
  if (s.length < 2) return null
  const first = s[0][1]
  const last = s[s.length - 1][1]
  return first > 0 ? last / first - 1 : null
})

async function load(id: string) {
  loading.value = true
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用）
    d.value = await getInstrumentDetail(id)
    // 等渲染出 canvas 节点再画
    setTimeout(() => drawChart(), 300)
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

/** 毫秒时间戳 → 本地日期（toISOString 会按 UTC 偏移一天） */
function fmtTs(ts: number): string {
  const dt = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`
}

/** 净值曲线：uni 旧 CanvasContext（mp-weixin/H5 双端可用）。企业风：细线、浅网格、无渐变。
 * P12：touch 传入 crossTs 时叠加十字线（就近吸附最近数据点）。 */
let chartGeom: {
  series: [number, number][]
  W: number
  H: number
  padL: number
  padR: number
  padT: number
  padB: number
  t0: number
  t1: number
  vmin: number
  vmax: number
} | null = null

function drawChart(crossTs?: number) {
  const series = d.value?.nav_series || []
  if (series.length < 2) return
  const ctx = uni.createCanvasContext('navChart', instance?.proxy)
  // canvas css 尺寸为 686×420 rpx，按屏宽换算逻辑像素，避免不同机型拉伸
  // 新基础库用 getWindowInfo（getSystemInfoSync 已废弃告警）
  const win = uni.getWindowInfo ? uni.getWindowInfo() : uni.getSystemInfoSync()
  const W = (win.windowWidth / 750) * 686
  const H = (win.windowWidth / 750) * 420
  const padL = 8
  const padR = 58
  const padT = 14
  const padB = 20
  const values = series.map((p) => p[1])
  // 循环求极值（大数组 spread 在小程序编译 helper 下报 Iterator incompatible）
  let vmin = Infinity
  let vmax = -Infinity
  for (const v of values) {
    if (v < vmin) vmin = v
    if (v > vmax) vmax = v
  }
  if (vmax - vmin < 1e-9) {
    vmax += 1
    vmin -= 1
  }
  const t0 = series[0][0]
  const t1 = series[series.length - 1][0] || t0 + 1
  const x = (ts: number) => padL + ((ts - t0) / (t1 - t0)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - vmin) / (vmax - vmin)) * (H - padT - padB)
  chartGeom = { series, W, H, padL, padR, padT, padB, t0, t1, vmin, vmax }

  // 网格（3 条水平参考线）
  ctx.setStrokeStyle('#e5e6eb')
  ctx.setLineWidth(0.5)
  for (let i = 0; i <= 2; i++) {
    const gy = padT + (i * (H - padT - padB)) / 2
    ctx.beginPath()
    ctx.moveTo(padL, gy)
    ctx.lineTo(W - padR, gy)
    ctx.stroke()
  }
  // 净值线
  ctx.setStrokeStyle('#1652a8')
  ctx.setLineWidth(1.5)
  ctx.beginPath()
  series.forEach((p, i) => {
    const px = x(p[0])
    const py = y(p[1])
    if (i === 0) ctx.moveTo(px, py)
    else ctx.lineTo(px, py)
  })
  ctx.stroke()
  // 交易事件标记（点落在时间范围内的才画）
  ctx.setFillStyle('#d54941')
  const seen = new Set<number>()
  for (const ev of d.value?.events || []) {
    const ex = x(ev.ts)
    if (ex < padL || ex > W - padR) continue
    const key = Math.round(ex)
    if (seen.has(key)) continue // 同位置只画一个点
    seen.add(key)
    ctx.beginPath()
    ctx.arc(ex, padT + 4, 2.5, 0, Math.PI * 2)
    ctx.fill()
  }
  // 右侧最值标注
  ctx.setFillStyle('#86909c')
  ctx.setFontSize(9)
  ctx.setTextAlign('left')
  ctx.fillText(vmax.toFixed(4), W - padR + 4, y(vmax) + 3)
  ctx.fillText(vmin.toFixed(4), W - padR + 4, y(vmin) + 3)

  // 十字线：就近吸附最近数据点，画竖线+点；数值渲染到 canvas 下方文本
  if (crossTs !== undefined) {
    let nearest = series[0]
    let best = Infinity
    for (const p of series) {
      const dist = Math.abs(p[0] - crossTs)
      if (dist < best) {
        best = dist
        nearest = p
      }
    }
    const cx = x(nearest[0])
    const cy = y(nearest[1])
    ctx.setStrokeStyle('#d54941')
    ctx.setLineWidth(0.8)
    ctx.beginPath()
    ctx.moveTo(cx, padT)
    ctx.lineTo(cx, H - padB)
    ctx.stroke()
    ctx.setFillStyle('#d54941')
    ctx.beginPath()
    ctx.arc(cx, cy, 3, 0, Math.PI * 2)
    ctx.fill()
    const dt = new Date(nearest[0])
    const p2 = (n: number) => String(n).padStart(2, '0')
    crossLabel.value = `${dt.getFullYear()}-${p2(dt.getMonth() + 1)}-${p2(dt.getDate())} · 净值/价 ${nearest[1].toFixed(4)}`
  } else {
    crossLabel.value = ''
  }
  // R6 成本线：均价成本画水平虚线（在值域内时）——竞品标配的盈亏直觉参照
  const avg = d.value?.row?.avg_cost
  if (avg !== null && avg !== undefined && avg >= vmin && avg <= vmax) {
    const cy0 = y(avg)
    ctx.setStrokeStyle('#86909c')
    ctx.setLineWidth(0.8)
    ctx.setLineDash([4, 3])
    ctx.beginPath()
    ctx.moveTo(padL, cy0)
    ctx.lineTo(W - padR, cy0)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.setFillStyle('#86909c')
    ctx.setFontSize(9)
    ctx.fillText(`成本 ${avg.toFixed(4)}`, padL + 4, cy0 - 4)
  }
  ctx.draw()
}

/** touch → 时间戳（W/H 已是 css 像素坐标，touch.x 同坐标系，无需再换算） */
function onChartTouch(e: { touches?: { x?: number; y?: number; clientX?: number }[] }) {
  const g = chartGeom
  const touch = e.touches && e.touches[0]
  if (!g || !touch) return
  const rawX = typeof touch.x === 'number' ? touch.x : touch.clientX
  if (typeof rawX !== 'number') return
  const ts = g.t0 + ((rawX - g.padL) / (g.W - g.padL - g.padR)) * (g.t1 - g.t0)
  drawChart(ts)
}

function onChartTouchEnd() {
  drawChart() // 抬手清除十字线
}

// 理财净值录入
const showNavForm = ref(false)
const navForm = ref({ date: new Date().toISOString().slice(0, 10), value: '' })
const navSubmitting = ref(false)

function openNavForm() {
  navForm.value = { date: new Date().toISOString().slice(0, 10), value: d.value?.row.price ? String(d.value.row.price) : '' }
  showNavForm.value = true
}

function onPickNavDate(e: { detail: { value: string } }) {
  navForm.value.date = e.detail.value
}

async function submitNav() {
  const v = Number(navForm.value.value)
  if (!navForm.value.value || Number.isNaN(v) || v <= 0) {
    return uni.showToast({ title: '净值需为正数', icon: 'none' })
  }
  navSubmitting.value = true
  try {
    await addNav({ instrument_id: d.value!.id, date: navForm.value.date, value: v })
    uni.showToast({ title: '净值已更新', icon: 'success' })
    showNavForm.value = false
    load(d.value!.id)
  } catch (e) {
    showApiError(e)
  } finally {
    navSubmitting.value = false
  }
}

onLoad((q) => {
  if (q && q.id) load(String(q.id))
})
</script>

<template>
  <view class="page">
    <!-- 指标头 -->
    <view class="card">
      <view class="head">
        <view>
          <view class="title">{{ d?.name || '...' }}</view>
          <view class="muted sub">
            {{ d?.row.type_label }} · {{ d?.account_name }}
            <text v-if="d?.code"> · {{ d.code }}</text>
          </view>
        </view>
        <button v-if="d?.type === 'wealth'" class="mini-btn" @tap="openNavForm">记净值</button>
      </view>
      <view class="metrics">
        <view class="metric">
          <text class="muted m-label">{{ d?.row.price_label || '现价' }}</text>
          <text class="m-val">{{ d?.row.price ?? '—' }}</text>
          <text class="muted m-date">{{ d?.row.price_date }}</text>
        </view>
        <view class="metric">
          <text class="muted m-label">市值</text>
          <text class="m-val">{{ fmtAmount(d?.row.market_value) }}</text>
          <text :class="['m-date', pnlClass(d?.row.unrealized)]">盈亏 {{ fmtSigned(d?.row.unrealized) }}</text>
        </view>
        <view class="metric">
          <text class="muted m-label">XIRR</text>
          <text :class="['m-val', pnlClass(d?.row.xirr)]">
            {{ d?.row.xirr === null || d?.row.xirr === undefined ? '—' : fmtPct(d.row.xirr) }}
          </text>
          <text class="muted m-date">成本 {{ d?.row.avg_cost ?? '—' }}</text>
        </view>
      </view>
    </view>

    <!-- 净值曲线 -->
    <view class="card">
      <view class="card-title">
        净值/行情曲线
        <text v-if="periodChange !== null" :class="['period', pnlClass(periodChange)]">
          期间 {{ fmtPct(periodChange) }}
        </text>
      </view>
      <canvas
        v-if="(d?.nav_series?.length || 0) >= 2"
        canvas-id="navChart"
        id="navChart"
        class="chart"
        @touchstart="onChartTouch"
        @touchmove="onChartTouch"
        @touchend="onChartTouchEnd"
      />
      <view v-if="crossLabel" class="cross-label">{{ crossLabel }}</view>
      <view v-if="(d?.nav_series?.length || 0) >= 2" class="muted chart-hint">按住曲线可查看某日净值</view>
      <view v-else class="muted no-chart">序列不足（需先拉数或录入净值，至少 2 个点）</view>
    </view>

    <!-- 基准估值 -->
    <view v-if="d?.benchmark" class="card">
      <view class="card-title">基准 · {{ d.benchmark.name }}</view>
      <view class="kv"><text class="muted">PE(TTM)</text><text>{{ d.benchmark.pe_ttm ?? '—' }}</text></view>
      <view class="kv"><text class="muted">PE分位(5y/全历史)</text><text>{{ Math.round(d.benchmark.pct_5y ?? 0) }}% / {{ Math.round(d.benchmark.pct_all ?? 0) }}%</text></view>
      <view class="kv"><text class="muted">股息率</text><text>{{ d.benchmark.dyield ?? '—' }}%</text></view>
      <view class="kv"><text class="muted">距5年高点回撤</text><text>{{ d.benchmark.drawdown_5y === null ? '—' : (d.benchmark.drawdown_5y * 100).toFixed(1) + '%' }}</text></view>
      <!-- S5 PE 5y 分位带：0-100 横条 + 指针（低绿高红三段） -->
      <view v-if="d.benchmark.pct_5y !== null" class="pct-band">
        <view class="band-track">
          <view class="band-seg low" />
          <view class="band-seg mid" />
          <view class="band-seg high" />
          <view class="band-pin" :style="{ left: Math.min(100, Math.max(0, d.benchmark.pct_5y)) + '%' }" />
        </view>
        <view class="band-labels">
          <text>低估</text><text>中位</text><text>高估</text>
        </view>
      </view>
    </view>

    <!-- 基金透视 -->
    <view v-if="d?.lookthrough" class="card">
      <view class="card-title">持仓穿透（{{ d.lookthrough.period }}季报）</view>
      <view v-for="h in d.lookthrough.holdings.slice(0, 10)" :key="h.rank" class="kv">
        <text class="muted">{{ h.rank }}. {{ h.name }}</text>
        <text>{{ h.weight_pct }}%</text>
      </view>
      <view class="muted industry">
        行业：{{ d.lookthrough.industry.map((i) => `${i.name} ${i.weight_pct}%`).join(' · ') }}
      </view>
    </view>

    <!-- 交易事件 -->
    <view v-if="d?.events?.length" class="card">
      <view class="card-title">交易事件（{{ d.events.length }}）</view>
      <view v-for="(ev, i) in d.events.slice().reverse()" :key="i" class="kv">
        <text class="muted">{{ fmtTs(ev.ts) }}</text>
        <text>{{ ev.label }}</text>
      </view>
    </view>

    <!-- 相关信号 -->
    <view v-if="d?.signals?.length" class="card">
      <view class="card-title">相关信号</view>
      <view v-for="s in d.signals" :key="s.id" class="kv">
        <text class="muted">{{ s.date }} {{ s.rule }}</text>
        <text>{{ s.action }}（{{ s.status }}）</text>
      </view>
    </view>

    <!-- 记净值弹层 -->
    <view v-if="showNavForm" class="mask" @tap="showNavForm = false">
      <view class="sheet" @tap.stop>
        <view class="sheet-title">录入净值 · {{ d?.name }}</view>
        <view class="form-row">
          <text class="form-label">日期</text>
          <picker mode="date" :value="navForm.date" @change="onPickNavDate">
            <view class="form-value">{{ navForm.date }}</view>
          </picker>
        </view>
        <view class="form-row">
          <text class="form-label">净值</text>
          <input v-model="navForm.value" type="digit" class="form-input" placeholder="如 1.0234" />
        </view>
        <button class="primary-btn block" :disabled="navSubmitting" @tap="submitNav">
          {{ navSubmitting ? '提交中' : '保存（同日重录覆盖）' }}
        </button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.title {
  font-size: 34rpx;
  font-weight: 600;
}
.sub {
  font-size: 24rpx;
  margin-top: 8rpx;
}
.mini-btn {
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #1652a8;
  font-size: 24rpx;
  line-height: 2.2;
  padding: 0 24rpx;
  margin: 0;
}
.metrics {
  display: flex;
  margin-top: 24rpx;
}
.metric {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.m-label {
  font-size: 24rpx;
}
.m-val {
  font-size: 32rpx;
  font-weight: 500;
  margin-top: 6rpx;
}
.m-date {
  font-size: 22rpx;
  margin-top: 6rpx;
}
.period {
  font-size: 24rpx;
  margin-left: 16rpx;
}
.chart {
  width: 686rpx;
  height: 420rpx;
}
.cross-label {
  font-size: 24rpx;
  color: #d54941;
  margin-top: 8rpx;
}
.chart-hint {
  font-size: 22rpx;
  margin-top: 4rpx;
}
.no-chart {
  padding: 40rpx 0;
  text-align: center;
  font-size: 24rpx;
}
.kv {
  display: flex;
  justify-content: space-between;
  font-size: 26rpx;
  padding: 14rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.kv:last-child {
  border-bottom: none;
}
.pct-band {
  padding: 16rpx 0 6rpx;
}
.band-track {
  position: relative;
  height: 16rpx;
  border-radius: 8rpx;
  overflow: hidden;
  display: flex;
}
.band-seg {
  flex: 1;
}
.band-seg.low { background: #2e9e5b; }
.band-seg.mid { background: #d46b08; }
.band-seg.high { background: #d54941; }
.band-pin {
  position: absolute;
  top: -6rpx;
  width: 6rpx;
  height: 28rpx;
  background: #1d2129;
  border-radius: 3rpx;
  transform: translateX(-3rpx);
}
.band-labels {
  display: flex;
  justify-content: space-between;
  font-size: 20rpx;
  color: #86909c;
  margin-top: 6rpx;
}
.industry {
  font-size: 22rpx;
  line-height: 1.8;
  margin-top: 12rpx;
}
.mask {
  position: fixed;
  inset: 0;
  background: rgba(29, 33, 41, 0.45);
  display: flex;
  align-items: flex-end;
  z-index: 100;
}
.sheet {
  width: 100%;
  background: #ffffff;
  border-radius: 24rpx 24rpx 0 0;
  padding: 32rpx 32rpx calc(32rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
}
.sheet-title {
  font-size: 32rpx;
  font-weight: 500;
  margin-bottom: 20rpx;
}
.form-row {
  display: flex;
  align-items: center;
  border-bottom: 1rpx solid #f0f1f3;
  padding: 20rpx 0;
}
.form-label {
  width: 120rpx;
  font-size: 26rpx;
  color: #4e5969;
  flex-shrink: 0;
}
.form-value {
  flex: 1;
  font-size: 28rpx;
  text-align: right;
}
.form-input {
  flex: 1;
  font-size: 28rpx;
  text-align: right;
}
.primary-btn {
  background: #1652a8;
  color: #ffffff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.4;
}
.primary-btn.block {
  width: 100%;
  margin-top: 28rpx;
}
</style>
