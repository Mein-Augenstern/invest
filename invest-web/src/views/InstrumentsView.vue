<!--
  标的管理（对齐小程序 instruments）：标的表（db + yaml 合并视角，带持仓数量）· 新增 / 编辑共用弹窗 ·
  从截图识别（OCR + AI 反显表单，依赖 macOS Vision，Linux 部署 422 属预期降级）· 删除双保护（持仓 409 / yaml 种子 404）。
-->
<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from 'vue'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
  type UploadFile,
  type UploadInstance,
} from 'element-plus'
import { Picture, Plus } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { ApiError, errMsg } from '@/api/client'
import { deleteInstrument, getInstruments, parseInstrumentImage, saveInstrument } from '@/api/invest'
import type { InstrumentForm, InstrumentRow } from '@/types'
import { fmtQty } from '@/utils/format'

/** 品类：value 为后端 INSTRUMENT_TYPES，中文与小程序一致 */
const TYPES = [
  { value: 'open_end_fund', label: '场外基金' },
  { value: 'etf', label: 'ETF' },
  { value: 'stock', label: '股票' },
  { value: 'bond', label: '债券' },
  { value: 'wealth', label: '理财/固收' },
]
const typeLabel = (t: string) => TYPES.find((x) => x.value === t)?.label || t || '—'

/** 删除失败的语义映射（后端：409 = 仍有持仓流水；404 = 不在数据库，即 yaml 种子） */
const MSG_HELD = '仍有持仓不可删除'
const MSG_SEED = 'YAML 种子标的，请在配置文件中删除'

const rows = ref<InstrumentRow[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getInstruments()
    rows.value = res.instruments
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/* ---------- 新增 / 编辑（共用弹窗） ---------- */

type FormModel = Required<InstrumentForm>

const emptyForm = (): FormModel => ({ id: '', name: '', type: 'open_end_fund', code: '', benchmark_index: '', account: '' })

const dialog = ref(false)
const editing = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<FormModel>(emptyForm())

/** 截图识别原文：核对用；AI 未识别时默认展开供手动对照 */
const ocrText = ref('')
const ocrOpen = ref<string[]>([])

/** 与后端 POST /instruments 同口径 */
const ID_RE = /^[a-z0-9_]{2,32}$/

const rules: FormRules = {
  id: [
    { required: true, message: '请填写标识', trigger: 'blur' },
    {
      trigger: 'blur',
      validator: (_rule: unknown, value: string, callback: (e?: Error) => void) => {
        if (editing.value) return callback() // 编辑时标识锁定不复验
        if (!ID_RE.test(value)) return callback(new Error('标识需 2-32 位小写字母/数字/下划线'))
        // 后端按 id upsert：新增撞已有 id 会静默覆盖原标的，前端拦一道
        if (rows.value.some((r) => r.id === value)) return callback(new Error('标识已存在，请换一个或改用编辑'))
        callback()
      },
    },
  ],
  name: [{ required: true, whitespace: true, message: '请填写名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择类型', trigger: 'change' }],
}

function openDialog(row?: InstrumentRow) {
  editing.value = !!row
  Object.assign(
    form,
    row
      ? {
          id: row.id,
          name: row.name || '',
          type: row.type || 'open_end_fund',
          code: row.code || '',
          benchmark_index: row.benchmark_index || '',
          account: row.account || '',
        }
      : emptyForm(),
  )
  ocrText.value = ''
  ocrOpen.value = []
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await saveInstrument({
      id: form.id.trim(),
      name: form.name.trim(),
      type: form.type,
      code: form.code.trim(),
      benchmark_index: form.benchmark_index.trim(),
      account: form.account.trim(),
    })
    ElMessage.success(editing.value ? '已更新' : '已添加（拉数后生效）')
    dialog.value = false
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

/* ---------- 从截图识别：OCR + AI → 标的草稿反显到新增弹窗 ---------- */

const uploadRef = ref<UploadInstance>()
const parsing = ref(false)

/** 与后端 _read_upload_image 同口径预校验（png/jpg ≤5MB）：省一次往返，服务端 422 基本只剩 OCR 本身不可用 */
function imageError(file: File): string {
  if (!/\.(png|jpe?g)$/i.test(file.name)) return '仅支持 png/jpg 图片'
  if (!file.size) return '空文件'
  if (file.size > 5 * 1024 * 1024) return '图片超过 5MB'
  return ''
}

/** 只用非空识别值反显，空字段留给用户补；type 非法时保持默认（后端已把非法值清空） */
function applyDraft(draft: Partial<InstrumentForm>) {
  for (const k of ['id', 'name', 'code', 'benchmark_index', 'account'] as const) {
    const v = draft[k]
    if (v) form[k] = v
  }
  if (draft.type && TYPES.some((t) => t.value === draft.type)) form.type = draft.type
}

async function onShot(uploadFile: UploadFile) {
  const file = uploadFile.raw
  uploadRef.value?.clearFiles() // 手动模式下组件内部会累积文件列表，每次取完即清
  if (!file) return
  const bad = imageError(file)
  if (bad) {
    ElMessage.warning(bad)
    return
  }
  parsing.value = true
  try {
    const res = await parseInstrumentImage(file)
    openDialog()
    if (res.instrument) applyDraft(res.instrument)
    ocrText.value = res.text || ''
    if (res.ai_parsed && res.instrument) {
      ElMessage.success('已识别并填入表单，请核对后保存')
    } else {
      if (ocrText.value) ocrOpen.value = ['text']
      ElMessage.warning('OCR 完成，但未识别出标的（可能未配置 GLM Key），请对照原文手动填写')
    }
  } catch (e) {
    // 422 = 服务端 OCR 不可用（Linux 无 macOS Vision）等语义错误：展示后端文案，属预期降级
    const unsupported = e instanceof ApiError && e.status === 422
    ElMessage.error({
      message: unsupported ? `${errMsg(e)}（截图识别依赖 macOS Vision，服务端不支持 OCR 时请手动新增）` : errMsg(e),
      duration: 6000,
    })
  } finally {
    parsing.value = false
  }
}

/* ---------- 删除 ---------- */

async function remove(row: InstrumentRow) {
  // 与小程序一致先按列表字段本地判定（与服务端映射同一文案），免「确认后才告知不能删」；服务端 409/404 映射兜底竞态
  if (!row.from_db) {
    ElMessage.warning(MSG_SEED)
    return
  }
  if (row.held_qty) {
    ElMessage.warning(MSG_HELD)
    return
  }
  try {
    await ElMessageBox.confirm(`删除标的「${row.name}」（${row.id}）？删除后不可恢复。`, '删除标的', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return // 取消 / 关闭
  }
  try {
    await deleteInstrument(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) ElMessage.error(MSG_HELD)
    else if (e instanceof ApiError && e.status === 404) ElMessage.error(MSG_SEED)
    else ElMessage.error(errMsg(e))
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="标的管理" desc="新增/修改即时生效；新增后需到总览「立即拉数」抓取行情，理财/固收无需代码">
    <template #actions>
      <el-upload
        ref="uploadRef"
        :show-file-list="false"
        :auto-upload="false"
        accept=".png,.jpg,.jpeg"
        :disabled="parsing"
        :on-change="onShot"
      >
        <el-button :icon="Picture" :loading="parsing">{{ parsing ? '识别中…' : '从截图识别' }}</el-button>
      </el-upload>
      <el-button type="primary" :icon="Plus" @click="openDialog()">新增标的</el-button>
    </template>
  </PageHeader>

  <div class="panel">
    <StateBlock
      :loading="loading"
      :error="error"
      :empty="!rows.length"
      :has-data="!!rows.length"
      empty-text="暂无标的，点右上角「新增标的」开始"
      @retry="load"
    >
      <template #empty-action>
        <el-button type="primary" @click="openDialog()">新增标的</el-button>
      </template>

      <el-table :data="rows" row-key="id">
        <el-table-column prop="id" label="标识" min-width="140" show-overflow-tooltip>
          <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ typeLabel(row.type) }}</template>
        </el-table-column>
        <el-table-column label="代码" width="110">
          <template #default="{ row }">{{ row.code || '—' }}</template>
        </el-table-column>
        <el-table-column label="基准指数" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.benchmark_index || '—' }}</template>
        </el-table-column>
        <el-table-column label="账户" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.account || '—' }}</template>
        </el-table-column>
        <el-table-column label="持仓数量" align="right" width="120">
          <template #default="{ row }">{{ fmtQty(row.held_qty) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.from_db" type="primary" effect="plain" size="small">数据库</el-tag>
            <el-tag v-else type="info" size="small">YAML 种子</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDialog(row as InstrumentRow)">编辑</el-button>
            <el-button link type="danger" @click="remove(row as InstrumentRow)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </StateBlock>
  </div>

  <el-dialog v-model="dialog" :title="editing ? '编辑标的' : '新增标的'" width="560px" :close-on-click-modal="false">
    <el-collapse v-if="ocrText" v-model="ocrOpen" class="ocr-fold">
      <el-collapse-item title="识别原文（核对用）" name="text">
        <pre class="ocr-text">{{ ocrText }}</pre>
      </el-collapse-item>
    </el-collapse>
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="标识" prop="id">
        <el-input v-model="form.id" :disabled="editing" placeholder="如 my_fund（2-32 位小写字母/数字/下划线）" />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="展示名称" />
      </el-form-item>
      <el-form-item label="类型" prop="type">
        <el-select v-model="form.type" placeholder="选择类型" style="width: 100%">
          <el-option v-for="t in TYPES" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="代码">
        <el-input v-model="form.code" placeholder="基金/股票代码；债券带 sh/sz 前缀；理财留空" />
      </el-form-item>
      <el-form-item label="基准指数">
        <el-input v-model="form.benchmark_index" placeholder="可空，如 中证红利" />
      </el-form-item>
      <el-form-item label="账户">
        <el-input v-model="form.account" placeholder="如 pension / a_stock / bank" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.ocr-fold {
  margin-bottom: 16px;
}
.ocr-text {
  margin: 0;
  max-height: 220px;
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
</style>
