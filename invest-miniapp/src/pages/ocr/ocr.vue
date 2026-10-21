<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { getServer, getToken } from '@/api/config'
import { fmtQty } from '@/utils/format'
import type { InstrumentBrief } from '@/types'
import { ACTION_LABELS } from '@/types'

interface Draft {
  date: string
  action: string
  instrument_id: string
  quantity: number | string
  price: number | string
  fee: number | string
  note: string
}

const instruments = ref<InstrumentBrief[]>([])
const ocrText = ref('')
const drafts = ref<Draft[]>([])
const aiParsed = ref(false)
const busy = ref(false)
const savedIdx = ref<Set<number>>(new Set())

async function loadInstruments() {
  try {
    await ensureLogin()
    const d = await request<{ instruments: InstrumentBrief[] }>({ url: '/trades', params: { limit: 1 } })
    instruments.value = d.instruments
  } catch (e) {
    showApiError(e)
  }
}

/** 拍照/相册 → 上传 → OCR+结构化 */
function onPick() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    success: (res) => {
      const path = res.tempFilePaths?.[0]
      if (path) upload(path)
    },
  })
}

function upload(filePath: string) {
  busy.value = true
  drafts.value = []
  ocrText.value = ''
  savedIdx.value = new Set()
  const server = getServer()
  if (!server) {
    busy.value = false
    uni.showToast({ title: '未配置服务器地址', icon: 'none' })
    return
  }
  uni.uploadFile({
    url: `${server}/api/invest/ocr`,
    filePath,
    name: 'file',
    header: { Authorization: `Bearer ${getToken()}` },
    success: (res) => {
      if (res.statusCode !== 200) {
        let msg = `识别失败（HTTP ${res.statusCode}）`
        try {
          msg = JSON.parse(res.data).error || msg
        } catch { /* 保持默认 */ }
        uni.showToast({ title: msg, icon: 'none', duration: 3000 })
        return
      }
      const data = JSON.parse(res.data)
      ocrText.value = data.text || ''
      aiParsed.value = !!data.ai_parsed
      drafts.value = (data.trades || []).map((t: Draft) => ({
        date: t.date,
        action: t.action,
        instrument_id: t.instrument_id || (instruments.value[0]?.id ?? ''),
        quantity: t.quantity,
        price: t.price,
        fee: t.fee || 0,
        note: t.note || '',
      }))
      if (!drafts.value.length) {
        uni.showToast({
          title: aiParsed.value ? '未识别出交易行（可看原文手动整理）' : 'OCR 完成（无 AI Key，请对照原文手动录入）',
          icon: 'none',
          duration: 3000,
        })
      }
    },
    fail: (e) => uni.showToast({ title: `上传失败：${e.errMsg || ''}`, icon: 'none' }),
    complete: () => { busy.value = false },
  })
}

function actionLabel(a: string): string {
  return ACTION_LABELS[a] || a
}

function onPickIns(idx: number, e: { detail: { value: number } }) {
  drafts.value[idx].instrument_id = instruments.value[Number(e.detail.value)]?.id || ''
}

async function onSaveOne(i: number) {
  const d = drafts.value[i]
  const qty = Number(d.quantity)
  const price = Number(d.price)
  if (!d.instrument_id || !qty || !price) {
    uni.showToast({ title: '该行信息不全，请补齐', icon: 'none' })
    return
  }
  try {
    await request({
      url: '/trades', method: 'POST',
      data: { ...d, quantity: qty, price, fee: Number(d.fee) || 0 },
    })
    savedIdx.value.add(i)
    uni.showToast({ title: '已录入', icon: 'success' })
  } catch (e) {
    showApiError(e)
  }
}

onShow(loadInstruments)
</script>

<template>
  <view class="page">
    <view class="card">
      <view class="card-title">截图识别录入</view>
      <view class="muted sub">支持券商/基金/银行 App 的交易确认或持仓截图（png/jpg ≤5MB）。本地 OCR 识别 + AI 整理成流水草稿，逐条确认后入账。</view>
      <button class="primary-btn block" :disabled="busy" @tap="onPick">
        {{ busy ? '识别中…' : '拍照 / 从相册选择' }}
      </button>
    </view>

    <!-- 识别草稿 -->
    <view v-for="(d, i) in drafts" :key="i" class="card draft-card" :class="{ saved: savedIdx.has(i) }">
      <view class="draft-head">
        <text class="tag">{{ actionLabel(d.action) }}</text>
        <text class="date">{{ d.date }}</text>
        <text v-if="savedIdx.has(i)" class="saved-mark">已录入</text>
      </view>
      <view class="row">
        <text class="lbl">标的</text>
        <picker mode="selector" :range="instruments.map((x) => x.name)" @change="(e: any) => onPickIns(i, e)">
          <view class="val">{{ instruments.find((x) => x.id === d.instrument_id)?.name || '选择标的' }}</view>
        </picker>
      </view>
      <view class="row-grid">
        <view class="row"><text class="lbl">份额</text><input v-model="d.quantity" type="digit" class="inp" /></view>
        <view class="row"><text class="lbl">净值</text><input v-model="d.price" type="digit" class="inp" /></view>
        <view class="row"><text class="lbl">费用</text><input v-model="d.fee" type="digit" class="inp" /></view>
      </view>
      <view class="row"><text class="lbl">备注</text><input v-model="d.note" class="inp" placeholder="可改" /></view>
      <button v-if="!savedIdx.has(i)" class="primary-btn block" @tap="onSaveOne(i)">确认录入</button>
    </view>

    <!-- OCR 原文（降级/核对用） -->
    <view v-if="ocrText" class="card">
      <view class="card-title">识别原文<text v-if="aiParsed" class="muted">（AI 已整理上方草稿）</text></view>
      <view class="ocr-text">{{ ocrText }}</view>
    </view>
  </view>
</template>

<style scoped>
.sub {
  font-size: 24rpx;
  line-height: 1.7;
  margin-bottom: 20rpx;
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
.draft-card.saved {
  opacity: 0.6;
}
.draft-head {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 8rpx;
}
.tag {
  font-size: 22rpx;
  color: #1652a8;
  background: #eef3fb;
  border-radius: 6rpx;
  padding: 2rpx 12rpx;
}
.date {
  font-size: 24rpx;
  color: #4e5969;
}
.saved-mark {
  margin-left: auto;
  font-size: 22rpx;
  color: #2e9e5b;
}
.row {
  display: flex;
  align-items: center;
  border-bottom: 1rpx solid #f0f1f3;
  padding: 16rpx 0;
}
.row-grid {
  display: flex;
  gap: 20rpx;
}
.row-grid .row {
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
  gap: 6rpx;
}
.lbl {
  width: 90rpx;
  font-size: 24rpx;
  color: #4e5969;
  flex-shrink: 0;
}
.row-grid .lbl {
  width: auto;
}
.val {
  flex: 1;
  font-size: 27rpx;
  text-align: right;
}
.inp {
  flex: 1;
  font-size: 27rpx;
  text-align: right;
  border: 1rpx solid #f0f1f3;
  border-radius: 8rpx;
  padding: 6rpx 12rpx;
}
.ocr-text {
  font-size: 24rpx;
  line-height: 1.9;
  white-space: pre-wrap;
  color: #4e5969;
  background: #f7f8fa;
  border-radius: 10rpx;
  padding: 20rpx;
}
</style>
