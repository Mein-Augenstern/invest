<script setup lang="ts">
import { ref } from 'vue'
import { onShow, onPullDownRefresh } from '@dcloudio/uni-app'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'

interface ValRow {
  name: string
  code: string
  close: number | null
  pe: number | null
  pct_5y: number | null
  pct_all: number | null
  dyield: number | null
  ready: boolean
}

const loading = ref(true)
const rows = ref<ValRow[]>([])
const temperature = ref<number | null>(null)
// R8 自选指数：本地关注（storage 持久化），关注项置顶
const starred = ref<Set<string>>(new Set())
const STAR_KEY = 'invest_starred_indexes'

function loadStars() {
  try {
    const raw = uni.getStorageSync(STAR_KEY)
    starred.value = new Set(raw ? JSON.parse(raw) : [])
  } catch {
    starred.value = new Set()
  }
}

function toggleStar(code: string) {
  const next = new Set(starred.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  starred.value = next
  uni.setStorageSync(STAR_KEY, JSON.stringify([...next]))
  sortRows()
}

function sortRows() {
  rows.value = [...rows.value].sort((a, b) => {
    const sa = starred.value.has(a.code) ? 0 : 1
    const sb = starred.value.has(b.code) ? 0 : 1
    return sa - sb
  })
}

async function load() {
  loading.value = true
  try {
    await ensureLogin()
    const d = await request<{ indexes: ValRow[]; temperature: number | null }>({ url: '/valuation' })
    rows.value = d.indexes
    temperature.value = d.temperature
    sortRows()
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

/** 分位色阶（蛋卷式）：低=绿 中=黄 高=红 */
function pctClass(p: number | null): string {
  if (p === null) return 'cell-none'
  if (p < 30) return 'cell-low'
  if (p < 70) return 'cell-mid'
  return 'cell-high'
}

function tempLabel(): string {
  const t = temperature.value
  if (t === null) return ''
  if (t < 30) return '偏低'
  if (t < 70) return '中性'
  return '偏高'
}

loadStars()
onPullDownRefresh(async () => {
  await load()
  uni.stopPullDownRefresh()
})
onShow(load)
</script>

<template>
  <view class="page">
    <!-- R2 市场温度 -->
    <view v-if="temperature !== null" class="card temp-card">
      <view class="temp-left">
        <view class="temp-num" :class="pctClass(temperature)">{{ temperature }}</view>
        <view class="muted temp-sub">市场温度（0-100）</view>
      </view>
      <view class="temp-bar-wrap">
        <view class="temp-bar">
          <view class="temp-fill" :class="pctClass(temperature)" :style="{ width: temperature + '%' }" />
        </view>
        <view class="muted temp-tip">估值表指数 5 年 PE 分位等权合成 · {{ tempLabel() }}</view>
      </view>
    </view>

    <!-- R1 估值表 -->
    <view class="card table-card">
      <view class="t-head">
        <text class="c-name">指数</text>
        <text class="c-num">PE</text>
        <text class="c-num c-warm">5y分位</text>
        <text class="c-num">全历史</text>
        <text class="c-num">股息率</text>
      </view>
      <view v-for="r in rows" :key="r.code" class="t-row">
        <text class="c-name" @tap="toggleStar(r.code)">
          <text :class="['star', { on: starred.has(r.code) }]">{{ starred.has(r.code) ? '★' : '☆' }}</text>
          {{ r.name }}
        </text>
        <text class="c-num muted-num">{{ r.pe !== null ? r.pe.toFixed(2) : '—' }}</text>
        <text class="c-num">
          <text v-if="r.pct_5y !== null" :class="pctClass(r.pct_5y)">{{ Math.round(r.pct_5y) }}%</text>
          <text v-else class="cell-none">待拉取</text>
        </text>
        <text class="c-num">
          <text v-if="r.pct_all !== null" :class="pctClass(r.pct_all)">{{ Math.round(r.pct_all) }}%</text>
          <text v-else class="cell-none">—</text>
        </text>
        <text class="c-num">{{ r.dyield !== null ? r.dyield + '%' : '—' }}</text>
      </view>
      <view class="muted note">分位=当前 PE 在历史窗口内的位置（绿低红高，低买高卖参考）；口径见 docs/03。数据未齐时在设置页拉数。</view>
    </view>
  </view>
</template>

<style scoped>
.temp-card {
  display: flex;
  align-items: center;
  gap: 32rpx;
}
.temp-left {
  flex-shrink: 0;
  text-align: center;
}
.temp-num {
  font-size: 64rpx;
  font-weight: 600;
  line-height: 1.1;
}
.temp-sub {
  font-size: 22rpx;
  margin-top: 4rpx;
}
.temp-bar-wrap {
  flex: 1;
}
.temp-bar {
  height: 18rpx;
  background: #f0f1f3;
  border-radius: 9rpx;
  overflow: hidden;
}
.temp-fill {
  height: 100%;
  border-radius: 9rpx;
}
.temp-tip {
  font-size: 22rpx;
  margin-top: 10rpx;
}
.table-card {
  padding: 16rpx 24rpx;
}
.t-head,
.t-row {
  display: flex;
  align-items: center;
  padding: 14rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.t-head {
  color: #86909c;
  font-size: 24rpx;
}
.t-row {
  font-size: 26rpx;
}
.t-row:last-of-type {
  border-bottom: none;
}
.c-name {
  flex: 1.2;
}
.c-num {
  flex: 1;
  text-align: right;
}
.c-warm {
  font-weight: 500;
}
.muted-num {
  color: #4e5969;
}
.cell-low {
  color: #2e9e5b;
}
.cell-mid {
  color: #d46b08;
}
.cell-high {
  color: #d54941;
}
.cell-none {
  color: #c9cdd4;
}
.star {
  color: #c9cdd4;
  margin-right: 6rpx;
}
.star.on {
  color: #d46b08;
}
.temp-fill.cell-low,
.cell-low.temp-num {
  background: #2e9e5b;
  color: #2e9e5b;
}
.temp-fill.cell-mid,
.cell-mid.temp-num {
  background: #d46b08;
  color: #d46b08;
}
.temp-fill.cell-high,
.cell-high.temp-num {
  background: #d54941;
  color: #d54941;
}
.note {
  font-size: 22rpx;
  padding-top: 12rpx;
  line-height: 1.6;
}
</style>
