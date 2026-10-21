<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'

interface InsRow {
  id: string
  name: string
  type: string
  code: string
  benchmark_index: string
  account: string
  held_qty: number
  from_db: boolean
}

const rows = ref<InsRow[]>([])
const loading = ref(true)
const showForm = ref(false)
const editing = ref(false)
const submitting = ref(false)
const form = ref({ id: '', name: '', type: 'open_end_fund', code: '', benchmark_index: '', account: '' })
const delHint = ref('')

const TYPES = [
  { value: 'open_end_fund', label: '场外基金' },
  { value: 'etf', label: 'ETF' },
  { value: 'stock', label: '股票' },
  { value: 'bond', label: '债券' },
  { value: 'wealth', label: '理财/固收' },
]
const typeLabels = TYPES.map((t) => t.label)
const typeLabel = (t: string) => TYPES.find((x) => x.value === t)?.label || t

async function load() {
  loading.value = true
  try {
    await ensureLogin()
    const d = await request<{ instruments: InsRow[] }>({ url: '/instruments' })
    rows.value = d.instruments
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

function onNew() {
  form.value = { id: '', name: '', type: 'open_end_fund', code: '', benchmark_index: '', account: '' }
  editing.value = false
  showForm.value = true
}

function onEdit(r: InsRow) {
  form.value = { id: r.id, name: r.name, type: r.type, code: r.code, benchmark_index: r.benchmark_index, account: r.account }
  editing.value = true
  showForm.value = true
}

function onPickType(e: { detail: { value: number } }) {
  form.value.type = TYPES[Number(e.detail.value)]?.value || 'open_end_fund'
}

async function onSubmit() {
  const f = form.value
  if (!editing.value && !/^[a-z0-9_]{2,32}$/.test(f.id)) {
    uni.showToast({ title: '标识需 2-32 位小写字母/数字/下划线', icon: 'none' })
    return
  }
  if (!f.name.trim()) {
    uni.showToast({ title: '请填名称', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    await request({ url: '/instruments', method: 'POST', data: f })
    uni.showToast({ title: editing.value ? '已更新' : '已添加（拉数后生效）', icon: 'success' })
    showForm.value = false
    load()
  } catch (e) {
    showApiError(e)
  } finally {
    submitting.value = false
  }
}

function onDelete(r: InsRow) {
  if (!r.from_db) {
    uni.showToast({ title: '配置文件种子标的，请在 Mac 配置中删除', icon: 'none', duration: 2500 })
    return
  }
  if (r.held_qty > 0) {
    uni.showToast({ title: '有持仓流水，清仓后才能删除', icon: 'none' })
    return
  }
  uni.showModal({
    title: '删除标的',
    content: `删除 ${r.name}（${r.id}）？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await request({ url: '/instruments/delete', method: 'POST', data: { id: r.id } })
        load()
      } catch (e) {
        showApiError(e)
      }
    },
  })
}

onShow(load)
</script>

<template>
  <view class="page">
    <view class="card head-card">
      <view class="head-title">标的管理</view>
      <view class="muted sub">新增/修改即时生效；添加后到设置页「开始拉数」抓行情，理财/固收无需代码（详情页记净值）。</view>
      <button class="primary-btn block" @tap="onNew">添加标的</button>
    </view>

    <view v-for="r in rows" :key="r.id" class="card">
      <view class="row-head">
        <view class="row-main">
          <view class="row-name">
            <text class="type-tag">{{ typeLabel(r.type) }}</text>
            <text class="name">{{ r.name }}</text>
          </view>
          <view class="muted row-sub">
            {{ r.id }}<text v-if="r.code"> · {{ r.code }}</text><text v-if="r.account"> · {{ r.account }}</text>
            · 持仓 {{ r.held_qty }}
          </view>
        </view>
        <view class="row-ops">
          <text class="op" @tap="onEdit(r)">编辑</text>
          <text class="op danger" @tap="onDelete(r)">删除</text>
        </view>
      </view>
    </view>

    <view v-if="!rows.length && !loading" class="card empty">暂无标的，点上方「添加标的」开始</view>

    <view v-if="showForm" class="mask" @tap="showForm = false">
      <view class="sheet" @tap.stop>
        <view class="sheet-title">{{ editing ? '编辑标的' : '添加标的' }}</view>
        <view class="form-row">
          <text class="form-label">标识</text>
          <input v-model="form.id" class="form-input" :disabled="editing" placeholder="如 my_fund（小写/数字/_）" />
        </view>
        <view class="form-row">
          <text class="form-label">名称</text>
          <input v-model="form.name" class="form-input" placeholder="展示名称" />
        </view>
        <view class="form-row">
          <text class="form-label">品类</text>
          <picker mode="selector" :range="typeLabels" @change="onPickType">
            <view class="form-value">{{ typeLabel(form.type) }}</view>
          </picker>
        </view>
        <view class="form-row">
          <text class="form-label">代码</text>
          <input v-model="form.code" class="form-input" placeholder="基金/股票代码；债券带前缀；理财留空" />
        </view>
        <view class="form-row">
          <text class="form-label">基准指数</text>
          <input v-model="form.benchmark_index" class="form-input" placeholder="可空，如 中证红利" />
        </view>
        <view class="form-row">
          <text class="form-label">账户</text>
          <input v-model="form.account" class="form-input" placeholder="如 pension / a_stock / bank" />
        </view>
        <button class="primary-btn block" :disabled="submitting" @tap="onSubmit">
          {{ submitting ? '保存中' : '保存' }}
        </button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.head-title {
  font-size: 34rpx;
  font-weight: 600;
}
.sub {
  font-size: 24rpx;
  line-height: 1.7;
  margin: 10rpx 0 20rpx;
}
.primary-btn {
  background: #1652a8;
  color: #fff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.4;
}
.primary-btn.block {
  width: 100%;
}
.row-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.row-main {
  flex: 1;
  min-width: 0;
}
.row-name {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.type-tag {
  font-size: 22rpx;
  color: #1652a8;
  background: #eef3fb;
  border-radius: 6rpx;
  padding: 2rpx 10rpx;
  flex-shrink: 0;
}
.name {
  font-size: 28rpx;
}
.row-sub {
  font-size: 22rpx;
  margin-top: 6rpx;
}
.row-ops {
  display: flex;
  gap: 24rpx;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.op {
  font-size: 24rpx;
  color: #1652a8;
}
.op.danger {
  color: #d54941;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
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
  background: #fff;
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
  width: 140rpx;
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
</style>
