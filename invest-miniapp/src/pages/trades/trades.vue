<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow, onLoad, onUnload } from '@dcloudio/uni-app'
import { getTrades, addTrade, deleteTrade } from '@/api/invest'
import { showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { fmtQty } from '@/utils/format'
import type { TradeRow, InstrumentBrief } from '@/types'
import { ACTION_LABELS } from '@/types'

const trades = ref<TradeRow[]>([])
const instruments = ref<InstrumentBrief[]>([])
const filterId = ref('')
const loading = ref(false)

// L9 筛选增强：动作类型 + 备注关键词（本地过滤，流水百条内无需服务端）
const filterAction = ref('')
const keyword = ref('')
const ACTION_FILTERS = [
  { value: '', label: '全部动作' },
  { value: 'buy', label: '买入/申购' },
  { value: 'sell', label: '卖出/赎回' },
  { value: 'contribute', label: '缴存' },
  { value: 'dividend_reinvest', label: '红利再投资' },
  { value: 'dividend_cash', label: '现金分红' },
]
const actionFilterLabels = ACTION_FILTERS.map((a) => a.label)

/** 展示列表 = 服务器筛选(标的) ∩ 本地筛选(动作+关键词) */
const shownTrades = computed(() => {
  let rows = trades.value
  if (filterAction.value) rows = rows.filter((t) => t.action === filterAction.value)
  const kw = keyword.value.trim()
  if (kw) rows = rows.filter((t) => (t.note || '').includes(kw) || t.instrument_id.includes(kw))
  return rows
})

// 录入表单状态
const showForm = ref(false)
const form = ref({
  instrument_id: '',
  action: 'buy',
  date: new Date().toISOString().slice(0, 10),
  quantity: '',
  price: '',
  fee: '',
  note: '',
})
const submitting = ref(false)
// L1 录入体验：按金额模式（金额÷最新净值自动折算份额）——买入通常只知道花了多少钱
const byAmount = ref(false)
const amountInput = ref('')

const currentInstrument = computed(() =>
  instruments.value.find((i) => i.id === form.value.instrument_id),
)
const currentPrice = computed(() => currentInstrument.value?.price ?? null)

/** 切换标的/动作时：预填最新净值；按金额模式同步重算份额 */
function syncPrice() {
  if (currentPrice.value !== null) {
    form.value.price = String(currentPrice.value)
    if (byAmount.value) recalcFromAmount()
  }
}

function recalcFromAmount() {
  const amt = Number(amountInput.value)
  const px = Number(form.value.price)
  if (amt > 0 && px > 0) {
    form.value.quantity = String(Math.round((amt / px) * 100) / 100) // 分两位，账本校验两位
  }
}

function toggleAmountMode() {
  byAmount.value = !byAmount.value
  if (byAmount.value) {
    syncPrice()
    amountInput.value = ''
  }
}

const actionOptions = [
  { value: 'buy', label: '买入/申购' },
  { value: 'sell', label: '卖出/赎回' },
  { value: 'contribute', label: '缴存（养老金）' },
  { value: 'dividend_cash', label: '现金分红' },
  { value: 'dividend_reinvest', label: '红利再投资' },
  { value: 'adjust', label: '份额校准' },
]
const actionLabels = actionOptions.map((a) => a.label)
const actionIndex = computed(() => {
  const i = actionOptions.findIndex((a) => a.value === form.value.action)
  return i >= 0 ? i : 0
})
const instrumentNames = computed(() => instruments.value.map((i) => i.name))
const instrumentIndex = computed(() => {
  const i = instruments.value.findIndex((x) => x.id === form.value.instrument_id)
  return i >= 0 ? i : 0
})

async function load() {
  loading.value = true
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用）
    const payload = await getTrades(filterId.value || undefined)
    trades.value = payload.trades
    instruments.value = payload.instruments
    uni.setStorageSync('invest_cache_trades', JSON.stringify({ trades: payload.trades, instruments: payload.instruments }))
  } catch (e) {
    // 失败回退缓存（弱网/后端未起时保可用）
    if (!trades.value.length) {
      try {
        const raw = uni.getStorageSync('invest_cache_trades')
        if (raw) {
          const obj = JSON.parse(raw)
          trades.value = obj.trades || []
          instruments.value = obj.instruments || []
        }
      } catch {
        /* 忽略 */
      }
    }
    showApiError(e)
  } finally {
    loading.value = false
  }
}

function openAdd() {
  onAdd()
}

function onOpenOcr() {
  uni.navigateTo({ url: '/pages/ocr/ocr' })
}

function onAdd() {
  if (!instruments.value.length) {
    uni.showToast({ title: '无可用标的，请先在本机配置', icon: 'none' })
    return
  }
  // R9 最近标的记忆：上次录入的标的优先
  const recent = uni.getStorageSync('invest_recent_instrument')
  const pick = instruments.value.find((i) => i.id === recent) || instruments.value[0]
  form.value = {
    instrument_id: pick.id,
    action: 'buy',
    date: new Date().toISOString().slice(0, 10),
    quantity: '',
    price: '',
    fee: '',
    note: '',
  }
  byAmount.value = false
  amountInput.value = ''
  syncPrice() // 预填最新净值
  showForm.value = true
}

function onPickInstrument(e: { detail: { value: number } }) {
  form.value.instrument_id = instruments.value[e.detail.value]?.id || ''
  syncPrice()
}

function onPickAction(e: { detail: { value: number } }) {
  form.value.action = actionOptions[e.detail.value]?.value || 'buy'
}

function onPickDate(e: { detail: { value: string } }) {
  form.value.date = e.detail.value
}

async function onSubmit() {
  const f = form.value
  if (!f.instrument_id) return uni.showToast({ title: '请选择标的', icon: 'none' })
  const qty = Number(f.quantity)
  const price = Number(f.price)
  if (!f.quantity || Number.isNaN(qty) || qty <= 0) return uni.showToast({ title: '数量需为正数', icon: 'none' })
  if (f.price === '' || Number.isNaN(price)) return uni.showToast({ title: '请填写价格', icon: 'none' })
  submitting.value = true
  try {
    uni.setStorageSync('invest_recent_instrument', f.instrument_id)
    await addTrade({
      instrument_id: f.instrument_id,
      action: f.action,
      date: f.date,
      quantity: qty,
      price,
      fee: f.fee ? Number(f.fee) : 0,
      note: f.note,
    })
    uni.showToast({ title: '已记录', icon: 'success' })
    showForm.value = false
    load()
  } catch (e) {
    showApiError(e)
  } finally {
    submitting.value = false
  }
}

function onDelete(t: TradeRow) {
  uni.showModal({
    title: '删除流水',
    content: `${t.date} ${t.instrument_id} ${ACTION_LABELS[t.action] || t.action}，确认删除？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteTrade({
          date: t.date,
          instrument_id: t.instrument_id,
          action: t.action,
          quantity: `${t.quantity.toFixed(2)}`,
          price: `${t.price.toFixed(4)}`,
          fee: t.fee ? `${t.fee.toFixed(2)}` : '',
          note: t.note || '',
        })
        uni.showToast({ title: '已删除', icon: 'success' })
        load()
      } catch (e) {
        showApiError(e)
      }
    },
  })
}

onShow(load)
onLoad(() => {
  uni.$on('invest-quick-add', openAdd)
})
onUnload(() => {
  uni.$off('invest-quick-add', openAdd)
})
defineExpose({ openAdd })
</script>

<template>
  <view class="page">
    <!-- 标的筛选 -->
    <view class="filter-row">
      <picker :range="['全部标的', ...instrumentNames]" @change="(e: any) => { filterId = e.detail.value === 0 ? '' : (instruments[e.detail.value - 1]?.id || ''); load() }">
        <view class="filter-btn">
          {{ filterId === '' ? '全部标的' : (instruments.find((i) => i.id === filterId)?.name || '全部标的') }}
          <text class="muted">▾</text>
        </view>
      </picker>
      <picker mode="selector" :range="actionFilterLabels" @change="(e: any) => { filterAction = ACTION_FILTERS[Number(e.detail.value)]?.value || '' }">
        <view class="filter-btn">
          {{ ACTION_FILTERS.find((a) => a.value === filterAction)?.label || '全部动作' }}
          <text class="muted">▾</text>
        </view>
      </picker>
      <button class="primary-btn" @tap="onAdd">记一笔</button>
    </view>
    <view class="ocr-entry muted" @tap="onOpenOcr">截图识别录入 ›</view>
    <view class="search-row">
      <input v-model="keyword" class="search-input" placeholder="搜索备注/标的关键词" confirm-type="search" />
      <text class="muted count">{{ shownTrades.length }} 笔</text>
    </view>

    <!-- 流水列表 -->
    <view class="card list-card">
      <view v-if="!trades.length && !loading" class="empty">
        <view class="empty-title">暂无流水——品类记账口径速查</view>
        <view class="cq">场外基金：申购按金额录（录法切「按金额」，自动折份额），分红用「红利再投资」</view>
        <view class="cq">ETF/股票/债券：买卖录份额×价格，动词自动切换为买入/卖出</view>
        <view class="cq">理财/固收：申购可 price=1（金额即份额），净值用详情页「记净值」维护</view>
        <view class="cq">养老金：缴存用「缴存」动作（只进现金流与年度额度），再用「申购」买基金</view>
      </view>
      <view v-for="(t, i) in shownTrades" :key="i" class="trade-row" @longpress="onDelete(t)">
        <view class="pos-main">
          <view class="trade-title">
            <text class="action-tag">{{ t.action_label || ACTION_LABELS[t.action] || t.action }}</text>
            <text class="trade-name">{{ t.instrument_id }}</text>
          </view>
          <view class="muted trade-sub">
            {{ t.date }} · {{ fmtQty(t.quantity) }} × {{ t.price }}<text v-if="t.fee"> · 费 {{ t.fee }}</text>
            <text v-if="t.note"> · {{ t.note }}</text>
          </view>
        </view>
        <view class="trade-amt" :class="{ out: t.action === 'buy' || t.action === 'contribute' }">
          {{ t.action === 'sell' || t.action === 'dividend_cash' ? '+' : '-' }}{{ fmtQty(t.quantity * t.price) }}
        </view>
      </view>
      <view class="muted hint">长按某行可删除</view>
    </view>

    <!-- 录入弹层 -->
    <view v-if="showForm" class="mask" @tap="showForm = false">
      <view class="sheet" @tap.stop>
        <view class="sheet-title">记一笔</view>
        <view class="form-row">
          <text class="form-label">标的</text>
          <picker mode="selector" :range="instrumentNames" :value="instrumentIndex" @change="onPickInstrument">
            <view class="form-value">{{ instruments.find((i) => i.id === form.instrument_id)?.name || '请选择' }}</view>
          </picker>
        </view>
        <view class="form-row">
          <text class="form-label">动作</text>
          <picker mode="selector" :range="actionLabels" :value="actionIndex" @change="onPickAction">
            <view class="form-value">{{ actionOptions[actionIndex]?.label }}</view>
          </picker>
        </view>
        <view class="form-row">
          <text class="form-label">日期</text>
          <picker mode="date" :value="form.date" @change="onPickDate">
            <view class="form-value">{{ form.date }}</view>
          </picker>
        </view>
        <!-- L1 按金额录入：金额÷最新净值自动折算份额（仅 buy/contribute 有意义） -->
        <view v-if="form.action === 'buy' || form.action === 'contribute'" class="form-row" @tap="toggleAmountMode">
          <text class="form-label">录法</text>
          <view class="mode-switch">
            <text :class="['mode-opt', { on: !byAmount }]">按份额</text>
            <text :class="['mode-opt', { on: byAmount }]">按金额</text>
          </view>
        </view>
        <view v-if="byAmount && (form.action === 'buy' || form.action === 'contribute')" class="form-row">
          <text class="form-label">金额(元)</text>
          <input v-model="amountInput" type="digit" class="form-input" placeholder="如 5000" @input="recalcFromAmount" />
        </view>
        <view class="form-row">
          <text class="form-label">数量/份额</text>
          <input
            v-model="form.quantity"
            type="digit"
            class="form-input"
            :class="{ derived: byAmount }"
            :disabled="byAmount"
            :placeholder="byAmount ? '按金额自动折算' : '0.00'"
          />
        </view>
        <view class="form-row">
          <text class="form-label">价格/净值</text>
          <input v-model="form.price" type="digit" class="form-input" placeholder="0.0000" @input="byAmount && recalcFromAmount()" />
          <text v-if="currentPrice !== null" class="muted price-hint">最新 {{ currentPrice }}</text>
        </view>
        <view class="form-row">
          <text class="form-label">费用</text>
          <input v-model="form.fee" type="digit" class="form-input" placeholder="可空" />
        </view>
        <view class="form-row">
          <text class="form-label">备注</text>
          <input v-model="form.note" class="form-input" placeholder="可空" />
        </view>
        <button class="primary-btn block" :disabled="submitting" @tap="onSubmit">
          {{ submitting ? '提交中' : '保存' }}
        </button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 20rpx 24rpx 0;
}
.filter-btn {
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  padding: 10rpx 24rpx;
  font-size: 26rpx;
}
.ocr-entry {
  font-size: 24rpx;
  margin: 12rpx 24rpx 0;
  color: #1652a8;
}
.search-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin: 16rpx 24rpx 0;
}
.search-input {
  flex: 1;
  background: #ffffff;
  border: 1rpx solid #e5e6eb;
  border-radius: 10rpx;
  padding: 10rpx 20rpx;
  font-size: 26rpx;
}
.count {
  font-size: 24rpx;
  flex-shrink: 0;
}
.primary-btn {
  background: #1652a8;
  color: #ffffff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.4;
  padding: 0 32rpx;
}
.primary-btn.block {
  width: 100%;
  margin-top: 28rpx;
}
.list-card {
  padding: 8rpx 24rpx;
}
.trade-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.trade-row:last-of-type {
  border-bottom: none;
}
.trade-title {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.action-tag {
  font-size: 22rpx;
  color: #1652a8;
  background: #eef3fb;
  border-radius: 6rpx;
  padding: 2rpx 10rpx;
}
.trade-name {
  font-size: 28rpx;
}
.trade-sub {
  font-size: 24rpx;
  margin-top: 6rpx;
}
.trade-amt {
  font-size: 28rpx;
  color: #2e9e5b;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.trade-amt.out {
  color: #1d2129;
}
.hint {
  font-size: 22rpx;
  padding: 12rpx 0;
  text-align: center;
}
.empty {
  color: #86909c;
  text-align: left;
  padding: 32rpx 8rpx 48rpx;
}
.empty-title {
  text-align: center;
  font-size: 28rpx;
  font-weight: 500;
  color: #1d2129;
  margin-bottom: 12rpx;
}
.cq {
  font-size: 25rpx;
  line-height: 2;
  color: #4e5969;
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
  max-height: 85vh;
  overflow-y: auto;
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
  width: 170rpx;
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
.form-input.derived {
  color: #86909c;
}
.price-hint {
  font-size: 22rpx;
  margin-left: 12rpx;
  flex-shrink: 0;
}
.mode-switch {
  flex: 1;
  display: flex;
  justify-content: flex-end;
  gap: 12rpx;
}
.mode-opt {
  font-size: 26rpx;
  color: #86909c;
  border: 1rpx solid #e5e6eb;
  border-radius: 8rpx;
  padding: 4rpx 20rpx;
}
.mode-opt.on {
  color: #1652a8;
  border-color: #1652a8;
  background: #eef3fb;
}
</style>
