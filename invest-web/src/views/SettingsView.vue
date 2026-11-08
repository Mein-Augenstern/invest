<!--
  设置（对齐小程序 settings「我的」）：访问与安全（star 会员登录态 / 退出登录）· GLM 智能（Key 状态与保存）·
  数据拉取（立即拉数 + 3s 轮询 + 日志）· 备份与数据健康（导出 zip / 文件行数与损坏行）· 与小程序的功能差异说明。
  各卡独立三态：任一接口失败只影响所在卡片，退出登录始终可用。
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Lock, Refresh, SwitchButton, User } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { ApiError, errMsg } from '@/api/client'
import {
  downloadBackup,
  getBackupInfo,
  getDataHealth,
  getGlmKeyStatus,
  getPullStatus,
  saveGlmKey,
  startPull,
} from '@/api/invest'
import { changePassword, getProfile, updateProfile, type MemberProfile } from '@/api/member'
import type { BackupInfo, DataHealth, PullStatus } from '@/types'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

/* ---------- 个人信息 ---------- */

const profile = ref<MemberProfile | null>(null)
const profileLoading = ref(true)
const profileError = ref('')
const nicknameEdit = ref('')
const nicknameSaving = ref(false)

async function loadProfile() {
  profileLoading.value = true
  profileError.value = ''
  try {
    profile.value = await getProfile()
    nicknameEdit.value = profile.value?.nickname || ''
  } catch (e) {
    profileError.value = errMsg(e)
  } finally {
    profileLoading.value = false
  }
}

async function saveNickname() {
  const v = nicknameEdit.value.trim()
  if (!v || nicknameSaving.value) return
  nicknameSaving.value = true
  try {
    await updateProfile({ nickname: v })
    ElMessage.success('昵称已更新')
    if (profile.value) profile.value.nickname = v
    if (auth.member) auth.member.nickname = v
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    nicknameSaving.value = false
  }
}

/* ---------- 修改密码 ---------- */

const pwdForm = reactive({ old: '', fresh: '', confirm: '' })
const pwdSaving = ref(false)

async function submitPassword() {
  if (pwdSaving.value) return
  if (!pwdForm.old || !pwdForm.fresh) return ElMessage.warning('请填写旧密码与新密码')
  if (pwdForm.fresh !== pwdForm.confirm) return ElMessage.warning('两次新密码不一致')
  if (pwdForm.fresh.length < 6) return ElMessage.warning('新密码至少 6 位')
  pwdSaving.value = true
  try {
    await changePassword(pwdForm.old, pwdForm.fresh)
    ElMessage.success('密码已修改，下次登录使用新密码')
    pwdForm.old = pwdForm.fresh = pwdForm.confirm = ''
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    pwdSaving.value = false
  }
}

/* ---------- 退出登录 ---------- */

function logout() {
  auth.logout()
  router.replace({ name: 'login' })
}

/* ---------- GLM 智能：只回是否已配置，不回显 Key ---------- */

const glmConfigured = ref<boolean | null>(null)
const glmLoading = ref(true)
const glmError = ref('')
const glmKey = ref('')
const glmSaving = ref(false)

async function loadGlm() {
  glmLoading.value = true
  glmError.value = ''
  try {
    glmConfigured.value = (await getGlmKeyStatus()).configured
  } catch (e) {
    glmError.value = errMsg(e)
  } finally {
    glmLoading.value = false
  }
}

/** 后端约定：key 为空串即清除 */
async function saveGlm(clear = false) {
  const key = clear ? '' : glmKey.value.trim()
  if (!clear && !key) return
  glmSaving.value = true
  try {
    const res = await saveGlmKey(key)
    glmConfigured.value = res.configured
    glmKey.value = ''
    ElMessage.success(res.configured ? 'GLM Key 已保存，即时生效' : 'GLM Key 已清除')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    glmSaving.value = false
  }
}

/* ---------- 数据拉取：POST /pull → 轮询 /pull/status（3s） ---------- */

const PULL_LABELS: Record<PullStatus['status'], string> = { idle: '空闲', running: '进行中', done: '已完成', error: '失败' }
const PULL_TAGS = { idle: 'info', running: 'primary', done: 'success', error: 'danger' } as const

const pull = ref<PullStatus | null>(null)
const pullLoading = ref(true)
const pullError = ref('')
const pulling = computed(() => pull.value?.status === 'running')
const logEl = ref<HTMLDivElement | null>(null)

let pullTimer: ReturnType<typeof setInterval> | null = null
let pullInFlight = false

function stopPullPolling() {
  if (pullTimer) clearInterval(pullTimer)
  pullTimer = null
}

function startPullPolling() {
  stopPullPolling()
  pullTimer = setInterval(pollPull, 3000)
}

async function pollPull() {
  if (pullInFlight) return
  pullInFlight = true
  try {
    const s = await getPullStatus()
    pull.value = s
    if (s.status === 'done') {
      stopPullPolling()
      ElMessage.success('拉数完成')
      loadBackup() // invest.db 已更新：刷新数据健康
    } else if (s.status === 'error') {
      stopPullPolling()
      ElMessage.error('拉数失败，详见日志')
    } else if (s.status === 'idle') {
      // 服务重启会丢失内存任务句柄：不再空转轮询
      stopPullPolling()
    }
  } catch (e) {
    stopPullPolling()
    ElMessage.error(errMsg(e))
  } finally {
    pullInFlight = false
  }
}

async function loadPull() {
  pullLoading.value = true
  pullError.value = ''
  try {
    pull.value = await getPullStatus()
    // 进页时已有任务在跑（定时任务或其他端触发）：直接接管轮询
    if (pull.value.status === 'running') startPullPolling()
  } catch (e) {
    pullError.value = errMsg(e)
  } finally {
    pullLoading.value = false
  }
}

async function runPull() {
  try {
    await startPull()
    ElMessage.success('拉数已开始')
  } catch (e) {
    // 409 = 已有拉数任务在跑：不报错，直接接管轮询
    if (!(e instanceof ApiError && e.status === 409)) {
      ElMessage.error(errMsg(e))
      return
    }
  }
  pull.value = { status: 'running', started: null, finished: null, log: [] }
  startPullPolling()
  pollPull() // 立即取一次，日志不必等首个轮询周期
}

/** 新日志到达时滚到底部 */
watch(
  () => pull.value?.log,
  async () => {
    await nextTick()
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  },
)

/* ---------- 备份与数据健康 ---------- */

const backup = ref<BackupInfo | null>(null)
const health = ref<DataHealth | null>(null)
const backupLoading = ref(true)
const backupError = ref('')
const exporting = ref(false)

async function loadBackup() {
  backupLoading.value = true
  backupError.value = ''
  try {
    const [info, h] = await Promise.all([getBackupInfo(), getDataHealth()])
    backup.value = info
    health.value = h
  } catch (e) {
    backupError.value = errMsg(e)
  } finally {
    backupLoading.value = false
  }
}

async function exportBackup() {
  exporting.value = true
  try {
    await downloadBackup()
    ElMessage.success('备份已导出，含全部流水与持仓配置，请妥善保管')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    exporting.value = false
  }
}

type HealthFile = DataHealth['files'][string]
interface HealthRow extends HealthFile {
  key: string
}

const healthRows = computed<HealthRow[]>(() =>
  Object.entries(health.value?.files ?? {}).map(([key, f]) => ({ key, ...f })),
)

function fmtBytes(n: number | undefined): string {
  if (n === undefined) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** ISO 时间（2026-11-08T17:25:01.123456）→ 2026-11-08 17:25:01 */
function fmtIso(s: string | null | undefined): string {
  return s ? s.replace('T', ' ').slice(0, 19) : '—'
}

onMounted(() => {
  loadGlm()
  loadPull()
  loadBackup()
  loadProfile()
})
onBeforeUnmount(stopPullPolling)
</script>

<template>
  <PageHeader title="设置" desc="访问凭证 · AI 能力 · 数据拉取 · 备份与数据健康" />

  <div class="grid grid-2">
    <!-- 卡1 个人信息 -->
    <section class="panel">
      <div class="panel-title">
        个人信息
        <el-tag :type="auth.authed ? 'success' : 'info'" size="small">{{ auth.authed ? '已登录' : '未登录' }}</el-tag>
      </div>
      <StateBlock :loading="profileLoading" :error="profileError" :has-data="!!profile" @retry="loadProfile">
        <template v-if="profile">
          <div class="profile-row">
            <el-avatar :size="48" :icon="User" class="profile-avatar" />
            <div class="profile-info">
              <div class="profile-name">{{ profile.nickname || profile.username || '—' }}</div>
              <div class="muted">member #{{ profile.id }}<span v-if="profile.createdAt"> · {{ profile.createdAt.slice(0, 10) }} 加入</span></div>
            </div>
          </div>
          <el-form label-width="60px" class="profile-form">
            <el-form-item label="昵称">
              <div class="nick-row">
                <el-input v-model="nicknameEdit" placeholder="展示昵称" maxlength="20" />
                <el-button type="primary" size="small" :loading="nicknameSaving" :disabled="!nicknameEdit.trim() || nicknameEdit.trim() === profile.nickname" @click="saveNickname">保存</el-button>
              </div>
            </el-form-item>
          </el-form>
        </template>
      </StateBlock>
      <el-popconfirm title="退出后需重新登录才能访问，确定退出？" confirm-button-text="退出" :width="260" @confirm="logout">
        <template #reference>
          <el-button type="danger" plain :icon="SwitchButton">退出登录</el-button>
        </template>
      </el-popconfirm>
    </section>

    <!-- 卡1.5 修改密码 -->
    <section class="panel">
      <div class="panel-title">
        修改密码
        <el-icon class="muted"><Lock /></el-icon>
      </div>
      <el-form label-width="72px">
        <el-form-item label="旧密码">
          <el-input v-model="pwdForm.old" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.fresh" type="password" show-password autocomplete="new-password" placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password autocomplete="new-password" @keyup.enter="submitPassword" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="pwdSaving" @click="submitPassword" style="width: 100%">修改密码</el-button>
      <p class="muted pwd-hint">修改后当前登录不受影响，下次登录使用新密码</p>
    </section>

    <!-- 卡2 GLM 智能 -->
    <section class="panel">
      <div class="panel-title">
        GLM 智能
        <el-tag v-if="glmConfigured !== null" :type="glmConfigured ? 'success' : 'info'" size="small">
          {{ glmConfigured ? '已配置' : '未配置' }}
        </el-tag>
      </div>
      <StateBlock :loading="glmLoading" :error="glmError" :has-data="glmConfigured !== null" @retry="loadGlm">
        <p class="desc">
          智谱 GLM API Key 用于周报 AI 解读与截图识别结构化。Key 只保存在你自己的 invest 服务上（config/glm.local.env），保存即时生效；接口只返回是否已配置，不回显 Key。
        </p>
        <div class="glm-row">
          <el-input
            v-model="glmKey"
            type="password"
            show-password
            clearable
            autocomplete="new-password"
            :placeholder="glmConfigured ? '输入新 Key 以替换当前配置' : '粘贴智谱 API Key'"
            @keyup.enter="saveGlm()"
          />
          <el-button type="primary" :loading="glmSaving" :disabled="!glmKey.trim()" @click="saveGlm()">保存</el-button>
          <el-popconfirm
            v-if="glmConfigured"
            title="清除后周报 AI 解读与截图结构化将降级，确定清除？"
            confirm-button-text="清除"
            :width="260"
            @confirm="saveGlm(true)"
          >
            <template #reference>
              <el-button :disabled="glmSaving">清除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </StateBlock>
    </section>
  </div>

  <!-- 卡3 数据拉取 -->
  <section class="panel panel-gap">
    <div class="panel-title">
      数据拉取
      <el-tag v-if="pull" :type="PULL_TAGS[pull.status]" size="small">{{ PULL_LABELS[pull.status] }}</el-tag>
    </div>
    <StateBlock :loading="pullLoading" :error="pullError" :has-data="!!pull" @retry="loadPull">
      <template v-if="pull">
        <div class="pull-bar">
          <div>
            <p class="desc tight">拉取行情、基金净值与指数估值，完成后自动评估策略信号。分钟级后台任务，离开本页不会中断。</p>
            <div class="pull-meta muted">
              <span>上次开始：{{ pull.started || '—' }}</span>
              <span>上次完成：{{ pull.finished || (pulling ? '进行中' : '—') }}</span>
            </div>
          </div>
          <el-button type="primary" :icon="Refresh" :loading="pulling" @click="runPull">立即拉数</el-button>
        </div>
        <div ref="logEl" class="log">
          <div v-for="(l, i) in pull.log" :key="i">{{ l }}</div>
          <div v-if="!pull.log.length" class="muted">暂无日志</div>
        </div>
      </template>
    </StateBlock>
  </section>

  <!-- 卡4 备份与数据健康 -->
  <section class="panel panel-gap">
    <div class="panel-title">
      备份与数据健康
      <template v-if="health">
        <el-tag v-if="health.healthy" type="success" size="small">数据完好</el-tag>
        <el-tag v-else type="warning" size="small">发现损坏行</el-tag>
      </template>
    </div>
    <StateBlock :loading="backupLoading" :error="backupError" :has-data="!!backup && !!health" @retry="loadBackup">
      <div v-if="backup && health" class="backup">
        <div>
          <dl class="kv">
            <dt>流水条数</dt>
            <dd class="num">{{ backup.trades_count }}</dd>
            <dt>可导出</dt>
            <dd>
              <el-tag :type="backup.exportable ? 'success' : 'info'" size="small" effect="plain">
                {{ backup.exportable ? '可导出' : '暂无可导出数据' }}
              </el-tag>
            </dd>
            <dt>数据目录</dt>
            <dd class="mono">{{ backup.data_dir }}</dd>
            <dt>数据文件</dt>
            <dd class="files">
              <el-tag v-for="f in backup.files" :key="f" type="info" size="small" effect="plain">{{ f }}</el-tag>
              <span v-if="!backup.files.length" class="muted">无</span>
            </dd>
          </dl>
          <el-button type="primary" :icon="Download" :loading="exporting" :disabled="!backup.exportable" @click="exportBackup">
            导出备份 zip
          </el-button>
          <p class="hint muted">
            {{ backup.exportable ? '打包 trades.csv、invest.db 与本机配置（*.local.yaml）' : '暂无流水记录，记一笔后即可导出备份' }}
          </p>
        </div>
        <div>
          <el-table :data="healthRows" size="small" empty-text="未发现数据文件">
            <el-table-column prop="key" label="文件" min-width="110" show-overflow-tooltip />
            <el-table-column label="行数" align="right" width="80">
              <template #default="{ row }">{{ row.total_rows ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="损坏行" align="right" width="80">
              <template #default="{ row }">
                <span :class="{ danger: (row.corrupted_rows ?? 0) > 0 }">{{ row.corrupted_rows ?? '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="大小" align="right" width="90">
              <template #default="{ row }">{{ fmtBytes(row.size_bytes) }}</template>
            </el-table-column>
            <el-table-column label="最后修改" width="160">
              <template #default="{ row }">{{ fmtIso(row.last_modified) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </StateBlock>
  </section>

  <!-- 卡5 说明 -->
  <el-alert type="info" show-icon :closable="false" title="PC 端与小程序的功能差异" class="panel-gap">
    家庭提醒依赖 star 网关，PC 端暂不支持；截图识别依赖 macOS Vision，服务器为 Linux 时不可用。
  </el-alert>
</template>

<style scoped>
/* 全局 .panel + .panel 会给栅格内相邻卡片加上外边距，栅格内以 gap 为准 */
.grid > .panel {
  margin-top: 0;
}
.profile-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}
.profile-avatar {
  background: var(--iv-primary);
  flex-shrink: 0;
}
.profile-name {
  font-size: 18px;
  font-weight: 600;
}
.profile-info {
  min-width: 0;
}
.profile-form {
  margin-bottom: 16px;
}
.nick-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.pwd-hint {
  text-align: center;
  font-size: 12px;
  margin-top: 8px;
}
.desc {
  margin: 0 0 14px;
  color: var(--iv-text-2);
  font-size: 13px;
  line-height: 1.7;
}
.desc.tight {
  margin-bottom: 6px;
}
.tips {
  margin: 0 0 16px;
  padding-left: 18px;
  color: var(--iv-text-2);
  font-size: 13px;
  line-height: 1.8;
}
.glm-row {
  display: flex;
  gap: 8px;
}
.pull-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.pull-meta {
  display: flex;
  gap: 24px;
  font-size: 12px;
}
.log {
  height: 200px;
  overflow-y: auto;
  padding: 10px 12px;
  background: #f7f8fa;
  border: 1px solid var(--iv-border);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}
.backup {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: 24px;
}
@media (max-width: 1100px) {
  .backup {
    grid-template-columns: minmax(0, 1fr);
  }
}
.kv {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px 12px;
  margin: 0 0 16px;
  font-size: 13px;
  align-items: center;
}
.kv dt {
  color: var(--iv-text-3);
}
.kv dd {
  margin: 0;
}
.files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  word-break: break-all;
}
.hint {
  font-size: 12px;
  margin: 8px 0 0;
}
</style>
