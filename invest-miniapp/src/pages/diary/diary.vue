<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { request, showApiError } from '@/api/client'
import { ensureLogin } from '@/api/auth'

interface DiaryEntry {
  date: string
  content: string
  mood: string
}

const entries = ref<DiaryEntry[]>([])
const loading = ref(true)
const showForm = ref(false)
const editing = ref(false)
const form = ref({ date: new Date().toISOString().slice(0, 10), content: '', mood: '' })
const submitting = ref(false)

const MOODS = ['平静', '贪婪', '恐惧', '犹豫', '坚定']

// 中文情绪词不能直接当 class：WXSS 解析器不支持 \XXXX unicode 转义，会编译报错炸掉启动
const MOOD_CLASS: Record<string, string> = {
  '贪婪': 'mood-greed',
  '恐惧': 'mood-fear',
  '坚定': 'mood-steady',
}

async function load() {
  loading.value = true
  try {
    await ensureLogin()
    const d = await request<{ entries: DiaryEntry[] }>({ url: '/diary' })
    entries.value = d.entries
  } catch (e) {
    showApiError(e)
  } finally {
    loading.value = false
  }
}

function onNew() {
  form.value = { date: new Date().toISOString().slice(0, 10), content: '', mood: '' }
  editing.value = false
  showForm.value = true
}

function onEdit(entry: DiaryEntry) {
  form.value = { date: entry.date, content: entry.content, mood: entry.mood }
  editing.value = true
  showForm.value = true
}

function onPickDate(e: { detail: { value: string } }) {
  form.value.date = e.detail.value
}

async function onSubmit() {
  if (!form.value.content.trim()) {
    uni.showToast({ title: '写点什么吧', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    await request({ url: '/diary', method: 'POST', data: form.value })
    uni.showToast({ title: editing.value ? '已更新' : '已记录', icon: 'success' })
    showForm.value = false
    load()
  } catch (e) {
    showApiError(e)
  } finally {
    submitting.value = false
  }
}

function onDelete() {
  uni.showModal({
    title: '删除日记',
    content: `删除 ${form.value.date} 的日记？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await request({ url: '/diary/delete', method: 'POST', data: { date: form.value.date } })
        showForm.value = false
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
      <view class="head-title">投资日记</view>
      <view class="muted head-sub">记录当日的判断与情绪——复盘是把情绪变成纪律的唯一路径</view>
      <button class="primary-btn block" @tap="onNew">写一篇</button>
    </view>

    <view v-if="!entries.length && !loading" class="card empty">还没有日记。任何一天都值得记一笔。</view>

    <view v-for="e in entries" :key="e.date" class="card" @tap="onEdit(e)">
      <view class="e-head">
        <text class="e-date">{{ e.date }}</text>
        <text v-if="e.mood" class="mood-tag" :class="MOOD_CLASS[e.mood]">{{ e.mood }}</text>
      </view>
      <view class="e-content">{{ e.content }}</view>
    </view>

    <view v-if="showForm" class="mask" @tap="showForm = false">
      <view class="sheet" @tap.stop>
        <view class="sheet-title">{{ editing ? '编辑日记' : '写日记' }}</view>
        <view class="form-row">
          <text class="form-label">日期</text>
          <picker mode="date" :value="form.date" @change="onPickDate">
            <view class="form-value">{{ form.date }}</view>
          </picker>
        </view>
        <view class="form-row">
          <text class="form-label">心情</text>
          <view class="mood-row">
            <text
              v-for="m in MOODS"
              :key="m"
              :class="['mood-opt', { on: form.mood === m }]"
              @tap="form.mood = form.mood === m ? '' : m"
            >{{ m }}</text>
          </view>
        </view>
        <view class="form-col">
          <textarea v-model="form.content" class="content-input" placeholder="今天的判断、操作、情绪…" :maxlength="1000" />
        </view>
        <view class="btn-row">
          <button v-if="editing" class="del-btn" @tap="onDelete">删除</button>
          <button class="primary-btn" :disabled="submitting" @tap="onSubmit">
            {{ submitting ? '保存中' : '保存' }}
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.head-title {
  font-size: 34rpx;
  font-weight: 600;
}
.head-sub {
  font-size: 24rpx;
  margin: 10rpx 0 20rpx;
  line-height: 1.6;
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
.e-head {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 10rpx;
}
.e-date {
  font-size: 28rpx;
  font-weight: 500;
}
.mood-tag {
  font-size: 22rpx;
  border-radius: 6rpx;
  padding: 2rpx 12rpx;
  color: #4e5969;
  background: #f2f3f5;
}
.mood-tag.mood-greed { color: #d54941; background: #fdf0ef; }
.mood-tag.mood-fear { color: #2e9e5b; background: #eff7f2; }
.mood-tag.mood-steady { color: #1652a8; background: #eef3fb; }
.e-content {
  font-size: 26rpx;
  line-height: 1.8;
  color: #1d2129;
  white-space: pre-wrap;
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
.mood-row {
  flex: 1;
  display: flex;
  justify-content: flex-end;
  gap: 12rpx;
  flex-wrap: wrap;
}
.mood-opt {
  font-size: 24rpx;
  color: #86909c;
  border: 1rpx solid #e5e6eb;
  border-radius: 8rpx;
  padding: 4rpx 18rpx;
}
.mood-opt.on {
  color: #1652a8;
  border-color: #1652a8;
  background: #eef3fb;
}
.form-col {
  padding: 20rpx 0;
}
.content-input {
  width: 100%;
  min-height: 220rpx;
  background: #f7f8fa;
  border-radius: 10rpx;
  padding: 20rpx;
  font-size: 27rpx;
  line-height: 1.7;
  box-sizing: border-box;
}
.btn-row {
  display: flex;
  gap: 20rpx;
}
.del-btn {
  flex: none;
  background: #fff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #d54941;
  font-size: 26rpx;
  line-height: 2.4;
  padding: 0 40rpx;
}
.btn-row .primary-btn {
  flex: 1;
}
</style>
