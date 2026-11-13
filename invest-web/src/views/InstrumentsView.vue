<!--
  标的管理（对齐小程序 instruments）：标的表（db + yaml 合并视角，带持仓数量）· 新增 / 编辑共用弹窗 ·
  从截图识别（OCR + AI 反显表单，依赖 macOS Vision，Linux 部署 422 属预期降级）· 删除双保护（持仓 409 / yaml 种子 404）。
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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
import { deleteInstrument, getInstruments, parseInstrumentImage, saveInstrument, searchInstrumentCatalog, browseInstrumentCatalog } from '@/api/invest'
import type { InstrumentForm, InstrumentRow } from '@/types'
import { fmtQty } from '@/utils/format'

/** 品类：value 为后端 INSTRUMENT_TYPES，中文与小程序一致 */
const TYPES = [
  { value: 'open_end_fund', label: '场外基金', group: 'fund' },
  { value: 'etf', label: 'ETF', group: 'fund' },
  { value: 'stock', label: '股票', group: 'stock' },
  { value: 'bond', label: '债券', group: 'bond' },
  { value: 'wealth', label: '理财/固收', group: 'wealth' },
]
const typeLabel = (t: string) => TYPES.find((x) => x.value === t)?.label || t || '—'
const typeGroup = (t: string) => TYPES.find((x) => x.value === t)?.group || 'other'

/** 资产大类 Tab（家庭四类 + 全部 + 标的目录） */
const GROUPS = [
  { value: '', label: '全部', icon: '' },
  { value: 'fund', label: '基金', icon: '🍬' },
  { value: 'stock', label: '股票', icon: '📈' },
  { value: 'bond', label: '债券', icon: '🏛' },
  { value: 'wealth', label: '理财', icon: '💰' },
]
const activeGroup = ref('')

/* ---------- 标的目录（可浏览 4000+ 热门标的） ---------- */
const CATALOG_TYPES = [
  { value: '', label: '全部' },
  { value: 'fund', label: '基金' },
  { value: 'etf', label: 'ETF' },
  { value: 'stock', label: '股票' },
  { value: 'bond', label: '债券' },
]
const catalogActive = ref(false)
const catalogType = ref('')
const catalogSearch = ref('')
const catalogRows = ref<{ code: string; name: string; full_name: string; itype: string; suggested_type: string; benchmark_index: string; already_added: boolean }[]>([])
const catalogTotal = ref(0)
const catalogPage = ref(1)
const catalogLoading = ref(false)
let catalogTimer: ReturnType<typeof setTimeout> | null = null

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const r = await browseInstrumentCatalog({
      q: catalogSearch.value.trim() || undefined,
      page: catalogPage.value,
      page_size: 50,
      itype: catalogType.value || undefined,
    })
    catalogRows.value = r.results
    catalogTotal.value = r.total
  } catch {
    catalogRows.value = []
  } finally {
    catalogLoading.value = false
  }
}

watch(catalogSearch, () => {
  if (catalogTimer) clearTimeout(catalogTimer)
  catalogTimer = setTimeout(() => {
    catalogPage.value = 1
    loadCatalog()
  }, 400)
})

watch(catalogType, () => {
  catalogPage.value = 1
  loadCatalog()
})

watch(catalogActive, (v) => {
  if (v && !catalogRows.value.length) loadCatalog()
})

/** 目录品类标签颜色/文案 */
function catTagColor(itype: string): 'primary' | 'success' | 'danger' | 'warning' | 'info' {
  const map: Record<string, 'primary' | 'success' | 'danger' | 'warning' | 'info'> = { fund: 'primary', etf: 'success', stock: 'danger', bond: 'warning', index: 'info' }
  return map[itype] || 'info'
}
function catTypeLabel(itype: string): string {
  const map: Record<string, string> = { fund: '基金', etf: 'ETF', stock: '股票', bond: '债券', index: '指数' }
  return map[itype] || itype
}

/** 从目录一键加入我的标的（接受任意行对象，取需要的字段） */
async function addFromBrowse(item: Record<string, unknown>) {
  const code = String(item.code || "")
  const name = String(item.name || "")
  const suggested_type = String(item.suggested_type || "")
  const benchmark_index = String(item.benchmark_index || "")
  if (item.already_added) return
  openDialog()
  form.name = name
  form.code = code
  form.benchmark_index = benchmark_index
  if (suggested_type && TYPES.some((t) => t.value === suggested_type)) {
    form.type = suggested_type
  }
  ElMessage.success(`已填入「${name}」，请选择账户后保存`)
}

/** 品类统计（按当前标的列表实时算） */
const groupStats = computed(() => {
  const stats = GROUPS.filter((g) => g.value).map((g) => {
    const items = rows.value.filter((r) => typeGroup(r.type) === g.value)
    return { ...g, count: items.length, held: items.filter((i) => i.held_qty > 0).length }
  })
  return stats
})

const filteredRows = computed(() => {
  if (!activeGroup.value) return rows.value
  return rows.value.filter((r) => typeGroup(r.type) === activeGroup.value)
})

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

/** 持仓状态 */
function heldLabel(qty: number): { text: string; type: TagType } {
  if (qty > 0) return { text: '持有中', type: 'success' }
  return { text: '已清仓', type: 'info' }
}

/** 类型 → 标签颜色 */
function typeTagColor(t: string): TagType {
  const map: Record<string, TagType> = {
    open_end_fund: 'primary',
    etf: 'primary',
    stock: 'danger',
    bond: 'warning',
    wealth: 'success',
  }
  return map[t] || 'info'
}

/** 账户 slug → 中文名 */
function accountLabel(slug: string): string {
  return ACCOUNTS.find((a) => a.value === slug)?.label || slug
}

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

/** 常用账户（下拉选择 + 允许自定义输入） */
const ACCOUNTS = [
  { value: 'pension', label: '个人养老金' },
  { value: 'a_stock', label: 'A股证券' },
  { value: 'bank', label: '银行账户' },
  { value: 'broker', label: '券商' },
  { value: '', label: '暂不指定' },
]

/** 品类动态表单提示 */
const CODE_HINTS: Record<string, string> = {
  open_end_fund: '6 位基金代码，如 001102',
  etf: '场内 ETF 代码，如 159928',
  stock: '6 位股票代码，如 600519',
  bond: '债券代码带市场前缀，如 sh019547',
  wealth: '理财产品无需代码，留空即可',
}
const BENCH_HINTS: Record<string, string> = {
  open_end_fund: '跟踪的指数名称，如 中证红利',
  etf: '跟踪的指数名称，如 中证消费50',
  stock: '可空，板块或行业指数',
  bond: '可空',
  wealth: '可空',
}

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
  catalogPick.value = ""
  searchResults.value = []
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

/* ---------- 实时搜索标的目录（el-select remote 模式）---------- */

const catalogPick = ref('')
const searchResults = ref<{ code: string; name: string; full_name: string; itype: string; suggested_type: string; benchmark_index: string; already_added: boolean }[]>([])
const searching = ref(false)

async function remoteSearch(q: string) {
  if (!q || q.trim().length < 2) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const r = await searchInstrumentCatalog(q.trim())
    searchResults.value = r.results
  } catch {
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

/** 从下拉选中 → 自动预填全表单 */
function onCatalogPick(val: string) {
  if (!val) return
  const [code] = val.split("|")
  const item = searchResults.value.find((r) => r.code === code)
  if (!item) return
  form.name = item.name
  form.code = item.code
  form.benchmark_index = item.benchmark_index || ""
  if (item.suggested_type && TYPES.some((t) => t.value === item.suggested_type)) {
    form.type = item.suggested_type
  }
  ElMessage.success(`已填入「${item.name}」，请选择账户后保存`)
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
  <PageHeader title="标的管理" desc="按资产大类管理家庭持仓标的；新增后需「立即拉数」抓取行情">
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

  <!-- 我的标的 / 标的目录 切换 -->
  <div class="view-switch">
    <el-radio-group v-model="catalogActive">
      <el-radio-button :value="false">我的标的</el-radio-button>
      <el-radio-button :value="true">标的目录（{{ catalogTotal || '…' }}）</el-radio-button>
    </el-radio-group>
  </div>

  <!-- 标的目录模式 -->
  <div v-if="catalogActive" class="panel">
    <div class="catalog-bar">
      <el-radio-group v-model="catalogType" size="small">
        <el-radio-button v-for="t in CATALOG_TYPES" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
      </el-radio-group>
      <el-input v-model="catalogSearch" placeholder="搜索名称/代码" clearable size="small" style="width: 240px" />
    </div>
    <StateBlock :loading="catalogLoading" :empty="!catalogRows.length" :has-data="!!catalogRows.length" empty-text="没有符合条件的标的">
      <el-table :data="catalogRows" size="small" row-key="code">
        <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span style="font-weight:500">{{ row.name }}</span>
            <el-tag :type="catTagColor(row.itype)" size="small" effect="plain" style="margin-left:6px">
              {{ catTypeLabel(row.itype) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="代码" width="110">
          <template #default="{ row }"><span class="mono">{{ row.code }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-tag v-if="row.already_added" type="info" size="small">已添加</el-tag>
            <el-button v-else type="primary" size="small" @click="addFromBrowse(row)">加入</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="catalog-pager">
        <el-pagination
          v-model:current-page="catalogPage"
          :page-size="50"
          :total="catalogTotal"
          layout="prev, pager, next, total"
          background
          small
          @current-change="loadCatalog"
        />
      </div>
    </StateBlock>
  </div>

  <!-- 我的标的模式（原有内容） -->
  <template v-else>
  <!-- 品类统计条 -->
  <div v-if="rows.length" class="grid grid-4 group-stats">
    <div
      v-for="g in groupStats"
      :key="g.value"
      class="panel group-card"
      :class="{ active: activeGroup === g.value }"
      @click="activeGroup = activeGroup === g.value ? '' : g.value"
    >
      <div class="gc-icon">{{ g.icon }}</div>
      <div class="gc-body">
        <div class="gc-name">{{ g.label }}</div>
        <div class="gc-num num">{{ g.count }} 个标的</div>
        <div class="gc-held muted">{{ g.held }} 个持有中</div>
      </div>
    </div>
  </div>

  <div class="panel panel-gap">
    <StateBlock
      :loading="loading"
      :error="error"
      :empty="!filteredRows.length"
      :has-data="!!rows.length"
      :empty-text="activeGroup ? '该品类暂无标的' : '暂无标的，点右上角「新增标的」开始'"
      @retry="load"
    >
      <template #empty-action>
        <el-button type="primary" @click="openDialog()">新增标的</el-button>
      </template>

      <!-- 品类 Tab -->
      <el-tabs v-if="rows.length" v-model="activeGroup" class="type-tabs">
        <el-tab-pane v-for="g in GROUPS" :key="g.value" :label="g.label" :name="g.value" />
      </el-tabs>

      <el-table :data="filteredRows" row-key="id">
        <el-table-column prop="name" label="名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="ins-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="typeTagColor(row.type)" effect="light" size="small">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="代码" width="120">
          <template #default="{ row }"><span class="mono">{{ row.code || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="基准指数" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.benchmark_index || '—' }}</template>
        </el-table-column>
        <el-table-column label="账户" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.account" type="info" size="small" effect="plain">{{ accountLabel(row.account) }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="持仓数量" align="right" width="110" sortable :sort-by="'held_qty'">
          <template #default="{ row }">{{ fmtQty(row.held_qty) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="heldLabel(row.held_qty).type" size="small">{{ heldLabel(row.held_qty).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.from_db" type="primary" effect="plain" size="small">自建</el-tag>
            <el-tag v-else type="info" size="small">配置</el-tag>
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
  </template><!-- /v-else 我的标的 -->

  <el-dialog v-model="dialog" :title="editing ? '编辑标的' : '新增标的'" width="560px" :close-on-click-modal="false">
    <!-- 实时搜索：输入即出下拉，选中自动预填全表单（新增模式才显示） -->
    <div v-if="!editing" class="smart-search-zone">
      <el-select
        v-model="catalogPick"
        filterable
        remote
        clearable
        placeholder="搜索标的（输入名称/代码，选中后自动填入）"
        :remote-method="remoteSearch"
        :loading="searching"
        size="large"
        class="smart-select"
        @change="onCatalogPick"
      >
        <el-option
          v-for="item in searchResults"
          :key="item.code + item.itype"
          :label="`${item.name} (${item.code})`"
          :value="item.code + '|' + item.itype"
          :disabled="item.already_added"
        >
          <div class="remote-option">
            <span class="ro-name">{{ item.name }}</span>
            <el-tag :type="item.itype === 'fund' ? 'primary' : item.itype === 'etf' ? 'success' : item.itype === 'stock' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ { fund: '基金', etf: 'ETF', stock: '股票', bond: '债券', index: '指数' }[item.itype] || item.itype }}
            </el-tag>
            <span class="ro-code mono">{{ item.code }}</span>
            <el-tag v-if="item.already_added" type="info" size="small">已添加</el-tag>
          </div>
        </el-option>
      </el-select>
      <p class="muted smart-hint">从 38,000+ 标的中搜索；选中后自动填入，也可直接手动填写下方表单</p>
    </div>
    <el-collapse v-if="ocrText" v-model="ocrOpen" class="ocr-fold">
      <el-collapse-item title="识别原文（核对用）" name="text">
        <pre class="ocr-text">{{ ocrText }}</pre>
      </el-collapse-item>
    </el-collapse>
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="类型" prop="type">
        <el-radio-group v-model="form.type">
          <el-radio-button v-for="t in TYPES" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="展示名称，如 中证红利基金Y" />
      </el-form-item>
      <el-form-item label="标识" prop="id">
        <el-input v-model="form.id" :disabled="editing" placeholder="唯一标识（2-32 位小写字母/数字/下划线）" />
      </el-form-item>
      <el-form-item label="代码">
        <el-input v-model="form.code" :placeholder="CODE_HINTS[form.type] || '可空'" />
        <div class="form-hint muted">{{ CODE_HINTS[form.type] }}</div>
      </el-form-item>
      <el-form-item label="基准指数">
        <el-input v-model="form.benchmark_index" :placeholder="BENCH_HINTS[form.type] || '可空'" />
      </el-form-item>
      <el-form-item label="账户">
        <el-select v-model="form.account" filterable allow-create placeholder="选择或输入账户" style="width: 100%">
          <el-option v-for="a in ACCOUNTS" :key="a.value" :label="a.label" :value="a.value" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.view-switch {
  margin-bottom: 16px;
}
.catalog-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.catalog-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.smart-search-zone {
  margin-bottom: 20px;
}
.smart-select {
  width: 100%;
}
.smart-hint {
  font-size: 12px;
  margin: 6px 0 0;
  text-align: center;
}
.remote-option {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ro-name {
  font-weight: 500;
}
.ro-code {
  font-size: 12px;
  color: var(--iv-text-3);
}
.search-results {
  margin-top: 16px;
  max-height: 400px;
  overflow-y: auto;
}
.search-empty {
  text-align: center;
  padding: 40px 0;
  font-size: 13px;
}
.search-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border: 1px solid var(--iv-border);
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.search-item:hover {
  border-color: var(--iv-primary);
  background: var(--el-color-primary-light-9);
}
.si-name {
  font-weight: 600;
  font-size: 14px;
}
.si-code {
  font-size: 12px;
  color: var(--iv-text-3);
  margin-top: 2px;
}
.si-tag {
  margin-left: 6px;
  vertical-align: middle;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.form-hint {
  font-size: 12px;
  margin-top: 2px;
}
.group-stats {
  margin-bottom: 0;
  cursor: pointer;
}
.group-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  cursor: pointer;
  border: 1px solid var(--iv-border);
  transition: border-color 0.2s, background 0.2s;
}
.group-card:hover {
  border-color: var(--iv-primary);
}
.group-card.active {
  border-color: var(--iv-primary);
  background: var(--el-color-primary-light-9);
}
.gc-icon {
  font-size: 28px;
  flex-shrink: 0;
}
.gc-name {
  font-weight: 600;
  font-size: 14px;
}
.gc-num {
  font-size: 20px;
  font-weight: 700;
  margin-top: 2px;
}
.gc-held {
  font-size: 12px;
  margin-top: 2px;
}
.type-tabs {
  margin-bottom: 16px;
}
.type-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.ins-name {
  font-weight: 500;
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
