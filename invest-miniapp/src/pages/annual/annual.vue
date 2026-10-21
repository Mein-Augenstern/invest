<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { fmtAmount, fmtSigned, pnlClass } from '@/utils/format'

interface Annual {
  year: string
  empty: boolean
  net_invested: number
  invested: number
  returned: number
  pnl_change: number
  realized: number
  account_cash: number
  cash_div: number
  year_end_mv: number
  months_count: number
  win_months: number
  best_month: { month: string; pnl_change: number }
  worst_month: { month: string; pnl_change: number }
  monthly: { month: string; pnl_change: number; net_invested: number }[]
}

const years = computed(() => {
  const now = new Date().getFullYear()
  return [now, now - 1, now - 2]
})
const year = ref(String(new Date().getFullYear()))
const data = ref<Annual | null>(null)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    await ensureLogin()
    data.value = await request<Annual>({ url: '/annual-report', params: { year: year.value } })
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

function switchYear(y: string) {
  year.value = y
  load()
}

/** 月度盈亏条形（CSS 实现，正负双向） */
const maxAbs = computed(() => {
  const ms = data.value?.monthly || []
  let mx = 1
  for (const m of ms) mx = Math.max(mx, Math.abs(m.pnl_change))
  return mx
})

onShow(load)
</script>

<template>
  <view class="page">
    <view class="year-switch">
      <text
        v-for="y in years"
        :key="y"
        :class="{ on: y === year }"
        @tap="switchYear(y)"
      >{{ y }}</text>
    </view>

    <view v-if="data && !data.empty" class="page">
      <view class="card hero">
        <view class="muted hero-label">{{ year }} 年浮盈变化</view>
        <view :class="['hero-num', pnlClass(data.pnl_change)]">{{ fmtSigned(data.pnl_change) }}</view>
        <view class="hero-row">
          <view class="hero-item">
            <text class="muted l">净投入</text>
            <text class="v">{{ fmtAmount(data.net_invested, 0) }}</text>
          </view>
          <view class="hero-item">
            <text class="muted l">年末市值</text>
            <text class="v">{{ fmtAmount(data.year_end_mv, 0) }}</text>
          </view>
        </view>
      </view>

      <view class="card">
        <view class="card-title">全年盘点</view>
        <view class="kv"><text class="muted">月度胜率</text><text>{{ data.win_months }}/{{ data.months_count }} 个月正收益</text></view>
        <view class="kv"><text class="muted">最佳月份</text><text :class="pnlClass(data.best_month.pnl_change)">{{ data.best_month.month }} {{ fmtSigned(data.best_month.pnl_change, 0) }}</text></view>
        <view class="kv"><text class="muted">最差月份</text><text :class="pnlClass(data.worst_month.pnl_change)">{{ data.worst_month.month }} {{ fmtSigned(data.worst_month.pnl_change, 0) }}</text></view>
        <view class="kv"><text class="muted">累计申购</text><text>{{ fmtAmount(data.invested, 0) }}</text></view>
        <view class="kv"><text class="muted">累计赎回</text><text>{{ fmtAmount(data.returned, 0) }}</text></view>
        <view class="kv">
          <text class="muted">账户现金（缴存未申购）</text>
          <view class="cash-wrap">
            <text>{{ fmtAmount(data.account_cash, 0) }}</text>
            <text v-if="data.account_cash < 0" class="cash-warn">缴存记录待补全</text>
          </view>
        </view>
        <view class="kv"><text class="muted">现金分红</text><text>{{ fmtAmount(data.cash_div, 0) }}</text></view>
        <view class="kv"><text class="muted">已实现盈亏</text><text :class="pnlClass(data.realized)">{{ fmtSigned(data.realized) }}</text></view>
      </view>

      <view class="card">
        <view class="card-title">月度盈亏分布</view>
        <view class="bar-row" v-for="m in data.monthly" :key="m.month">
          <text class="b-month">{{ m.month.slice(5) }}</text>
          <view class="b-track">
            <view class="b-zero" />
            <view
              :class="['b-fill', m.pnl_change >= 0 ? 'up' : 'down']"
              :style="{
                width: (Math.abs(m.pnl_change) / maxAbs) * 50 + '%',
                [m.pnl_change >= 0 ? 'left' : 'right']: '50%',
              }"
            />
          </view>
          <text :class="['b-val', pnlClass(m.pnl_change)]">{{ fmtSigned(m.pnl_change, 0) }}</text>
        </view>
        <view class="muted note">持仓浮盈 = Δ市值 − 净投入；养老金账户「缴存未申购」的现金单列不计入浮盈；回望是纪律的一部分</view>
      </view>
    </view>

    <view v-else-if="data && data.empty" class="card empty">{{ year }} 年还没有数据</view>
  </view>
</template>

<style scoped>
.year-switch {
  display: flex;
  justify-content: center;
  gap: 32rpx;
  margin: 20rpx 0 0;
}
.year-switch text {
  font-size: 28rpx;
  color: #86909c;
  padding: 6rpx 28rpx;
  border: 1rpx solid #e5e6eb;
  border-radius: 28rpx;
}
.year-switch text.on {
  color: #1652a8;
  border-color: #1652a8;
  background: #eef3fb;
}
.hero {
  text-align: center;
  padding: 40rpx 24rpx;
}
.hero-label {
  font-size: 26rpx;
}
.hero-num {
  font-size: 72rpx;
  font-weight: 600;
  margin: 12rpx 0 20rpx;
}
.hero-row {
  display: flex;
  justify-content: center;
  gap: 80rpx;
}
.hero-item {
  display: flex;
  flex-direction: column;
}
.l {
  font-size: 24rpx;
}
.v {
  font-size: 30rpx;
  font-weight: 500;
  margin-top: 6rpx;
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
.cash-wrap {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.cash-warn {
  font-size: 20rpx;
  color: #d46b08;
}
.bar-row {
  display: flex;
  align-items: center;
  padding: 8rpx 0;
}
.b-month {
  width: 70rpx;
  font-size: 24rpx;
  color: #86909c;
  flex-shrink: 0;
}
.b-track {
  flex: 1;
  height: 28rpx;
  position: relative;
  background: #f7f8fa;
  border-radius: 6rpx;
  overflow: hidden;
}
.b-zero {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1rpx;
  background: #e5e6eb;
}
.b-fill {
  position: absolute;
  top: 4rpx;
  bottom: 4rpx;
  border-radius: 4rpx;
}
.b-fill.up {
  background: #d54941;
}
.b-fill.down {
  background: #2e9e5b;
}
.b-val {
  width: 130rpx;
  text-align: right;
  font-size: 24rpx;
  flex-shrink: 0;
}
.note {
  font-size: 22rpx;
  padding-top: 14rpx;
  line-height: 1.6;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
</style>
