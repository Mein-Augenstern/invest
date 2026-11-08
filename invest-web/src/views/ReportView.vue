<!--
  周报（对齐小程序 report）：生成新周报（可附 GLM 解读；后台任务，2.5s 轮询 /reports/status，409 时接管轮询）· 最新周报渲染。
  渲染只输出文本节点（禁 v-html）：标题 / 段落 / 列表 / 引用（el-alert）/ 表格（el-table，单元格全部字符串化）。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DocumentAdd } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { ApiError, errMsg } from '@/api/client'
import { generateReport, getLatestReport, getReportStatus } from '@/api/invest'
import type { ReportJobStatus } from '@/types'
import { parseMarkdown } from '@/utils/markdown-lite'

interface Report {
  file: string
  markdown: string
}

const report = ref<Report | null>(null)
const loaded = ref(false)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getLatestReport()
    report.value = 'file' in res ? res : null
    loaded.value = true
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/** 生成时间取自文件名：任务版 weekly-YYYYMMDD-HHMMSS.md / CLI 版 weekly-YYYYMMDD.md（接口不单独返回时间） */
function timeOfFile(file: string): string {
  const m = /(\d{4})(\d{2})(\d{2})(?:-(\d{2})(\d{2})(\d{2}))?/.exec(file)
  if (!m) return ''
  const day = `${m[1]}-${m[2]}-${m[3]}`
  return m[4] ? `${day} ${m[4]}:${m[5]}:${m[6]}` : day
}

const desc = computed(() => {
  if (!report.value) return loaded.value ? '持仓快照 · 基准估值 · 策略信号，可附 GLM 解读' : ''
  const t = timeOfFile(report.value.file)
  return t ? `${report.value.file} · 生成于 ${t}` : report.value.file
})

/* ---------- markdown-lite → 视图块（连续 li 合并为一个 ul；表格转 el-table 列/行） ---------- */

type TextKind = 'h1' | 'h2' | 'h3' | 'p' | 'quote'

interface TableColumn {
  prop: string
  label: string
  minWidth: number
  numeric: boolean
}

type ViewBlock =
  | { kind: TextKind; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'table'; columns: TableColumn[]; data: Record<string, string>[] }

/** 数值单元格（含千分位 / 百分号 / 「价格(日期)」）：整列为数值时右对齐 */
const NUM_CELL = /^[+-]?\d[\d,]*(\.\d+)?%?(\(.*\))?$/
const BLANK_CELL = /^(|—|-|n\/a)$/

/** 粗估文本宽度（CJK 约 14px、其余约 8px）定列最小宽：宽表横向滚动，不挤压换行 */
function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += /[\u2E80-\uFFEF]/.test(ch) ? 14 : 8
  return w
}

function toTable(rows: string[][]): ViewBlock {
  const [head, ...body] = rows
  const width = Math.max(head.length, ...body.map((r) => r.length))
  const columns: TableColumn[] = Array.from({ length: width }, (_, i) => {
    const label = String(head[i] ?? '')
    const cells = body.map((r) => String(r[i] ?? ''))
    const numeric = cells.some((c) => NUM_CELL.test(c)) && cells.every((c) => NUM_CELL.test(c) || BLANK_CELL.test(c))
    const minWidth = Math.min(320, Math.max(72, ...[label, ...cells].map(textWidth)) + 28)
    // prop 用列序号而非表头文字：表头可能重复，且含「.」「[」时会被当作取值路径
    return { prop: `c${i}`, label, minWidth, numeric }
  })
  const data = body.map((r) => Object.fromEntries(columns.map((c, i) => [c.prop, String(r[i] ?? '')])))
  return { kind: 'table', columns, data }
}

const blocks = computed<ViewBlock[]>(() => {
  const out: ViewBlock[] = []
  if (!report.value) return out
  for (const b of parseMarkdown(report.value.markdown)) {
    if (b.kind === 'li') {
      const last = out[out.length - 1]
      if (last && last.kind === 'ul') last.items.push(b.text ?? '')
      else out.push({ kind: 'ul', items: [b.text ?? ''] })
    } else if (b.kind === 'table') {
      if (b.rows?.length) out.push(toTable(b.rows))
    } else {
      out.push({ kind: b.kind, text: b.text ?? '' })
    }
  }
  return out
})

/* ---------- 生成周报：POST /reports/generate → 轮询 /reports/status ---------- */

const ai = ref(false)
const job = ref<ReportJobStatus | null>(null)
const generating = computed(() => job.value?.status === 'running')
const logTail = computed(() => (job.value?.log ?? []).slice(-3))

let timer: ReturnType<typeof setInterval> | null = null
let inFlight = false

function stopPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

function startPolling() {
  stopPolling()
  timer = setInterval(poll, 2500)
}

async function poll() {
  if (inFlight) return
  inFlight = true
  try {
    const s = await getReportStatus()
    job.value = s
    if (s.status === 'done') {
      stopPolling()
      ElMessage.success(s.file ? `周报已生成：${s.file}` : '周报已生成')
      load()
    } else if (s.status === 'error') {
      stopPolling()
      ElMessage.error('周报生成失败，详见日志')
    } else if (s.status === 'idle') {
      // 服务重启会丢失内存任务句柄：不再空转轮询
      stopPolling()
    }
  } catch (e) {
    stopPolling()
    job.value = null
    ElMessage.error(errMsg(e))
  } finally {
    inFlight = false
  }
}

async function generate() {
  try {
    await generateReport(ai.value)
    ElMessage.info(ai.value ? '已开始生成（含 AI 解读，约需 1 分钟）' : '已开始生成')
  } catch (e) {
    // 409 = 已有周报生成任务在跑：不报错，直接接管轮询
    if (!(e instanceof ApiError && e.status === 409)) {
      ElMessage.error(errMsg(e))
      return
    }
  }
  job.value = { status: 'running', started: null, finished: null, file: '', log: [] }
  startPolling()
}

/** 进页时若已有任务在跑（其他端触发或离开后返回），直接接管轮询 */
async function syncJob() {
  try {
    const s = await getReportStatus()
    if (s.status === 'running') {
      job.value = s
      startPolling()
    }
  } catch {
    /* 状态探测失败不影响正文展示 */
  }
}

onMounted(() => {
  load()
  syncJob()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <PageHeader title="周报" :desc="desc">
    <template #actions>
      <el-tooltip content="附 GLM 解读，约需 1 分钟；服务端未配置 GLM Key 时自动降级为纯数据周报" placement="bottom">
        <el-switch v-model="ai" active-text="AI 解读" :disabled="generating" class="ai-switch" />
      </el-tooltip>
      <el-button type="primary" :icon="DocumentAdd" :loading="generating" @click="generate">生成周报</el-button>
    </template>
  </PageHeader>

  <el-alert v-if="job && job.status === 'running'" type="info" :closable="false" title="正在生成周报…" class="job">
    <span v-for="(l, i) in logTail" :key="i" class="job-log">{{ l }}</span>
  </el-alert>
  <el-alert v-else-if="job && job.status === 'error'" type="error" title="周报生成失败" class="job" @close="job = null">
    <span v-for="(l, i) in logTail" :key="i" class="job-log">{{ l }}</span>
  </el-alert>

  <StateBlock
    :loading="loading"
    :error="error"
    :empty="loaded && !report"
    :has-data="!!report"
    empty-text="还没有周报，点右上角生成"
    @retry="load"
  >
    <template #empty-action>
      <el-button type="primary" :loading="generating" @click="generate">生成周报</el-button>
    </template>

    <article class="panel md">
      <template v-for="(b, i) in blocks" :key="i">
        <h1 v-if="b.kind === 'h1'" class="md-h1">{{ b.text }}</h1>
        <h2 v-else-if="b.kind === 'h2'" class="md-h2">{{ b.text }}</h2>
        <h3 v-else-if="b.kind === 'h3'" class="md-h3">{{ b.text }}</h3>
        <ul v-else-if="b.kind === 'ul'" class="md-ul">
          <li v-for="(t, j) in b.items" :key="j">{{ t }}</li>
        </ul>
        <el-alert v-else-if="b.kind === 'quote'" type="info" :title="b.text" :closable="false" class="md-quote" />
        <div v-else-if="b.kind === 'table'" class="md-table">
          <el-table :data="b.data" size="small">
            <el-table-column
              v-for="c in b.columns"
              :key="c.prop"
              :prop="c.prop"
              :label="c.label"
              :min-width="c.minWidth"
              :align="c.numeric ? 'right' : 'left'"
            />
          </el-table>
        </div>
        <p v-else class="md-p">{{ b.text }}</p>
      </template>
    </article>
  </StateBlock>
</template>

<style scoped>
.ai-switch {
  align-self: center;
  margin-right: 8px;
}
.job {
  margin-bottom: 16px;
}
.job-log {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
  word-break: break-all;
}
.md {
  padding: 24px 28px;
  line-height: 1.8;
}
.md-h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 28px 0 12px;
}
.md-h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 24px 0 10px;
  padding-left: 10px;
  border-left: 3px solid var(--iv-primary);
  line-height: 1.4;
}
.md-h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 18px 0 8px;
}
.md > :first-child {
  margin-top: 0;
}
.md-p {
  margin: 8px 0;
  color: var(--iv-text);
}
.md-ul {
  margin: 8px 0;
  padding-left: 22px;
}
.md-quote {
  margin: 10px 0;
}
.md-table {
  margin: 10px 0 16px;
}
</style>
