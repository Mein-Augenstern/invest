<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import {
  confirmSignal,
  getSignalHistory,
  getSignals,
  ignoreSignal,
  type PaperTrade,
  type SignalItem,
} from '@/api/invest'
import { ApiError, request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { ACTION_LABELS } from '@/types'
import ErrorCard from '@/components/ErrorCard.vue'

/* ---------- 视图模型：S02 富格式优先，旧版（S02 前）字段兜底 ---------- */

/** 规则明细行：signal.results[].rule 与命中情况拍平 */
interface RuleRowVM {
  id: string
  name: string
  signal: string
  weight: number | null
  note: string
  triggered: boolean
  metricValue: string
  description: string
}

interface SignalVM {
  key: string
  id: string | number
  name: string
  date: string
  finalSignal: string // buy/hold/sell/rebalance；旧数据为空
  confidence: number | null
  status: string
  summary: string
  ruleRows: RuleRowVM[]
  hasDetail: boolean
  legacyMetric: string
  legacyValue: string
  legacyAction: string
}

const SIGNAL_LABELS: Record<string, string> = {
  buy: '买入',
  hold: '持有',
  sell: '卖出',
  rebalance: '再平衡',
  ignore: '观望',
}

function formatMetric(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return v
}

function toVM(s: SignalItem): SignalVM {
  const ruleRows: RuleRowVM[] = (s.results || []).map((r, i) => ({
    id: r.rule?.id || `rule-${i}`,
    name: r.rule?.name || r.rule?.id || `规则${i + 1}`,
    signal: r.rule?.signal || '',
    weight: typeof r.rule?.weight === 'number' ? r.rule.weight : null,
    note: r.rule?.note || '',
    triggered: !!r.triggered,
    metricValue: formatMetric(r.metric_value),
    description: r.description || '',
  }))
  return {
    key: String(s.id),
    id: s.id,
    name: s.instrument_name || s.instrument || s.instrument_id || String(s.id),
    date: s.date || '',
    finalSignal: s.final_signal || '',
    confidence: typeof s.confidence === 'number' ? s.confidence : null,
    status: s.status || '',
    summary: s.summary || '',
    ruleRows,
    hasDetail: ruleRows.length > 0,
    legacyMetric: s.metric || '',
    legacyValue: s.value || '',
    legacyAction: s.action || '',
  }
}

/* ---------- 状态 ---------- */

const signals = ref<SignalVM[]>([])
const paperTrades = ref<PaperTrade[]>([]) // 当前纸面交易（/signals 随信号返回）
const historyTrades = ref<PaperTrade[]>([]) // 历史（已关闭，/signals/history）
const loading = ref(false)
const evaluating = ref(false)
const activeTab = ref<'signals' | 'paper'>('signals')
const historyLoaded = ref(false)
const expandedKeys = ref<Record<string, boolean>>({})
const showStrategyInfo = ref(false)

// 错误态 + 重试（ErrorCard；不影响 S02 信号/纸面交易逻辑）
const loadError = ref(false)
const errorMsg = ref('')
const retrying = ref(false)
const retry = async () => {
  if (retrying.value) return
  retrying.value = true
  try {
    await load()
  } catch {
    /* load 内部已置 loadError */
  } finally {
    retrying.value = false
  }
}

/** 纸面交易列表：当前 + 去重合并历史，持仓中在前 */
const paperList = computed<PaperTrade[]>(() => {
  const seen = new Set<string>()
  const merged: PaperTrade[] = []
  for (const t of [...paperTrades.value, ...historyTrades.value]) {
    const k = String(t.id)
    if (seen.has(k)) continue
    seen.add(k)
    merged.push(t)
  }
  const rank = (t: PaperTrade) => (t.status === 'open' ? 0 : 1)
  return merged.sort((a, b) => rank(a) - rank(b))
})

/** 策略说明：从已加载信号的规则明细聚合（去重 + 近期命中率） */
const activeRules = computed(() => {
  const map = new Map<string, { id: string; name: string; weight: number | null; note: string; hit: number; total: number }>()
  for (const s of signals.value) {
    for (const r of s.ruleRows) {
      const cur = map.get(r.id) || { id: r.id, name: r.name, weight: r.weight, note: '', hit: 0, total: 0 }
      cur.total += 1
      if (r.triggered) cur.hit += 1
      if (r.weight !== null) cur.weight = r.weight
      if (r.note) cur.note = r.note
      map.set(r.id, cur)
    }
  }
  return [...map.values()]
})

/* ---------- 行为 ---------- */

async function onEvaluate() {
  if (evaluating.value) return
  evaluating.value = true
  try {
    const d = await request<{ new: number }>({ url: '/signals/evaluate', method: 'POST' })
    uni.showToast({ title: `评估完成（新增 ${d.new} 条）`, icon: 'none' })
    load()
  } catch (e) {
    showApiError(e)
  } finally {
    evaluating.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用）
    const d = await getSignals()
    signals.value = d.signals.map(toVM)
    paperTrades.value = d.paper_trades || []
  } catch (e) {
    loadError.value = true
    errorMsg.value = e instanceof Error ? e.message : String(e)
    showApiError(e)
  } finally {
    loading.value = false
  }
}

/** 首次切到纸面交易页签时补拉历史（含已关闭交易的最终收益） */
async function loadHistory() {
  try {
    const d = await getSignalHistory()
    historyTrades.value = d.paper_trades || []
  } catch (e) {
    // 后端 S02 未上线（无 /signals/history，404）时静默降级，其余错误正常提示
    if (!(e instanceof ApiError && e.status === 404)) showApiError(e)
  }
}

function onTab(tab: 'signals' | 'paper') {
  if (activeTab.value === tab) return
  activeTab.value = tab
  if (tab === 'paper' && !historyLoaded.value) {
    historyLoaded.value = true
    loadHistory()
  }
}

function toggleDetail(s: SignalVM) {
  expandedKeys.value[s.key] = !expandedKeys.value[s.key]
}

async function onConfirm(s: SignalVM) {
  try {
    await confirmSignal(s.id)
    s.status = '已确认'
    uni.showToast({ title: '已确认，已开纸面交易', icon: 'none' })
    load() // 刷新纸面交易列表
  } catch (e) {
    showApiError(e)
  }
}

async function onIgnore(s: SignalVM) {
  try {
    await ignoreSignal(s.id)
    s.status = '已忽略'
    uni.showToast({ title: '已忽略', icon: 'success' })
  } catch (e) {
    showApiError(e)
  }
}

function badgeLabel(s: SignalVM): string {
  return SIGNAL_LABELS[s.finalSignal] || (s.finalSignal || '建议')
}

function confidencePct(s: SignalVM): string {
  return s.confidence === null ? '' : `${Math.round(s.confidence * 100)}%`
}

function actionLabel(a: string): string {
  return ACTION_LABELS[a] || a
}

function paperStatusLabel(t: PaperTrade): string {
  if (t.status === 'open') return '持仓中'
  if (t.status === 'closed') return '已关闭'
  if (t.status === 'expired') return '已过期'
  return t.status
}

function formatReturn(t: PaperTrade): string {
  const pct = t.return_pct
  if (pct === null || pct === undefined) return t.status === 'open' ? '—' : '收益待结算'
  return `${pct >= 0 ? '+' : ''}${(pct * 100).toFixed(2)}%`
}

function onOpenDiary() {
  uni.navigateTo({ url: '/pages/diary/diary' })
}

onShow(load)
</script>

<template>
  <view class="page">
    <view class="card note">
      信号是纪律工具而非收益保证（章程红线）。口径与规则见 docs/business/strategy-rules.md。
      <text class="diary-link" @tap="onOpenDiary">投资日记 ›</text>
      <text class="eval-link" @tap="onEvaluate">{{ evaluating ? '评估中…' : '立即评估' }}</text>
    </view>

    <!-- 页签切换：当前信号 / 纸面交易；右侧 ⓘ 策略说明 -->
    <view class="card tab-bar">
      <view class="tabs">
        <view :class="['tab', activeTab === 'signals' ? 'active' : '']" @tap="onTab('signals')">当前信号</view>
        <view :class="['tab', activeTab === 'paper' ? 'active' : '']" @tap="onTab('paper')">纸面交易</view>
      </view>
      <text class="info-btn" @tap="showStrategyInfo = true">ⓘ 策略说明</text>
    </view>

    <!-- 加载失败（ErrorCard，可重试） -->
    <ErrorCard :visible="loadError && !loading" title="加载失败" :description="errorMsg" :loading="retrying" @retry="retry" />

    <!-- Tab 1：当前信号 -->
    <block v-if="activeTab === 'signals'">
      <view v-if="!signals.length && !loading && !loadError" class="card empty">暂无信号。可在本机执行 invest signals 评估，或等待每日 cron。</view>

      <view v-for="s in signals" :key="s.key" class="card sig-card">
        <view class="sig-head" @tap="toggleDetail(s)">
          <view class="pos-main">
            <view class="sig-title-row">
              <text :class="['sig-badge', s.finalSignal || 'hold']">{{ badgeLabel(s) }}</text>
              <text class="sig-title">{{ s.name }}</text>
              <text v-if="s.hasDetail" class="expand-icon">{{ expandedKeys[s.key] ? '▼' : '▶' }}</text>
            </view>
            <view class="muted sig-sub">
              <text v-if="s.date">{{ s.date }}</text>
              <text v-if="s.confidence !== null" class="confidence">置信度 {{ confidencePct(s) }}</text>
            </view>
          </view>
          <text class="sig-status" :class="{ active: s.status === '建议' }">{{ s.status }}</text>
        </view>

        <view v-if="s.summary" class="sig-summary">{{ s.summary }}</view>

        <!-- 旧版（S02 前）数据：无规则明细，保留依据/建议两行 -->
        <view v-if="!s.hasDetail && (s.legacyMetric || s.legacyAction)" class="sig-body">
          <view v-if="s.legacyMetric" class="sig-line">
            <text class="muted">依据</text>{{ s.legacyMetric }} = {{ s.legacyValue }}
          </view>
          <view v-if="s.legacyAction" class="sig-line"><text class="muted">建议</text>{{ s.legacyAction }}</view>
        </view>

        <!-- 规则明细（可展开/收起） -->
        <view v-if="s.hasDetail && expandedKeys[s.key]" class="signal-detail">
          <view v-for="r in s.ruleRows" :key="r.id" class="rule-row">
            <text :class="['rule-dot', r.triggered ? 'hit' : 'miss']">●</text>
            <view class="rule-main">
              <view class="rule-line1">
                <text class="rule-name">{{ r.name }}</text>
                <text v-if="SIGNAL_LABELS[r.signal]" :class="['rule-signal', r.signal]">{{ SIGNAL_LABELS[r.signal] }}</text>
                <text v-if="r.weight !== null" class="rule-weight">{{ r.weight }}权重</text>
                <text class="rule-value">{{ r.metricValue }}</text>
              </view>
              <text v-if="r.description" class="rule-desc">{{ r.description }}</text>
            </view>
          </view>
        </view>

        <view v-if="s.status === '建议'" class="sig-actions">
          <button class="mini-btn" @tap="onIgnore(s)">忽略</button>
          <button class="mini-btn primary" @tap="onConfirm(s)">确认</button>
        </view>
      </view>
    </block>

    <!-- Tab 2：纸面交易 -->
    <block v-else>
      <view v-if="!paperList.length && !loading && !loadError" class="card empty">暂无纸面交易。确认信号后会自动开启纸面模拟跟踪（非真实交易）。</view>

      <view v-for="t in paperList" :key="String(t.id)" class="card paper-card">
        <view class="paper-head">
          <text :class="['paper-status', t.status === 'open' ? 'open' : 'closed']">{{ paperStatusLabel(t) }}</text>
          <text v-if="t.return_pct !== null && t.return_pct !== undefined" :class="['paper-return', t.return_pct >= 0 ? 'profit' : 'loss']">
            {{ formatReturn(t) }}
          </text>
        </view>
        <view class="paper-line">
          {{ t.instrument_name }} {{ actionLabel(t.action) }} {{ t.quantity }} @{{ t.price_at_signal }}
        </view>
        <view v-if="t.return_pct === null || t.return_pct === undefined" class="muted paper-sub">{{ formatReturn(t) }}</view>
      </view>
    </block>

    <!-- 策略说明弹窗：当前启用的规则列表 -->
    <view v-if="showStrategyInfo" class="strategy-modal" @tap="showStrategyInfo = false">
      <view class="modal-content" @tap.stop>
        <view class="modal-title">当前策略规则</view>
        <view v-if="!activeRules.length" class="muted modal-empty">
          暂无规则明细。规则由策略引擎（strategy.yaml）返回，旧版信号仅含单条规则口径。
        </view>
        <view v-for="r in activeRules" :key="r.id" class="modal-rule">
          <view class="modal-rule-line">
            <text class="rule-name">{{ r.name }}</text>
            <text v-if="r.weight !== null" class="rule-weight">{{ r.weight }}权重</text>
            <text class="muted rule-hit">近期命中 {{ r.hit }}/{{ r.total }}</text>
          </view>
          <text v-if="r.note" class="rule-desc">{{ r.note }}</text>
        </view>
        <button class="mini-btn primary modal-close" @tap="showStrategyInfo = false">关闭</button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.note {
  color: #86909c;
  font-size: 24rpx;
}
.diary-link {
  color: #1652a8;
  margin-left: 12rpx;
}
.eval-link {
  color: #1652a8;
  float: right;
}

/* 页签栏 */
.tab-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 24rpx;
}
.tabs {
  display: flex;
  gap: 8rpx;
  background: #f2f3f5;
  border-radius: 10rpx;
  padding: 4rpx;
}
.tab {
  font-size: 26rpx;
  color: #4e5969;
  padding: 8rpx 28rpx;
  border-radius: 8rpx;
}
.tab.active {
  background: #ffffff;
  color: #1652a8;
  font-weight: 500;
}
.info-btn {
  font-size: 24rpx;
  color: #1652a8;
  flex-shrink: 0;
}

/* 信号卡片 */
.sig-card {
  border-radius: 16rpx; /* 8px */
}
.sig-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.sig-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.sig-badge {
  font-size: 22rpx;
  color: #ffffff;
  background: #6b7280; /* 兜底：未知信号按中性灰 */
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  line-height: 1.6;
  flex-shrink: 0;
}
.sig-badge.buy {
  background: #10b981;
}
.sig-badge.hold,
.sig-badge.ignore {
  background: #6b7280;
}
.sig-badge.sell {
  background: #ef4444;
}
.sig-badge.rebalance {
  background: #f59e0b;
}
.sig-title {
  font-size: 30rpx;
  font-weight: 500;
}
.expand-icon {
  font-size: 22rpx;
  color: #86909c;
  flex-shrink: 0;
}
.sig-sub {
  font-size: 24rpx;
  margin-top: 8rpx;
  display: flex;
  gap: 24rpx;
}
.confidence {
  color: #4e5969;
}
.sig-status {
  font-size: 24rpx;
  color: #86909c;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.sig-status.active {
  color: #d46b08;
}
.sig-summary {
  font-size: 26rpx;
  color: #4e5969;
  margin-top: 12rpx;
  line-height: 1.6;
}
.sig-body {
  margin-top: 16rpx;
  border-top: 1rpx solid #f0f1f3;
  padding-top: 16rpx;
}
.sig-line {
  font-size: 26rpx;
  line-height: 1.8;
  display: flex;
  gap: 16rpx;
}
.sig-line .muted {
  width: 64rpx;
  flex-shrink: 0;
}

/* 规则明细 */
.signal-detail {
  margin-top: 16rpx;
  border-top: 1rpx solid #f0f1f3;
  padding-top: 16rpx;
}
.rule-row {
  display: flex;
  gap: 12rpx;
  padding: 10rpx 0;
}
.rule-dot {
  font-size: 22rpx;
  line-height: 1.8;
  flex-shrink: 0;
}
.rule-dot.hit {
  color: #10b981;
}
.rule-dot.miss {
  color: #c9cdd4;
}
.rule-main {
  flex: 1;
  min-width: 0;
}
.rule-line1 {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.rule-name {
  font-size: 26rpx;
  color: #1d2129;
}
.rule-signal {
  font-size: 20rpx;
  padding: 0 10rpx;
  border-radius: 6rpx;
  color: #ffffff;
  line-height: 1.7;
}
.rule-signal.buy {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}
.rule-signal.sell {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}
.rule-signal.hold {
  background: rgba(107, 114, 128, 0.15);
  color: #6b7280;
}
.rule-signal.rebalance {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}
.rule-weight {
  font-size: 22rpx;
  color: #86909c;
}
.rule-value {
  font-size: 24rpx;
  color: #1652a8;
  margin-left: auto;
}
.rule-desc {
  display: block;
  font-size: 24rpx;
  color: #86909c;
  margin-top: 4rpx;
  line-height: 1.6;
}

.sig-actions {
  display: flex;
  gap: 20rpx;
  margin-top: 20rpx;
}
.mini-btn {
  flex: 1;
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #1d2129;
  font-size: 26rpx;
  line-height: 2.2;
  padding: 0;
}
.mini-btn.primary {
  background: #1652a8;
  border-color: #1652a8;
  color: #ffffff;
}

/* 纸面交易卡片 */
.paper-card {
  border-radius: 16rpx; /* 8px */
}
.paper-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.paper-status {
  font-size: 22rpx;
  padding: 2rpx 14rpx;
  border-radius: 8rpx;
  line-height: 1.8;
}
.paper-status.open {
  color: #1652a8;
  background: rgba(22, 82, 168, 0.1);
}
.paper-status.closed {
  color: #86909c;
  background: #f2f3f5;
}
.paper-return {
  font-size: 30rpx;
  font-weight: 500;
}
.paper-return.profit {
  color: #10b981;
}
.paper-return.loss {
  color: #ef4444;
}
.paper-line {
  font-size: 26rpx;
  margin-top: 12rpx;
}
.paper-sub {
  font-size: 24rpx;
  margin-top: 4rpx;
  text-align: right;
}

/* 策略说明弹窗 */
.strategy-modal {
  position: fixed;
  inset: 0;
  background: rgba(29, 33, 41, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal-content {
  width: 620rpx;
  max-height: 70vh;
  overflow-y: auto;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 32rpx;
  box-sizing: border-box;
}
.modal-title {
  font-size: 32rpx;
  font-weight: 500;
  margin-bottom: 20rpx;
}
.modal-empty {
  font-size: 26rpx;
  line-height: 1.7;
}
.modal-rule {
  padding: 16rpx 0;
  border-top: 1rpx solid #f0f1f3;
}
.modal-rule-line {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.rule-hit {
  font-size: 22rpx;
  margin-left: auto;
}
.modal-close {
  margin-top: 24rpx;
}

.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
</style>
