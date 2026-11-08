<!--
  流水（对齐小程序 trades）：筛选（标的服务端 / 动作+关键词本地）· 表格分页 · 记一笔弹窗（按份额/按金额）· 删除确认。
  路由参数：?add=1 打开记一笔；?instrument=<id> 预选标的筛选（标的详情页跳转用）。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { MagicStick, Plus } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { errMsg } from '@/api/client'
import { addTrade, deleteTrade, getTrades, parseTradeText } from '@/api/invest'
import { ACTION_LABELS, type InstrumentBrief, type TradeRow } from '@/types'
import { fmtAmount, fmtQty, localDate } from '@/utils/format'

const route = useRoute()

const trades = ref<TradeRow[]>([])
const instruments = ref<InstrumentBrief[]>([])
const loading = ref(true)
const error = ref('')

const filter = reactive({
  instrument: typeof route.query.instrument === 'string' ? route.query.instrument : '',
  action: '',
  keyword: '',
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getTrades(filter.instrument || undefined)
    trades.value = res.trades
    // 标的下拉以「全量」为准：带筛选请求时后端仍返回完整标的清单
    instruments.value = res.instruments
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

watch(() => filter.instrument, load)

const nameOf = computed(() => Object.fromEntries(instruments.value.map((i) => [i.id, i.name])))

const filtered = computed(() => {
  const kw = filter.keyword.trim().toLowerCase()
  return trades.value.filter((t) => {
    if (filter.action && t.action !== filter.action) return false
    if (!kw) return true
    return [nameOf.value[t.instrument_id] || '', t.instrument_id, t.note].some((s) => s.toLowerCase().includes(kw))
  })
})

/* ---------- 分页（本地） ---------- */
const page = ref(1)
const pageSize = ref(20)
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
watch(filtered, () => (page.value = 1))

/* ---------- 删除：整行匹配（流水无 id） ---------- */
async function remove(row: TradeRow) {
  try {
    await deleteTrade({
      date: row.date,
      instrument_id: row.instrument_id,
      action: row.action,
      quantity: row.quantity,
      price: row.price,
      fee: row.fee,
      note: row.note,
    })
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

/* ---------- 记一笔 ---------- */

const ACTIONS = Object.entries(ACTION_LABELS).map(([value, label]) => ({ value, label }))

const dialog = ref(route.query.add === '1')
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  instrument_id: filter.instrument,
  action: 'buy',
  date: localDate(),
  byAmount: false,
  amount: undefined as number | undefined,
  quantity: undefined as number | undefined,
  price: undefined as number | undefined,
  fee: undefined as number | undefined,
  note: '',
})

/** 缴存：quantity 即金额、价格恒为 1（后端约定），表单只露「缴存金额」 */
const isContribute = computed(() => form.action === 'contribute')
/** 按金额录入仅对买入有意义：份额 = 金额 ÷ 价格（保留两位，与账本校验一致） */
const amountMode = computed(() => form.byAmount && form.action === 'buy')

watch(
  () => form.instrument_id,
  (id) => {
    const ins = instruments.value.find((i) => i.id === id)
    if (ins?.price) form.price = ins.price
  },
)

const derivedQty = computed(() => {
  if (!amountMode.value || !form.amount || !form.price) return undefined
  return Math.round((form.amount / form.price) * 100) / 100
})

const rules: FormRules = {
  instrument_id: [{ required: true, message: '请选择标的', trigger: 'change' }],
  action: [{ required: true, message: '请选择动作', trigger: 'change' }],
  date: [{ required: true, message: '请选择日期', trigger: 'change' }],
}

function openAdd() {
  form.instrument_id = filter.instrument || form.instrument_id
  form.date = localDate()
  dialog.value = true
}

/* ---------- 智能录入 v1：一句话 → 预填确认 ---------- */

const smartText = ref('')
const smartBusy = ref(false)

async function smartParse() {
  const text = smartText.value.trim()
  if (!text || smartBusy.value) return
  smartBusy.value = true
  try {
    const r = await parseTradeText(text)
    if (!r.draft) {
      ElMessage.warning('没听懂，试试「今天买入消费50 1000元」')
      return
    }
    const d = r.draft
    form.instrument_id = d.instrument_id || filter.instrument || form.instrument_id
    form.action = (d.action as typeof form.action) || 'buy'
    form.date = d.date || localDate()
    form.price = d.price ?? undefined
    form.quantity = d.quantity ?? undefined
    form.amount = undefined
    form.fee = d.fee || undefined
    form.note = d.note || ''
    form.byAmount = false
    dialog.value = true
    if (r.missing.length) ElMessage.info(r.explanation)
    else ElMessage.success(r.explanation)
    smartText.value = ''
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    smartBusy.value = false
  }
}

/** 再来一笔：复制某行（日期换成今天）——定投场景一键复录 */
function repeatRow(row: TradeRow) {
  form.instrument_id = row.instrument_id
  form.action = row.action
  form.date = localDate()
  form.price = row.price || undefined
  form.quantity = row.quantity || undefined
  form.amount = undefined
  form.fee = row.fee || undefined
  form.note = row.note || ''
  form.byAmount = false
  dialog.value = true
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const quantity = isContribute.value ? form.amount : amountMode.value ? derivedQty.value : form.quantity
  const price = isContribute.value ? 1 : form.price
  if (!quantity || quantity <= 0) return ElMessage.warning(isContribute.value ? '请输入缴存金额' : '份额必须为正数')
  if (!price || price <= 0) return ElMessage.warning('价格必须为正数')
  saving.value = true
  try {
    await addTrade({
      instrument_id: form.instrument_id,
      action: form.action,
      date: form.date,
      quantity,
      price,
      fee: form.fee || 0,
      note: form.note.trim(),
    })
    ElMessage.success('已记录')
    dialog.value = false
    form.amount = form.quantity = form.fee = undefined
    form.note = ''
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="流水" :desc="`共 ${filtered.length} 条${filter.instrument ? ' · 已按标的筛选' : ''}`">
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openAdd">记一笔</el-button>
    </template>
  </PageHeader>

  <div class="panel">
    <div class="smart-bar">
      <el-input
        v-model="smartText"
        placeholder="一句话记账：今天买入消费50 1000元 / 昨天定投红利 500 / 缴存养老金 3000"
        clearable
        class="smart-input"
        @keyup.enter="smartParse"
      >
        <template #prefix><el-icon><MagicStick /></el-icon></template>
      </el-input>
      <el-button type="primary" :loading="smartBusy" @click="smartParse">解析记账</el-button>
      <span class="muted smart-hint">解析后弹窗预填，确认才落账</span>
    </div>
    <div class="filters">
      <el-select v-model="filter.instrument" placeholder="全部标的" clearable filterable style="width: 220px">
        <el-option v-for="i in instruments" :key="i.id" :label="i.name" :value="i.id" />
      </el-select>
      <el-select v-model="filter.action" placeholder="全部动作" clearable style="width: 140px">
        <el-option v-for="a in ACTIONS" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-input v-model="filter.keyword" placeholder="搜索标的 / 备注" clearable style="width: 240px" />
    </div>

    <StateBlock :loading="loading" :error="error" :empty="!filtered.length" :has-data="!!trades.length" empty-text="没有符合条件的流水" @retry="load">
      <el-table :data="paged">
        <el-table-column prop="date" label="日期" width="110" sortable />
        <el-table-column label="标的" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ nameOf[row.instrument_id] || row.instrument_id }}</template>
        </el-table-column>
        <el-table-column label="动作" width="110">
          <template #default="{ row }">
            <el-tag :type="row.action === 'sell' ? 'success' : row.action === 'buy' ? 'danger' : 'info'" size="small" effect="plain">
              {{ row.action_label || ACTION_LABELS[row.action] || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="份额" align="right" width="120">
          <template #default="{ row }">{{ fmtQty(row.quantity) }}</template>
        </el-table-column>
        <el-table-column label="价格" align="right" width="110">
          <template #default="{ row }">{{ fmtAmount(row.price, 4) }}</template>
        </el-table-column>
        <el-table-column label="金额" align="right" width="130">
          <template #default="{ row }">{{ fmtAmount(row.quantity * row.price) }}</template>
        </el-table-column>
        <el-table-column label="费用" align="right" width="90">
          <template #default="{ row }">{{ row.fee ? fmtAmount(row.fee) : '—' }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="120" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="repeatRow(row as TradeRow)">再来一笔</el-button>
            <el-popconfirm title="确定删除这条流水？" confirm-button-text="删除" @confirm="remove(row as TradeRow)">
              <template #reference>
                <el-button link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          :total="filtered.length"
          layout="total, sizes, prev, pager, next"
          background
        />
      </div>
    </StateBlock>
  </div>

  <el-dialog v-model="dialog" title="记一笔" width="520px" :close-on-click-modal="false">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="标的" prop="instrument_id">
        <el-select v-model="form.instrument_id" filterable placeholder="选择标的" style="width: 100%">
          <el-option v-for="i in instruments" :key="i.id" :label="i.name" :value="i.id">
            <span>{{ i.name }}</span>
            <span class="opt-price muted">{{ i.price_label }}</span>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="动作" prop="action">
        <el-radio-group v-model="form.action">
          <el-radio-button v-for="a in ACTIONS" :key="a.value" :value="a.value">{{ a.label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="日期" prop="date">
        <el-date-picker v-model="form.date" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 100%" />
      </el-form-item>

      <template v-if="isContribute">
        <el-form-item label="缴存金额">
          <el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false" style="width: 100%" />
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item v-if="form.action === 'buy'" label="录入方式">
          <el-switch v-model="form.byAmount" active-text="按金额" inactive-text="按份额" />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="form.price" :min="0" :precision="4" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="amountMode" label="金额">
          <el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false" style="width: 100%" />
          <div class="derived muted">折算份额：{{ derivedQty === undefined ? '—' : fmtQty(derivedQty) }}</div>
        </el-form-item>
        <el-form-item v-else label="份额">
          <el-input-number v-model="form.quantity" :min="0" :precision="2" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="费用">
          <el-input-number v-model="form.fee" :min="0" :precision="2" :controls="false" style="width: 100%" />
        </el-form-item>
      </template>
      <el-form-item label="备注">
        <el-input v-model="form.note" maxlength="100" show-word-limit />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.smart-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.smart-input {
  flex: 1;
}
.smart-hint {
  font-size: 12px;
  flex-shrink: 0;
}
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.opt-price {
  float: right;
  font-size: 12px;
}
.derived {
  font-size: 12px;
  margin-top: 4px;
}
</style>
