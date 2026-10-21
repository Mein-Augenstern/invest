<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { ping, startPull, getPullStatus } from '@/api/invest'
import { request, showApiError } from '@/api/client'
import { silentWxLogin, isLoggedIn, memberLabel, ensureLogin } from '@/api/auth'
import { getServer, setServer, getToken, setToken, getMode, setMode, clearToken } from '@/api/config'
import { listFamilyMembers, listReminderRules, createReminderRule, deleteReminderRule, INVEST_RULE_PREFIX, type FamilyMember, type ReminderRule } from '@/api/star'
import type { PullStatus } from '@/types'

const mode = ref<'gateway' | 'direct'>(getMode())
const serverInput = ref('')
const tokenInput = ref('')
const testing = ref(false)
const loggedIn = ref(isLoggedIn())
const member = ref(memberLabel())
const avatarChar = computed(() => (member.value || '投').slice(0, 1))

// 「我的」折叠面板：空串=全收起；server/reminder/glm/pull/about
const opened = ref('')

function toggle(key: string) {
  opened.value = opened.value === key ? '' : key
}

// S2：GLM Key 状态
const glmConfigured = ref(false)
const glmKeyInput = ref('')

async function loadGlmStatus() {
  try {
    const d = await request<{ configured: boolean }>({ url: '/settings/glm-key' })
    glmConfigured.value = d.configured
  } catch {
    /* 静默 */
  }
}

async function onSaveGlmKey() {
  try {
    const d = await request<{ configured: boolean }>({ url: '/settings/glm-key', method: 'POST', data: { key: glmKeyInput.value.trim() } })
    glmConfigured.value = d.configured
    glmKeyInput.value = ''
    uni.showToast({ title: d.configured ? 'Key 已保存（即时生效）' : 'Key 已清除', icon: 'none' })
  } catch (e) {
    showApiError(e)
  }
}

function go(url: string) {
  uni.navigateTo({ url })
}

// L4 star 提醒集成：家庭成员 + 投资预设提醒
const familyMembers = ref<FamilyMember[]>([])
const memberIdx = ref(0)
const rules = ref<ReminderRule[]>([])
const memberName = computed(() => familyMembers.value[memberIdx.value]?.name || '')
const investRules = computed(() => rules.value.filter((r) => (r.title || '').startsWith(INVEST_RULE_PREFIX)))

async function loadReminders() {
  if (mode.value !== 'gateway' || !isLoggedIn()) return
  try {
    const [members, allRules] = await Promise.all([listFamilyMembers(), listReminderRules()])
    familyMembers.value = members
    rules.value = allRules
    if (members.length && memberIdx.value >= members.length) memberIdx.value = 0
  } catch {
    // 提醒是增强能力：失败静默（家庭服务未配置数据等场景）
  }
}

function nextMonth10th(): string {
  const d = new Date()
  const y = d.getMonth() + 1 > 11 ? d.getFullYear() + 1 : d.getFullYear()
  const m = d.getMonth() + 1 > 11 ? 1 : d.getMonth() + 2
  return `${y}-${String(m).padStart(2, '0')}-10`
}

async function onAddPreset(kind: 'dca' | 'pension') {
  const fm = familyMembers.value[memberIdx.value]
  if (!fm) {
    uni.showToast({ title: '请先在 star 家庭服务中添加成员', icon: 'none' })
    return
  }
  const payload =
    kind === 'dca'
      ? { familyMemberId: fm.id, title: `${INVEST_RULE_PREFIX}定投日（纪律执行）`, firstRemindAt: nextMonth10th(), repeatType: 'MONTHLY' as const }
      : { familyMemberId: fm.id, title: `${INVEST_RULE_PREFIX}养老金缴存补缴检查（缴满抵税额度）`, firstRemindAt: `${new Date().getFullYear()}-11-15`, repeatType: 'ANNUAL' as const }
  try {
    await createReminderRule(payload)
    uni.showToast({ title: '提醒已创建（star 待办中心可见）', icon: 'none' })
    loadReminders()
  } catch (e) {
    showApiError(e)
  }
}

function onDeleteRule(r: ReminderRule) {
  uni.showModal({
    title: '删除提醒',
    content: r.title,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteReminderRule(r.id)
        loadReminders()
      } catch (e) {
        showApiError(e)
      }
    },
  })
}

function repeatLabel(t: string): string {
  return { NONE: '单次', WEEKLY: '每周', MONTHLY: '每月', ANNUAL: '每年' }[t] || t
}
const pull = ref<PullStatus | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 地址提示用通用占位（不写具体内网 IP——本仓公开）；实际地址用户自查本机 IP
const GATEWAY_HINT = 'http://192.168.x.x:8080'
const DIRECT_HINT = 'http://192.168.x.x:8790'
serverInput.value = getServer() || (mode.value === 'gateway' ? GATEWAY_HINT : DIRECT_HINT)
tokenInput.value = getToken()

function switchMode(m: 'gateway' | 'direct') {
  mode.value = m
  setMode(m)
  clearToken() // 切模式清旧令牌（两模式令牌不通用）
  serverInput.value = getServer() || (m === 'gateway' ? GATEWAY_HINT : DIRECT_HINT)
  loggedIn.value = isLoggedIn()
  member.value = memberLabel()
}

async function onSaveAndTest() {
  if (!serverInput.value.trim()) {
    return uni.showToast({ title: '请填写服务器地址', icon: 'none' })
  }
  testing.value = true
  setServer(serverInput.value)
  if (mode.value === 'direct') setToken(tokenInput.value)
  try {
    if (mode.value === 'gateway') {
      const ok = await silentWxLogin()
      loggedIn.value = ok
      member.value = memberLabel()
      await ping()
      uni.showModal({
        title: '连接成功',
        content: ok ? `star 登录成功（${memberLabel() || '微信成员'}），网关与 invest 服务可达。` : '网关可达，但微信登录失败（模拟器需微信登录态）。',
        showCancel: false,
      })
    } else {
      await ping()
      uni.showModal({
        title: '连接成功',
        content: 'invest 服务可达，令牌有效（或服务未启用鉴权）。',
        showCancel: false,
      })
    }
  } catch (e) {
    showApiError(e)
  } finally {
    testing.value = false
  }
}

function onRelogin() {
  clearToken()
  silentWxLogin().then((ok) => {
    loggedIn.value = isLoggedIn()
    member.value = memberLabel()
    uni.showToast({ title: ok ? '已登录' : '登录失败', icon: 'none' })
  })
}

function onLogout() {
  uni.showModal({
    title: '退出登录',
    content: '清除本机令牌后需重新登录才能查看投资数据',
    success: (res) => {
      if (!res.confirm) return
      clearToken()
      loggedIn.value = isLoggedIn()
      member.value = memberLabel()
      uni.showToast({ title: '已退出', icon: 'none' })
    },
  })
}

async function onStartPull() {
  try {
    await startPull()
    uni.showToast({ title: '拉数已开始', icon: 'success' })
    poll()
  } catch (e) {
    showApiError(e)
  }
}

function poll() {
  stopPoll()
  pollTimer = setInterval(async () => {
    try {
      pull.value = await getPullStatus()
      if (pull.value.status !== 'running') stopPoll()
    } catch {
      stopPoll()
    }
  }, 2000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(stopPoll)
onShow(async () => {
  await ensureLogin()
  loggedIn.value = isLoggedIn()
  member.value = memberLabel()
  loadReminders()
  loadGlmStatus()
})
</script>

<template>
  <view class="page">
    <!-- 个人卡（star「我的」视觉，invest 主色） -->
    <view class="profile">
      <view class="avatar">{{ avatarChar }}</view>
      <view class="p-main">
        <view class="p-name">{{ member || '未登录' }}</view>
        <view class="p-sub">投资记账 · star 家庭成员</view>
      </view>
      <text :class="['login-state', loggedIn ? 'success' : 'danger']">
        {{ loggedIn ? '已登录' : '未登录' }}
      </text>
    </view>

    <!-- 我的工具 -->
    <view class="group">
      <view class="cell" hover-class="cell-hover" @tap="go('/pages/instruments/instruments')">
        <view class="cell-t">标的管理</view>
        <view class="cell-arrow">›</view>
      </view>
      <view class="cell" hover-class="cell-hover" @tap="go('/pages/diary/diary')">
        <view class="cell-t">投资日记</view>
        <view class="cell-arrow">›</view>
      </view>
      <view class="cell" hover-class="cell-hover" @tap="go('/pages/valuation/valuation')">
        <view class="cell-t">指数估值表</view>
        <view class="cell-arrow">›</view>
      </view>
      <view class="cell" hover-class="cell-hover" @tap="go('/pages/backtest/backtest')">
        <view class="cell-t">策略回测</view>
        <view class="cell-arrow">›</view>
      </view>
      <view class="cell" hover-class="cell-hover" @tap="go('/pages/annual/annual')">
        <view class="cell-t">年度账单</view>
        <view class="cell-arrow">›</view>
      </view>
    </view>

    <!-- 家庭与提醒（star 待办中心） -->
    <view class="group" v-if="mode === 'gateway'">
      <view class="cell" hover-class="cell-hover" @tap="toggle('reminder')">
        <view class="cell-t">投资提醒</view>
        <view class="cell-tag">star 待办</view>
        <view class="cell-arrow" :class="{ up: opened === 'reminder' }">›</view>
      </view>
      <view v-if="opened === 'reminder'" class="panel">
        <view class="form-row">
          <text class="form-label">提醒对象</text>
          <picker
            v-if="familyMembers.length"
            mode="selector"
            :range="familyMembers.map((m) => m.name)"
            :value="memberIdx"
            @change="(e: any) => { memberIdx = Number(e.detail.value) }"
          >
            <view class="form-value">{{ memberName || '选择成员' }}</view>
          </picker>
          <text v-else class="muted">star 家庭服务暂无成员</text>
        </view>
        <view class="preset-row">
          <button class="mini-btn" @tap="onAddPreset('dca')">建「定投日·每月10号」</button>
          <button class="mini-btn" @tap="onAddPreset('pension')">建「缴存补缴·每年11-15」</button>
        </view>
        <view v-for="r in investRules" :key="r.id" class="rule-row" @longpress="onDeleteRule(r)">
          <view class="rule-main">
            <view class="rule-title">{{ r.title }}</view>
            <view class="muted rule-sub">{{ r.firstRemindAt }} 起 · {{ repeatLabel(r.repeatType) }}</view>
          </view>
          <text class="link" @tap.stop="onDeleteRule(r)">删除</text>
        </view>
        <view v-if="!investRules.length" class="muted tip">未创建投资提醒。预设基于策略纪律（定投节奏/缴满抵税），在 star 小程序待办中心统一提醒。</view>
      </view>
    </view>

    <!-- 连接与运维 -->
    <view class="group">
      <view class="cell" hover-class="cell-hover" @tap="toggle('server')">
        <view class="cell-t">服务器配置</view>
        <view class="cell-tag">{{ mode === 'gateway' ? 'star 网关' : '本机直连' }}</view>
        <view class="cell-arrow" :class="{ up: opened === 'server' }">›</view>
      </view>
      <view v-if="opened === 'server'" class="panel">
        <view class="mode-row">
          <view class="mode-item" :class="{ on: mode === 'gateway' }" @tap="switchMode('gateway')">
            <view class="mode-name">star 网关（推荐）</view>
            <view class="mode-desc muted">微信登录 · 统一鉴权</view>
          </view>
          <view class="mode-item" :class="{ on: mode === 'direct' }" @tap="switchMode('direct')">
            <view class="mode-name">本机直连</view>
            <view class="mode-desc muted">LAN + 令牌 · 无 star</view>
          </view>
        </view>
        <view class="form-row">
          <text class="form-label">{{ mode === 'gateway' ? '网关地址' : '服务地址' }}</text>
          <input v-model="serverInput" class="form-input" :placeholder="mode === 'gateway' ? GATEWAY_HINT : DIRECT_HINT" />
        </view>
        <view v-if="mode === 'direct'" class="form-row">
          <text class="form-label">令牌</text>
          <input v-model="tokenInput" class="form-input" placeholder="invest serve --lan 打印" />
        </view>
        <view v-if="mode === 'gateway'" class="login-row">
          <text class="relogin" @tap="onRelogin">重新登录</text>
        </view>
        <button class="primary-btn block" :disabled="testing" @tap="onSaveAndTest">
          {{ testing ? '测试中' : '保存并测试连接' }}
        </button>
        <view class="muted tip">
          手机需与电脑同一 Wi-Fi；开发者工具中需开启「不校验合法域名」。
        </view>
      </view>

      <view class="cell" hover-class="cell-hover" @tap="toggle('glm')">
        <view class="cell-t">AI 能力（GLM Key）</view>
        <view class="cell-tag">{{ glmConfigured ? '已配置' : '未配置' }}</view>
        <view class="cell-arrow" :class="{ up: opened === 'glm' }">›</view>
      </view>
      <view v-if="opened === 'glm'" class="panel">
        <view class="form-row">
          <text class="form-label">智谱 Key</text>
          <input v-model="glmKeyInput" class="form-input" password placeholder="用于截图识别结构化，留空清除" />
        </view>
        <button class="primary-btn block" @tap="onSaveGlmKey">保存（即时生效）</button>
        <view class="muted tip">Key 仅保存在你自己的 invest 服务上，用于把 OCR 文本结构化为流水草稿。</view>
      </view>

      <view class="cell" hover-class="cell-hover" @tap="toggle('pull')">
        <view class="cell-t">手动拉数</view>
        <view class="cell-tag">行情/净值/估值</view>
        <view class="cell-arrow" :class="{ up: opened === 'pull' }">›</view>
      </view>
      <view v-if="opened === 'pull'" class="panel">
        <button class="primary-btn block" @tap="onStartPull">开始拉数</button>
        <view v-if="pull" class="pull-box">
          <view class="pull-status">
            状态：{{ pull.status }}
            <text v-if="pull.finished">（{{ pull.finished }}）</text>
          </view>
          <view v-for="(line, i) in pull.log.slice(-8)" :key="i" class="pull-log">{{ line }}</view>
        </view>
      </view>
    </view>

    <!-- 退出登录 -->
    <view class="group">
      <view class="cell" hover-class="cell-hover" @tap="onLogout">
        <view class="cell-t danger">退出登录</view>
        <view class="cell-arrow">›</view>
      </view>
    </view>

    <view class="footer">
      <view class="f-slogan">纪律是收益的底层资产</view>
      <view class="f-ver about">invest · 个人投资管理（决策支持，非投资建议）。数据存放于本人私有服务，不向第三方分享。</view>
    </view>
  </view>
</template>

<style scoped>
.profile {
  display: flex;
  align-items: center;
  background: #fff;
  border: 1rpx solid #e5e6eb;
  border-radius: 12rpx;
  padding: 32rpx 28rpx;
  margin: 20rpx 24rpx 0;
}
.avatar {
  width: 104rpx;
  height: 104rpx;
  border-radius: 50%;
  background: #1652a8;
  color: #fff;
  font-size: 44rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.p-main {
  flex: 1;
  margin-left: 24rpx;
}
.p-name {
  font-size: 33rpx;
  font-weight: 700;
  color: #1d2129;
}
.p-sub {
  font-size: 23rpx;
  color: #86909c;
  margin-top: 8rpx;
}
.login-state {
  font-size: 24rpx;
  flex-shrink: 0;
}
.login-state.success {
  color: #2e9e5b;
}
.login-state.danger {
  color: #d54941;
}
.group {
  background: #fff;
  border: 1rpx solid #e5e6eb;
  border-radius: 12rpx;
  padding: 0 28rpx;
  margin: 20rpx 24rpx 0;
}
.cell {
  display: flex;
  align-items: center;
  padding: 28rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.cell:last-child {
  border-bottom: none;
}
.cell-hover {
  background: #fafbfc;
}
.cell-t {
  flex: 1;
  font-size: 28rpx;
  color: #1d2129;
}
.cell-t.danger {
  color: #d54941;
}
.cell-tag {
  font-size: 20rpx;
  color: #86909c;
  border: 1rpx solid #e5e6eb;
  border-radius: 6rpx;
  padding: 2rpx 12rpx;
  margin-right: 12rpx;
}
.cell-arrow {
  color: #c9cdd4;
  font-size: 32rpx;
  transition: transform 0.15s;
}
.cell-arrow.up {
  transform: rotate(90deg);
}
.panel {
  padding: 8rpx 0 24rpx;
  border-bottom: 1rpx solid #f0f1f3;
}
.mode-row {
  display: flex;
  gap: 16rpx;
  margin-bottom: 8rpx;
}
.mode-item {
  flex: 1;
  border: 1rpx solid #e5e6eb;
  border-radius: 10rpx;
  padding: 16rpx 20rpx;
}
.mode-item.on {
  border-color: #1652a8;
  background: #eef3fb;
}
.mode-name {
  font-size: 26rpx;
  font-weight: 500;
}
.mode-desc {
  font-size: 22rpx;
  margin-top: 4rpx;
}
.form-row {
  display: flex;
  align-items: center;
  border-bottom: 1rpx solid #f0f1f3;
  padding: 20rpx 0;
}
.login-row {
  display: flex;
  justify-content: flex-end;
  border-bottom: 1rpx solid #f0f1f3;
  padding: 16rpx 0;
}
.relogin {
  color: #1652a8;
  font-size: 24rpx;
}
.form-label {
  width: 120rpx;
  font-size: 26rpx;
  color: #4e5969;
  flex-shrink: 0;
}
.form-input {
  flex: 1;
  font-size: 28rpx;
  text-align: right;
}
.form-value {
  font-size: 28rpx;
}
.primary-btn {
  background: #1652a8;
  color: #ffffff;
  border-radius: 10rpx;
  font-size: 26rpx;
  line-height: 2.4;
}
.primary-btn.block {
  width: 100%;
  margin-top: 24rpx;
}
.tip {
  font-size: 22rpx;
  margin-top: 16rpx;
  line-height: 1.6;
}
.pull-box {
  margin-top: 20rpx;
  border-top: 1rpx solid #f0f1f3;
  padding-top: 16rpx;
}
.pull-status {
  font-size: 26rpx;
  margin-bottom: 8rpx;
}
.pull-log {
  font-size: 22rpx;
  color: #86909c;
  line-height: 1.7;
}
.preset-row {
  display: flex;
  gap: 16rpx;
  margin-top: 16rpx;
}
.mini-btn {
  flex: 1;
  background: #ffffff;
  border: 1rpx solid #d0d3d9;
  border-radius: 10rpx;
  color: #1652a8;
  font-size: 24rpx;
  line-height: 2.2;
  padding: 0;
  margin: 0;
}
.rule-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}
.rule-row:last-of-type {
  border-bottom: none;
}
.rule-title {
  font-size: 26rpx;
}
.rule-sub {
  font-size: 22rpx;
  margin-top: 4rpx;
}
.link {
  color: #d54941;
  font-size: 24rpx;
  flex-shrink: 0;
  margin-left: 16rpx;
}
.footer {
  text-align: center;
  padding: 32rpx 48rpx 60rpx;
}
.f-slogan {
  font-size: 24rpx;
  color: #86909c;
}
.f-ver {
  font-size: 21rpx;
  color: #c9cdd4;
  margin-top: 10rpx;
  line-height: 1.6;
}
</style>
