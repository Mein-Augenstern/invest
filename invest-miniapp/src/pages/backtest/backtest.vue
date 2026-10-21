<script setup lang="ts">
import { ref, getCurrentInstance } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { request } from '@/api/client'

interface BtResult {
  code: string
  name: string
  params: string
  metrics: Record<string, string | number | null>
  curve: [number, number][]
}

const running = ref(false)
const results = ref<BtResult[]>([])
const span = ref('')
const monthly = ref(1000)
const start = ref('2013-06-03')
const instance = getCurrentInstance()

// 六色低饱和（企业风）
const COLORS = ['#6f8fc9', '#7fa88f', '#b89f6a', '#c98b8b', '#94b0d6', '#a6a1c4']

async function run() {
  running.value = true
  results.value = []
  try {
    await ensureLogin()
    const out = await request<{ span: string; results: BtResult[] }>({
      url: '/backtest',
      method: 'POST',
      data: { start: start.value, monthly: Number(monthly.value) || 1000 },
    })
    span.value = out.span
    results.value = out.results
    setTimeout(() => drawCurves(), 350)
  } catch (e) {
    showApiError(e)
  } finally {
    running.value = false
  }
}

function drawCurves() {
  const all = results.value.filter((r) => r.curve.length >= 2)
  if (!all.length) return
  const ctx = uni.createCanvasContext('btChart', instance?.proxy)
  // 新基础库用 getWindowInfo（getSystemInfoSync 已废弃告警）
  const win = uni.getWindowInfo ? uni.getWindowInfo() : uni.getSystemInfoSync()
  const W = (win.windowWidth / 750) * 686
  const H = (win.windowWidth / 750) * 460
  const padL = 8
  const padR = 46
  const padT = 12
  const padB = 20

  let t0 = Infinity
  let t1 = -Infinity
  let vmin = Infinity
  let vmax = -Infinity
  for (const r of all) {
    for (const [t, v] of r.curve) {
      if (t < t0) t0 = t
      if (t > t1) t1 = t
      if (v < vmin) vmin = v
      if (v > vmax) vmax = v
    }
  }
  const x = (t: number) => padL + ((t - t0) / (t1 - t0 || 1)) * (W - padL - padR)
  const y = (v: number) => padT + (1 - (v - vmin) / (vmax - vmin || 1)) * (H - padT - padB)

  ctx.setStrokeStyle('#e5e6eb')
  ctx.setLineWidth(0.5)
  // 基准线 y=1（投入线）
  if (vmin <= 1 && vmax >= 1) {
    ctx.beginPath()
    ctx.moveTo(padL, y(1))
    ctx.lineTo(W - padR, y(1))
    ctx.stroke()
    ctx.setFillStyle('#86909c')
    ctx.setFontSize(9)
    ctx.fillText('1.0x', W - padR + 4, y(1) + 3)
  }
  all.forEach((r, i) => {
    ctx.setStrokeStyle(COLORS[i % COLORS.length])
    ctx.setLineWidth(1.2)
    ctx.beginPath()
    r.curve.forEach(([t, v], j) => {
      if (j === 0) ctx.moveTo(x(t), y(v))
      else ctx.lineTo(x(t), y(v))
    })
    ctx.stroke()
  })
  ctx.draw()
}

function onPickStart(e: { detail: { value: string } }) {
  start.value = e.detail.value
}

onLoad(() => {
  run()
})
</script>

<template>
  <view class="page">
    <view class="card">
      <view class="card-title">策略回测（红利指数历史重放）</view>
      <view class="param-row">
        <view class="param">
          <text class="muted p-label">月投入(元)</text>
          <input v-model="monthly" type="number" class="p-input" />
        </view>
        <view class="param">
          <text class="muted p-label">起始</text>
          <picker mode="date" :value="start" :end="'2026-01-01'" fields="month" @change="onPickStart">
            <view class="p-input p-picker">{{ start }}</view>
          </picker>
        </view>
        <button class="run-btn" :disabled="running" @tap="run">{{ running ? '回放中…' : '运行' }}</button>
      </view>
      <view class="muted tip">六种定投纪律对照（估值分位调节投入）；信号是纪律工具，不保证未来收益</view>
    </view>

    <view v-if="results.length" class="card">
      <view class="card-title">净值/投入曲线对比<span v-if="span" class="muted">（{{ span }}）</span></view>
      <canvas canvas-id="btChart" id="btChart" class="chart" />
      <view class="legend">
        <view v-for="(r, i) in results" :key="r.code" class="lg-item">
          <view class="dot" :style="{ background: COLORS[i % COLORS.length] }" />
          <text>{{ r.name }}</text>
        </view>
      </view>
    </view>

    <view v-for="(r, i) in results" :key="r.code" class="card">
      <view class="s-head">
        <view class="dot dot-lg" :style="{ background: COLORS[i % COLORS.length] }" />
        <text class="s-name">{{ r.name }}</text>
        <text class="muted s-params">{{ r.params }}</text>
      </view>
      <view class="kv"><text class="muted">XIRR 年化</text><text class="s-big">{{ r.metrics['XIRR年化'] }}</text></view>
      <view class="kv"><text class="muted">累计收益倍数</text><text>{{ r.metrics['累计收益倍数'] }}x</text></view>
      <view class="kv"><text class="muted">账户最大浮亏</text><text class="danger">{{ r.metrics['账户最大浮亏'] }}</text></view>
      <view class="kv"><text class="muted">指数最大回撤</text><text>{{ r.metrics['指数自身最大回撤'] }}</text></view>
      <view class="kv"><text class="muted">总投入 → 期末</text><text>{{ r.metrics['总投入'] }} → {{ r.metrics['期末市值'] }}</text></view>
    </view>

    <view v-if="!running && !results.length" class="card empty">回测依赖本机已拉取的全收益指数历史数据（设置页可拉数）</view>
  </view>
</template>

<style scoped>
.param-row {
  display: flex;
  align-items: flex-end;
  gap: 20rpx;
}
.param {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.p-label {
  font-size: 24rpx;
  margin-bottom: 6rpx;
}
.p-input {
  border: 1rpx solid #e5e6eb;
  border-radius: 8rpx;
  padding: 10rpx 16rpx;
  font-size: 28rpx;
}
.p-picker {
  color: #1d2129;
}
.run-btn {
  background: #1652a8;
  color: #fff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.3;
  padding: 0 36rpx;
  margin: 0;
}
.tip {
  font-size: 22rpx;
  margin-top: 14rpx;
  line-height: 1.6;
}
.chart {
  width: 686rpx;
  height: 460rpx;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 20rpx;
  margin-top: 12rpx;
}
.lg-item {
  display: flex;
  align-items: center;
  font-size: 24rpx;
  color: #4e5969;
}
.dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 4rpx;
  margin-right: 8rpx;
}
.dot-lg {
  width: 22rpx;
  height: 22rpx;
}
.s-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 12rpx;
}
.s-name {
  font-size: 30rpx;
  font-weight: 500;
}
.s-params {
  font-size: 22rpx;
}
.kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 26rpx;
  padding: 12rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.kv:last-child {
  border-bottom: none;
}
.s-big {
  font-size: 32rpx;
  font-weight: 500;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
</style>
