<script setup lang="ts">
import { ref } from 'vue'
import { onPullDownRefresh, onUnload } from '@dcloudio/uni-app'
import { getLatestReport, generateReport, getReportStatus } from '@/api/invest'
import { showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'
import { parseMarkdown, type MdBlock } from '@/utils/markdown-lite'
import type { ReportJobStatus } from '@/types'

const loading = ref(true)
const fileName = ref('')
const blocks = ref<MdBlock[]>([])
// 生成任务态（P12）：触发后台生成 → 轮询 → 完成刷新正文
const genStatus = ref<ReportJobStatus | null>(null)
const withAi = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  try {
    await ensureLogin() // gateway 模式：等启动静默登录完成（单飞复用）
    const res = await getLatestReport()
    if (res.report === null) {
      fileName.value = ''
      blocks.value = []
    } else {
      fileName.value = res.file
      blocks.value = parseMarkdown(res.markdown)
    }
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

async function onGenerate() {
  try {
    await generateReport(withAi.value)
    uni.showToast({ title: withAi.value ? '生成中（含AI解读，约1分钟）' : '生成中', icon: 'none' })
    poll()
  } catch (e) {
    showApiError(e)
  }
}

function poll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      genStatus.value = await getReportStatus()
      if (genStatus.value.status === 'done') {
        stopPoll()
        load()
        uni.showToast({ title: '周报已更新', icon: 'success' })
      } else if (genStatus.value.status === 'error') {
        stopPoll()
        uni.showToast({ title: '生成失败，详情看本机日志', icon: 'none' })
      }
    } catch {
      stopPoll()
    }
  }, 2500)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnload(stopPoll)

/** 表格列数不齐时补空，避免 flex 错位 */
function normRows(rows: string[][]): string[][] {
  let n = 1
  for (const r of rows) n = Math.max(n, r.length)
  return rows.map((r) => [...r, ...Array(n - r.length).fill('')])
}

onPullDownRefresh(async () => {
  await load()
  uni.stopPullDownRefresh()
})
load()
</script>

<template>
  <view class="page">
    <!-- 生成条（P12） -->
    <view class="card gen-card">
      <view class="gen-left">
        <text class="gen-label">生成新周报</text>
        <view class="gen-ai" @tap="withAi = !withAi">
          <view class="checkbox" :class="{ on: withAi }">{{ withAi ? '✓' : '' }}</view>
          <text class="muted">附 GLM 解读</text>
        </view>
      </view>
      <button class="gen-btn" :disabled="genStatus?.status === 'running'" @tap="onGenerate">
        {{ genStatus?.status === 'running' ? '生成中…' : '生成' }}
      </button>
    </view>

    <view v-if="fileName" class="card file-name muted">{{ fileName }}</view>

    <view v-if="!loading && !fileName" class="card empty">
      暂无周报。可在本机执行 `invest report`，或等 cron 生成后再来看。
    </view>

    <view v-for="(b, i) in blocks" :key="i" class="block">
      <view v-if="b.kind === 'h1'" class="h1">{{ b.text }}</view>
      <view v-else-if="b.kind === 'h2'" class="h2">{{ b.text }}</view>
      <view v-else-if="b.kind === 'h3'" class="h3">{{ b.text }}</view>
      <view v-else-if="b.kind === 'quote'" class="quote muted">{{ b.text }}</view>
      <view v-else-if="b.kind === 'li'" class="li"><text class="dot">·</text>{{ b.text }}</view>
      <view v-else-if="b.kind === 'table'" class="card table-card">
        <view v-for="(r, ri) in normRows(b.rows || [])" :key="ri" class="trow" :class="{ head: ri === 0 }">
          <text v-for="(c, ci) in r" :key="ci" class="tcell">{{ c }}</text>
        </view>
      </view>
      <view v-else class="p">{{ b.text }}</view>
    </view>
    <view class="bottom-space" />
  </view>
</template>

<style scoped>
.gen-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20rpx 24rpx;
}
.gen-left {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}
.gen-label {
  font-size: 28rpx;
  font-weight: 500;
}
.gen-ai {
  display: flex;
  align-items: center;
}
.checkbox {
  width: 30rpx;
  height: 30rpx;
  border: 1rpx solid #c9cdd4;
  border-radius: 6rpx;
  margin-right: 10rpx;
  font-size: 22rpx;
  color: #ffffff;
  line-height: 30rpx;
  text-align: center;
}
.checkbox.on {
  background: #1652a8;
  border-color: #1652a8;
}
.gen-btn {
  background: #1652a8;
  color: #ffffff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.3;
  padding: 0 40rpx;
  margin: 0;
}
.file-name {
  font-size: 22rpx;
  padding: 16rpx 24rpx;
}
.h1 {
  font-size: 40rpx;
  font-weight: 600;
  margin: 32rpx 24rpx 8rpx;
}
.h2 {
  font-size: 32rpx;
  font-weight: 600;
  margin: 28rpx 24rpx 8rpx;
  padding-left: 16rpx;
  border-left: 6rpx solid #1652a8;
}
.h3 {
  font-size: 28rpx;
  font-weight: 500;
  margin: 24rpx 24rpx 6rpx;
}
.p {
  font-size: 26rpx;
  line-height: 1.8;
  margin: 8rpx 24rpx;
}
.li {
  font-size: 26rpx;
  line-height: 1.8;
  margin: 4rpx 24rpx;
  display: flex;
}
.dot {
  margin-right: 12rpx;
  color: #86909c;
}
.quote {
  font-size: 24rpx;
  margin: 12rpx 24rpx;
  padding-left: 16rpx;
  border-left: 4rpx solid #e5e6eb;
  line-height: 1.7;
}
.table-card {
  margin: 12rpx 24rpx;
  padding: 8rpx 16rpx;
  overflow-x: auto;
}
.trow {
  display: flex;
  border-bottom: 1rpx solid #f0f1f3;
  padding: 10rpx 0;
}
.trow:last-child {
  border-bottom: none;
}
.trow.head {
  color: #86909c;
  font-size: 24rpx;
}
.tcell {
  flex: 1;
  font-size: 25rpx;
  white-space: nowrap;
  padding-right: 12rpx;
}
.bottom-space {
  height: 40rpx;
}
.empty {
  color: #86909c;
  text-align: center;
  padding: 48rpx 24rpx;
}
</style>
