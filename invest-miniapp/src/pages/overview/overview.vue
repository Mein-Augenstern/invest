<script setup lang="ts">
import { ref, computed } from 'vue'
import { onPullDownRefresh, onShareAppMessage } from '@dcloudio/uni-app'
import { getOverview, startPull, getPullStatus } from '@/api/invest'
import { showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { fmtAmount, fmtSigned, fmtPct, pnlClass, fmtQty } from '@/utils/format'
import type { Overview } from '@/types'

const loading = ref(true)
const data = ref<Overview | null>(null)
const pulling = ref(false)
const loadError = ref('')
const cacheTime = ref('')

const CACHE_KEY = 'invest_cache_overview'

/** L8 缓存秒开：先渲染上次数据（标记时间），后台刷新替换 */
function readCache() {
  try {
    const raw = uni.getStorageSync(CACHE_KEY)
    if (raw) {
      const obj = JSON.parse(raw)
      data.value = obj.data
      cacheTime.value = obj.at || ''
    }
  } catch {
    /* 缓存损坏忽略 */
  }
}

/** 数据新鲜度（L5）：任一有持仓标的的 price_date 距今 >4 天（含周末缓冲）即过期 */
const staleDays = computed(() => {
  let worst = 0
  for (const g of data.value?.groups || []) {
    for (const p of g.positions) {
      if (!p.price_date || p.price_date === '—' || !p.quantity) continue
      const days = Math.floor((Date.now() - new Date(p.price_date.replace(/-/g, '/')).getTime()) / 86400000)
      if (days > worst) worst = days
    }
  }
  return worst > 4 ? worst : 0
})

async function onPullHere() {
  if (pulling.value) return
  try {
    await startPull()
    pulling.value = true
    uni.showToast({ title: '拉数已开始（分钟级）', icon: 'none' })
    const timer = setInterval(async () => {
      try {
        const st = await getPullStatus()
        if (st.status !== 'running') {
          clearInterval(timer)
          pulling.value = false
          if (st.status === 'done') {
            uni.showToast({ title: '数据已更新', icon: 'success' })
            load()
          }
        }
      } catch {
        clearInterval(timer)
        pulling.value = false
      }
    }, 3000)
  } catch (e) {
    showApiError(e)
  }
}

/** 品类占比（有市值的组才参与；企业风低饱和配色） */
const mix = computed(() => {
  const palette: Record<string, string> = {
    wealth: '#94b0d6',
    bond: '#7fa88f',
    open_end_fund: '#6f8fc9',
    etf: '#b89f6a',
    stock: '#c98b8b',
  }
  const withMv = (data.value?.groups || []).filter((g) => g.market_value && g.market_value > 0)
  const total = withMv.reduce((s, g) => s + (g.market_value || 0), 0)
  if (total <= 0) return []
  return withMv.map((g) => ({
    type: g.type,
    label: g.label,
    pct: (g.market_value || 0) / total,
    color: palette[g.type] || '#a6adb8',
  }))
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用，8s 超时放行）
    data.value = await getOverview()
    uni.setStorageSync(CACHE_KEY, JSON.stringify({ data: data.value, at: new Date().toTimeString().slice(0, 5) }))
    cacheTime.value = ''
  } catch (e) {
    console.warn('[invest] overview load FAIL:', e instanceof Error ? e.message : e)
    loadError.value = e instanceof Error ? e.message : String(e)
    showApiError(e)
  } finally {
    loading.value = false
  }
}

readCache()

function onNavTrades() {
  uni.switchTab({ url: '/pages/trades/trades' })
}

function onQuickAdd() {
  uni.$emit('invest-quick-add')
  uni.switchTab({ url: '/pages/trades/trades' })
}

function onNavSignals() {
  uni.switchTab({ url: '/pages/signals/signals' })
}

function onOpenInstrument(id: string) {
  uni.navigateTo({ url: `/pages/instrument/instrument?id=${encodeURIComponent(id)}` })
}

function onOpenReport() {
  uni.navigateTo({ url: '/pages/report/report' })
}

function onOpenValuation() {
  uni.navigateTo({ url: '/pages/valuation/valuation' })
}

function goInstruments() {
  uni.navigateTo({ url: '/pages/instruments/instruments' })
}

// L6 分享：转发卡片标题不含金额（真实数据不出家庭内网——章程红线）；
// 详细数字走「复制快照」（剪贴板在本机，粘给谁由用户自主决定）
onShareAppMessage(() => ({
  title: 'invest · 个人投资管理',
  path: '/pages/overview/overview',
}))

function buildSnapshotText(): string {
  const d = data.value
  if (!d) return ''
  const lines: string[] = [`📊 invest 快照 ${d.date}`, '']
  if (d.totals.market_value !== null) {
    lines.push(`总市值 ${fmtAmount(d.totals.market_value)} 元`)
    lines.push(`浮动盈亏 ${fmtSigned(d.totals.unrealized)} 元`)
    if (d.totals.xirr !== null) lines.push(`组合 XIRR ${fmtPct(d.totals.xirr)}`)
  }
  if (d.pension_progress) {
    const pp = d.pension_progress
    lines.push(`养老金缴存 ${fmtAmount(pp.contributed, 0)}/${fmtAmount(pp.cap, 0)}（${Math.round((pp.contributed / pp.cap) * 100)}%）`)
  }
  for (const g of d.groups) {
    for (const p of g.positions) {
      if (!p.quantity) continue
      const pnl = p.unrealized !== null ? `（${fmtSigned(p.unrealized, 0)}）` : ''
      lines.push(`· ${p.name} ${p.market_value !== null ? fmtAmount(p.market_value, 0) + ' 元' : '市值待更新'}${pnl}`)
    }
  }
  return lines.join('\n')
}

function onCopySnapshot() {
  const text = buildSnapshotText()
  if (!text) {
    uni.showToast({ title: '暂无数据', icon: 'none' })
    return
  }
  uni.setClipboardData({
    data: text,
    success: () => uni.showToast({ title: '快照已复制，可粘贴分享', icon: 'none' }),
  })
}

onPullDownRefresh(async () => {
  await load()
  uni.stopPullDownRefresh()
})

load()
</script>

<template>
  <view class="page">
    <!-- 组合总卡 -->
    <view class="card">
      <view class="card-title">总市值（{{ data?.date || '—' }}）</view>
      <view class="hero-num">{{ fmtAmount(data?.totals.market_value) }}</view>
      <view class="hero-row">
        <view class="hero-item">
          <text class="muted label">浮动盈亏</text>
          <text :class="['hero-val', pnlClass(data?.totals.unrealized)]">
            {{ fmtSigned(data?.totals.unrealized) }}
          </text>
        </view>
        <view class="hero-item">
          <text class="muted label">组合 XIRR</text>
          <text :class="['hero-val', pnlClass(data?.totals.xirr)]">
            {{ data?.totals.xirr === null || data?.totals.xirr === undefined ? '—' : fmtPct(data.totals.xirr) }}
          </text>
        </view>
      </view>
      <view v-if="data?.is_example" class="example-tip">当前为示例配置，请在本机 portfolio.local.yaml 填写真实标的</view>
    </view>

    <!-- L5 数据新鲜度：过期黄条 + 就地拉数 -->
    <view v-if="staleDays" class="stale-bar">
      <text class="stale-text">行情数据已 {{ staleDays }} 天未更新（本机 cron 或手动拉数可刷新）</text>
      <text class="stale-btn" @tap="onPullHere">{{ pulling ? '拉取中…' : '立即拉数' }}</text>
    </view>

    <!-- L8 缓存/错误状态条 -->
    <view v-if="cacheTime" class="muted cache-bar">显示缓存数据（{{ cacheTime }}），刷新中…</view>
    <view v-if="loadError && !loading" class="stale-bar" @tap="load">
      <text class="stale-text">加载失败：{{ loadError }}</text>
      <text class="stale-btn">重试</text>
    </view>

    <!-- 品类占比（≥2 组有市值才显示） -->
    <view v-if="mix.length >= 2" class="card">
      <view class="card-title">品类占比</view>
      <view class="mix-bar">
        <view
          v-for="m in mix"
          :key="m.type"
          class="mix-seg"
          :style="{ background: m.color, width: (m.pct * 100).toFixed(2) + '%' }"
        />
      </view>
      <view class="mix-legend">
        <view v-for="m in mix" :key="m.type" class="mix-item">
          <view class="dot" :style="{ background: m.color }" />
          <text>{{ m.label }} {{ (m.pct * 100).toFixed(0) }}%</text>
        </view>
      </view>
    </view>

    <!-- 养老金缴存进度 -->
    <view v-if="data?.pension_progress" class="card">
      <view class="card-title">养老金缴存进度（{{ data.pension_progress.year }}）</view>
      <view class="pension-row">
        <text class="pension-num">{{ fmtAmount(data.pension_progress.contributed, 0) }}</text>
        <text class="muted pension-cap">/ {{ fmtAmount(data.pension_progress.cap, 0) }} 元</text>
        <text class="pension-pct">
          {{ Math.min(100, Math.round((data.pension_progress.contributed / data.pension_progress.cap) * 100)) }}%
        </text>
      </view>
      <view class="pension-bar">
        <view
          class="pension-fill"
          :style="{ width: Math.min(100, (data.pension_progress.contributed / data.pension_progress.cap) * 100).toFixed(1) + '%' }"
        />
      </view>
      <view class="muted pension-note">缴满可享个税抵扣；超出上限的缴存不再抵扣</view>
    </view>

    <!-- 按品类分组持仓 -->
    <view v-for="g in data?.groups || []" :key="g.type" class="card">
      <view class="group-head">
        <text class="group-label">{{ g.label }}</text>
        <text class="muted">{{ fmtAmount(g.market_value) }}</text>
      </view>
      <view v-for="p in g.positions" :key="p.id" class="pos-row" @tap="onOpenInstrument(p.id)">
        <view class="pos-main">
          <view class="pos-name">{{ p.name }}</view>
          <view class="pos-sub muted">
            {{ p.account }} · {{ fmtQty(p.quantity) }}份 @ {{ p.price ?? '—' }}
            <text v-if="p.price_date && p.price_date !== '—'">（{{ p.price_date }}）</text>
          </view>
        </view>
        <view class="pos-side">
          <view :class="['pos-val', pnlClass(p.unrealized)]">
            {{ fmtSigned(p.market_value) }}<text class="arrow">›</text>
          </view>
          <view class="pos-sub muted">
            <text v-if="p.unrealized !== null">盈亏 {{ fmtSigned(p.unrealized) }}</text>
            <text v-else>缺{{ p.type === 'wealth' || p.type === 'open_end_fund' ? '净值' : '行情' }}</text>
            <text v-if="p.xirr !== null"> · XIRR {{ fmtPct(p.xirr) }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 基准估值 -->
    <view v-if="data?.benchmarks?.length" class="card">
      <view class="card-title">
        基准指数估值
        <text class="link" @tap="onOpenValuation">全市场估值表 ›</text>
      </view>
      <view v-for="b in data.benchmarks" :key="b.name" class="bench-row">
        <view class="pos-main">
          <view class="pos-name">{{ b.name }}</view>
          <view class="pos-sub muted">
            PE {{ b.pe_ttm ?? '—' }} · 5y分位 {{ b.pct_5y === null ? '—' : Math.round(b.pct_5y) + '%' }}
            · 股息率 {{ b.dyield === null ? '—' : b.dyield + '%' }}
          </view>
        </view>
        <view class="pos-side muted">{{ b.drawdown_5y === null ? '—' : (b.drawdown_5y * 100).toFixed(1) + '%' }}</view>
      </view>
      <view class="muted bench-note">右侧为距5年高点回撤；口径见 docs/03</view>
    </view>

    <!-- 近期信号 -->
    <view v-if="data?.signals?.length" class="card">
      <view class="group-head" @tap="onNavSignals">
        <text class="group-label">策略信号</text>
        <text class="link">全部</text>
      </view>
      <view v-for="s in data.signals" :key="s.id" class="sig-row">
        <view class="pos-main">
          <view class="pos-name">{{ s.instrument }} · {{ s.action }}</view>
          <view class="pos-sub muted">{{ s.date }} {{ s.rule }}</view>
        </view>
        <text class="sig-status" :class="{ active: s.status === '建议' }">{{ s.status }}</text>
      </view>
    </view>

    <view v-if="!loading && !data?.groups?.length" class="card empty">
      <view class="empty-title">开始使用 invest</view>
      <view class="empty-steps">
        <view class="step step-link" @tap="goInstruments">1. 点此添加标的（支持基金/ETF/股票/债券/理财五品类） ›</view>
        <view class="step">2. 设置页「开始拉数」抓取行情净值（理财品种跳过）</view>
        <view class="step">3. 流水页「记一笔」或「截图识别」录入持仓，总览与统计自动生成</view>
      </view>
      <view class="muted empty-note">账本与数据只在本机，不上传任何云端</view>
    </view>

    <!-- 底部快捷入口 -->
    <view class="footer-actions">
      <button class="ghost-btn" @tap="onNavTrades">记一笔</button>
      <button class="ghost-btn" @tap="onNavSignals">看信号</button>
      <button class="ghost-btn" @tap="onOpenReport">周报</button>
      <button class="ghost-btn" @tap="onCopySnapshot">复制快照</button>
    </view>
    <!-- R9 全局快捷记一笔 -->
    <view class="fab" @tap="onQuickAdd">＋</view>
    <view class="footer-space" />
  </view>
</template>

<style scoped>
.hero-num {
  font-size: 56rpx;
  font-weight: 600;
  letter-spacing: 1rpx;
}
.hero-row {
  display: flex;
  margin-top: 20rpx;
}
.hero-item {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.label {
  font-size: 24rpx;
}
.hero-val {
  font-size: 32rpx;
  font-weight: 500;
  margin-top: 6rpx;
}
.example-tip {
  margin-top: 16rpx;
  font-size: 24rpx;
  color: #d46b08;
}
.stale-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 20rpx 24rpx 0;
  padding: 16rpx 24rpx;
  background: #fdf6ec;
  border: 1rpx solid #f3d19e;
  border-radius: 12rpx;
}
.stale-text {
  font-size: 24rpx;
  color: #d46b08;
  flex: 1;
}
.stale-btn {
  font-size: 24rpx;
  color: #1652a8;
  margin-left: 16rpx;
  flex-shrink: 0;
}
.cache-bar {
  font-size: 22rpx;
  text-align: center;
  margin-top: 16rpx;
}
.mix-bar {
  display: flex;
  height: 22rpx;
  border-radius: 6rpx;
  overflow: hidden;
}
.mix-seg {
  height: 100%;
}
.mix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 24rpx;
  margin-top: 16rpx;
}
.mix-item {
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
.pension-row {
  display: flex;
  align-items: baseline;
}
.pension-num {
  font-size: 40rpx;
  font-weight: 600;
}
.pension-cap {
  font-size: 24rpx;
  margin-left: 8rpx;
}
.pension-pct {
  margin-left: auto;
  font-size: 28rpx;
  color: #1652a8;
  font-weight: 500;
}
.pension-bar {
  height: 14rpx;
  background: #f0f1f3;
  border-radius: 7rpx;
  overflow: hidden;
  margin-top: 14rpx;
}
.pension-fill {
  height: 100%;
  background: #1652a8;
  border-radius: 7rpx;
}
.pension-note {
  font-size: 22rpx;
  margin-top: 12rpx;
}
.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}
.group-label {
  font-weight: 500;
}
.link {
  color: #1652a8;
  font-size: 26rpx;
}
.pos-row,
.bench-row,
.sig-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.pos-row:last-child,
.bench-row:last-child,
.sig-row:last-child {
  border-bottom: none;
}
.pos-main {
  flex: 1;
  min-width: 0;
}
.pos-name {
  font-size: 28rpx;
}
.pos-sub {
  font-size: 24rpx;
  margin-top: 6rpx;
}
.pos-side {
  text-align: right;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.pos-val {
  font-size: 30rpx;
  font-weight: 500;
}
.arrow {
  color: #c9cdd4;
  font-weight: 400;
  margin-left: 6rpx;
}
.bench-note {
  font-size: 22rpx;
  margin-top: 12rpx;
}
.sig-status {
  font-size: 24rpx;
  color: #86909c;
}
.sig-status.active {
  color: #d46b08;
}
.footer-actions {
  display: flex;
  gap: 20rpx;
  margin: 32rpx 24rpx 0;
}
.ghost-btn {
  flex: 1;
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #1d2129;
  font-size: 28rpx;
  line-height: 2.4;
}
.footer-space {
  height: 40rpx;
}
.fab {
  position: fixed;
  right: 32rpx;
  bottom: calc(180rpx + env(safe-area-inset-bottom));
  width: 96rpx;
  height: 96rpx;
  border-radius: 48rpx;
  background: #1652a8;
  color: #fff;
  font-size: 52rpx;
  line-height: 92rpx;
  text-align: center;
  z-index: 90;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
.empty-title {
  font-size: 30rpx;
  font-weight: 500;
  color: #1d2129;
  margin-bottom: 16rpx;
}
.empty-steps {
  text-align: left;
}
.step {
  font-size: 26rpx;
  line-height: 2;
  color: #4e5969;
}
.step-link {
  color: #1652a8;
}
.empty-note {
  font-size: 22rpx;
  margin-top: 16rpx;
}
</style>
