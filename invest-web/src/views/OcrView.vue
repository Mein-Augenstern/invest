<!--
  截图识别（对齐小程序 ocr；S10 AC-6 服务端能力降级样板）：
  拖拽 / 选择截图 → POST /ocr（本地 Vision OCR + GLM 结构化）→ OCR 原文 + 可编辑流水草稿，逐条核对后入账。
  后端在 Linux（无 macOS Vision）时返回 422：展示后端文案 +「服务端不支持 OCR」说明 + 重试，不白屏、不抛未捕获异常。
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadFile, type UploadInstance } from 'element-plus'
import { Loading, UploadFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { ApiError, errMsg } from '@/api/client'
import { addTrade, getTrades, ocrTrades } from '@/api/invest'
import { ACTION_LABELS, type InstrumentBrief, type OcrDraft, type OcrResult } from '@/types'

const router = useRouter()

const ACTIONS = Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label }))

/** 草稿行：数值按字符串编辑（OCR 可能带千分位），保存时再解析 */
interface DraftRow {
  key: number
  date: string
  action: string
  instrument_id: string
  quantity: string
  price: string
  fee: string
  note: string
  saving: boolean
  saved: boolean
}

type Phase = 'idle' | 'loading' | 'done' | 'error'

const phase = ref<Phase>('idle')
const result = ref<OcrResult | null>(null)
const drafts = ref<DraftRow[]>([])
const errorText = ref('')
/** 422：服务端 OCR 不可用（Linux 无 macOS Vision）——预期降级，附说明与手工录入入口 */
const unsupported = ref(false)
const ocrOpen = ref<string[]>([])

const busy = computed(() => phase.value === 'loading')
const savedCount = computed(() => drafts.value.filter((d) => d.saved).length)
const lineCount = computed(() => (result.value?.text ? result.value.text.split('\n').length : 0))

/* ---------- 标的下拉：拿到草稿后按需拉一次（不做前置探活） ---------- */

const instruments = ref<InstrumentBrief[]>([])
let instrumentsLoaded = false

async function ensureInstruments() {
  if (instrumentsLoaded) return
  try {
    instruments.value = (await getTrades(undefined, 1)).instruments
    instrumentsLoaded = true
  } catch {
    /* 选项缺失不阻断：下拉仍可直接输入标的 id，保存时由后端校验 */
  }
}

/* ---------- 上传 → 识别 ---------- */

const uploadRef = ref<UploadInstance>()
let lastFile: File | null = null
let seq = 0

/** 与后端 _read_upload_image 同口径预校验（png/jpg ≤5MB）：通过后服务端 422 基本只剩 OCR 本身不可用 */
function imageError(file: File): string {
  if (!/\.(png|jpe?g)$/i.test(file.name)) return '仅支持 png/jpg 图片'
  if (!file.size) return '空文件'
  if (file.size > 5 * 1024 * 1024) return '图片超过 5MB'
  return ''
}

const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v).trim())

/** OCR 日期可能是 2024/3/5、2024.03.05：归一为 YYYY-MM-DD；认不出原样保留交后端校验 */
function normDate(s: string): string {
  const m = /^(\d{4})\D(\d{1,2})\D(\d{1,2})$/.exec(s)
  return m ? `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}` : s
}

function toRow(d: OcrDraft): DraftRow {
  return {
    key: ++seq,
    date: normDate(str(d.date)),
    action: str(d.action),
    instrument_id: str(d.instrument_id),
    quantity: str(d.quantity),
    price: str(d.price),
    fee: str(d.fee),
    note: str(d.note),
    saving: false,
    saved: false,
  }
}

function onPick(uploadFile: UploadFile) {
  const file = uploadFile.raw
  uploadRef.value?.clearFiles() // 手动模式下组件内部会累积文件列表，每次取完即清
  if (!file) return
  const bad = imageError(file)
  if (bad) {
    ElMessage.warning(bad)
    return
  }
  run(file)
}

async function run(file: File) {
  lastFile = file
  phase.value = 'loading'
  result.value = null
  drafts.value = []
  errorText.value = ''
  unsupported.value = false
  try {
    const res = await ocrTrades(file)
    result.value = res
    drafts.value = (res.trades ?? []).map(toRow)
    ocrOpen.value = drafts.value.length ? [] : ['text'] // 无草稿时默认展开原文，便于对照手工录入
    phase.value = 'done'
    if (drafts.value.length) ensureInstruments()
  } catch (e) {
    errorText.value = errMsg(e)
    unsupported.value = e instanceof ApiError && e.status === 422
    phase.value = 'error'
  }
}

function retry() {
  if (lastFile) run(lastFile)
}

function goManual() {
  router.push({ name: 'trades', query: { add: '1' } })
}

/* ---------- 逐条入账 ---------- */

/** 宽松解析数字：去千分位与空白；空串 / 非数字返回 null */
function toNum(s: string): number | null {
  const t = s.replace(/[,，\s]/g, '')
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

function warn(msg: string): void {
  ElMessage.warning(msg)
}

async function saveRow(row: DraftRow) {
  const isContribute = row.action === 'contribute' // 缴存：份额即金额，价格恒为 1（后端约定）
  const quantity = toNum(row.quantity)
  const price = isContribute ? 1 : toNum(row.price)
  const fee = row.fee.trim() ? toNum(row.fee) : 0
  if (!row.date) return warn('请填写日期')
  if (!row.action) return warn('请选择动作')
  if (!row.instrument_id) return warn('请选择标的')
  if (quantity === null || quantity === 0) return warn(isContribute ? '缴存金额需为非零数字' : '份额需为非零数字')
  if (price === null || price < 0) return warn('价格需为非负数字')
  if (fee === null || fee < 0) return warn('费用需为非负数字')
  row.saving = true
  try {
    await addTrade({
      date: row.date,
      action: row.action,
      instrument_id: row.instrument_id,
      quantity,
      price,
      fee,
      note: row.note.trim(),
    })
    row.saved = true
    ElMessage.success('已入账')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    row.saving = false
  }
}

function rowClass({ row }: { row: DraftRow }): string {
  return row.saved ? 'row-saved' : ''
}
</script>

<template>
  <PageHeader title="截图识别" desc="券商截图 → OCR → 结构化草稿" />

  <el-alert
    type="warning"
    show-icon
    :closable="false"
    class="ocr-alert"
    title="OCR 依赖 macOS Vision；当前服务器为 Linux 时接口会返回不支持，此页面仅在与 Mac 本机后端联调时可用"
  />

  <div class="panel">
    <el-upload
      ref="uploadRef"
      drag
      accept=".png,.jpg,.jpeg"
      :auto-upload="false"
      :show-file-list="false"
      :disabled="busy"
      :on-change="onPick"
    >
      <el-icon v-if="busy" class="upload-icon is-loading"><Loading /></el-icon>
      <el-icon v-else class="upload-icon"><UploadFilled /></el-icon>
      <div class="el-upload__text">
        <template v-if="busy">识别中…（OCR + AI 整理，最长约 1 分钟）</template>
        <template v-else>将截图拖到此处，或 <em>点击选择</em></template>
      </div>
      <template #tip>
        <div class="upload-tip muted">
          支持券商 / 基金 / 银行 App 的交易确认或持仓截图（png / jpg，≤ 5MB）；本地 OCR 识别 + AI 整理成流水草稿，逐条核对后入账。
        </div>
      </template>
    </el-upload>
  </div>

  <div class="panel panel-gap">
    <!-- 未上传：引导 -->
    <el-empty
      v-if="phase === 'idle'"
      :image-size="96"
      description="尚未上传截图。识别后这里会显示 OCR 原文与可编辑的流水草稿，逐条核对后保存入账"
    />

    <!-- 识别中 -->
    <el-skeleton v-else-if="phase === 'loading'" :rows="5" animated />

    <!-- 失败（含 422 服务端不支持）：后端文案 + 说明 + 重试 -->
    <el-result v-else-if="phase === 'error'" icon="error" title="识别失败">
      <template #sub-title>
        <p class="err-msg">{{ errorText }}</p>
        <p v-if="unsupported" class="err-hint muted">
          服务端不支持 OCR：截图识别依赖 macOS Vision 本地识别，后端运行在 Linux 服务器时返回此错误属预期降级。
          可连接 Mac 本机后端后重试，或到「流水」页手工记一笔。
        </p>
      </template>
      <template #extra>
        <el-button type="primary" @click="retry">重试</el-button>
        <el-button v-if="unsupported" @click="goManual">去手工记一笔</el-button>
      </template>
    </el-result>

    <!-- 成功：原文 + 草稿 -->
    <template v-else-if="result">
      <el-collapse v-model="ocrOpen" class="ocr-collapse">
        <el-collapse-item name="text">
          <template #title>
            OCR 原文<span class="muted collapse-sub">（{{ lineCount }} 行，核对用）</span>
          </template>
          <pre class="ocr-text">{{ result.text || '（未识别出文字）' }}</pre>
        </el-collapse-item>
      </el-collapse>

      <div class="panel-title">
        <span class="draft-title">
          流水草稿
          <el-tag v-if="result.ai_parsed" type="success" size="small" effect="plain">AI 已结构化</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">仅 OCR 原文</el-tag>
        </span>
        <span v-if="drafts.length" class="muted draft-count">共 {{ drafts.length }} 条 · 已入账 {{ savedCount }} 条</span>
      </div>

      <el-table v-if="drafts.length" :data="drafts" row-key="key" :row-class-name="rowClass" class="draft-table">
        <el-table-column label="日期" width="150">
          <template #default="{ row }">
            <el-date-picker
              v-model="row.date"
              type="date"
              value-format="YYYY-MM-DD"
              size="small"
              :clearable="false"
              :disabled="row.saved"
              placeholder="日期"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="动作" width="130">
          <template #default="{ row }">
            <el-select v-model="row.action" size="small" placeholder="动作" :disabled="row.saved">
              <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="标的" min-width="200">
          <template #default="{ row }">
            <el-select
              v-model="row.instrument_id"
              size="small"
              filterable
              allow-create
              default-first-option
              placeholder="选择或输入标的 id"
              :disabled="row.saved"
            >
              <el-option v-for="i in instruments" :key="i.id" :label="i.name" :value="i.id">
                <span>{{ i.name }}</span>
                <span class="opt-id muted">{{ i.id }}</span>
              </el-option>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="份额" width="120">
          <template #default="{ row }">
            <el-input v-model="row.quantity" size="small" class="num-input" :disabled="row.saved" />
          </template>
        </el-table-column>
        <el-table-column label="价格" width="110">
          <template #default="{ row }">
            <el-input
              v-model="row.price"
              size="small"
              class="num-input"
              :placeholder="row.action === 'contribute' ? '固定 1' : ''"
              :disabled="row.saved || row.action === 'contribute'"
            />
          </template>
        </el-table-column>
        <el-table-column label="费用" width="90">
          <template #default="{ row }">
            <el-input v-model="row.fee" size="small" class="num-input" placeholder="0" :disabled="row.saved" />
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.note" size="small" maxlength="100" :disabled="row.saved" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.saved ? 'success' : 'primary'"
              :plain="row.saved"
              :loading="row.saving"
              :disabled="row.saved"
              @click="saveRow(row as DraftRow)"
            >
              {{ row.saved ? '已保存' : '保存此条' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else :image-size="80" description="AI 结构化未识别出流水记录">
        <p class="muted empty-sub">
          {{ result.trades === null ? '未配置 GLM Key 或 AI 解析失败，仅返回 OCR 原文' : 'AI 已解析，但截图中没有可识别的交易行' }}；可对照上方原文手工录入。
        </p>
        <el-button @click="goManual">去手工记一笔</el-button>
      </el-empty>
    </template>
  </div>
</template>

<style scoped>
.ocr-alert {
  margin-bottom: 16px;
}
.upload-icon {
  font-size: 48px;
  color: var(--iv-text-3);
  margin-bottom: 8px;
}
.upload-tip {
  font-size: 12px;
  line-height: 1.6;
  margin-top: 8px;
}
.err-msg {
  margin: 0 0 6px;
  color: var(--iv-text);
  word-break: break-all;
}
.err-hint {
  margin: 0 auto;
  max-width: 560px;
  font-size: 13px;
  line-height: 1.7;
}
.ocr-collapse {
  margin-bottom: 20px;
}
.collapse-sub {
  font-weight: 400;
  font-size: 12px;
}
.ocr-text {
  margin: 0;
  max-height: 320px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
  color: var(--iv-text-2);
  background: #f7f8fa;
  border-radius: 6px;
  padding: 10px 12px;
}
.draft-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.draft-count {
  font-size: 12px;
  font-weight: 400;
}
.opt-id {
  float: right;
  margin-left: 12px;
  font-size: 12px;
}
.empty-sub {
  margin: 0 0 12px;
  font-size: 13px;
}
.draft-table :deep(.num-input .el-input__inner) {
  text-align: right;
}
.draft-table :deep(.row-saved td.el-table__cell) {
  background: #f7f8fa;
}
</style>
