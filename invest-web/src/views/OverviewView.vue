<!--
  总览（对齐小程序 overview）：指标卡 / 数据延迟徽标（S10 AC-5）/ 品类占比 / 持仓表钻取 / 基准估值 / 近期信号 / 立即拉数。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import StatCard from '@/components/StatCard.vue'
import { ApiError, errMsg } from '@/api/client'
import { getOverview, getPullStatus, startPull } from '@/api/invest'
import type { Overview, Position, PullStatus } from '@/types'
import { fmtAmount, fmtPct, fmtPlainPct, fmtQty, fmtSigned, pnlClass } from '@/utils/format'

const router = useRouter()

const data = ref<Overview | null>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getOverview()
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/* ---------- 持仓：扁平化 + 品类占比 ---------- */

interface Row extends Position {
  group_label: string
}

const rows = computed<Row[]>(() =>
  (data.value?.groups ?? []).flatMap((g) => g.positions.map((p) => ({ ...p, group_label: g.label }))),
)

const groupFilters = computed(() => (data.value?.groups ?? []).map((g) => ({ text: g.label, value: g.label })))

const mix = computed(() => {
  const groups = (data.value?.groups ?? []).filter((g) => (g.market_value ?? 0) > 0)
  const total = groups.reduce((s, g) => s + (g.market_value ?? 0), 0)
  if (!total) return []
  return groups.map((g, i) => ({
    label: g.label,
    value: g.market_value ?? 0,
    pct: ((g.market_value ?? 0) / total) * 100,
    color: MIX_COLORS[i % MIX_COLORS.length],
  }))
})
const MIX_COLORS = ['#1652a8', '#5c86c2', '#d46b08', '#7a4fbf', '#0e8a9e']

const pension = computed(() => {
  const p = data.value?.pension_progress
  if (!p || !p.cap) return null
  return { ...p, pct: Math.min(100, (p.contributed / p.cap) * 100) }
})

function filterGroup(value: string, row: Row) {
  return row.group_label === value
}

function openInstrument(row: Row) {
  router.push({ name: 'instrument', params: { id: row.id } })
}

/* ---------- 立即拉数：POST /pull → 轮询 /pull/status ---------- */

const pull = ref<PullStatus | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
  if (timer) clearInterval(timer)
  timer = null
}

async function poll() {
  try {
    pull.value = await getPullStatus()
    if (pull.value.status === 'done') {
      stopPolling()
      ElMessage.success('拉数完成')
      load()
    } else if (pull.value.status === 'error') {
      stopPolling()
      ElMessage.error('拉数失败，详见日志')
    }
  } catch (e) {
    stopPolling()
    ElMessage.error(errMsg(e))
  }
}

async function runPull() {
  try {
    await startPull()
  } catch (e) {
    // 409 = 已有拉数任务在跑：不报错，直接接管轮询
    if (!(e instanceof ApiError && e.status === 409)) {
      ElMessage.error(errMsg(e))
      return
    }
  }
  pull.value = { status: 'running', started: null, finished: null, log: [] }
  stopPolling()
  timer = setInterval(poll, 3000)
}

const pulling = computed(() => pull.value?.status === 'running')

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <PageHeader title="总览" :desc="data ? `数据截至 ${data.date} · 配置来源 ${data.config_source}` : ''">
    <template #tags>
      <el-tag v-if="data?.data_stale" type="warning" effect="light">数据延迟</el-tag>
      <el-tag v-if="data?.is_example" type="info" effect="light">示例数据</el-tag>
    </template>
    <template #actions>
      <el-popover v-if="pull" placement="bottom-end" :width="380" trigger="hover">
        <template #reference>
          <el-tag :type="pulling ? 'primary' : pull.status === 'error' ? 'danger' : 'success'" class="pull-tag">
            拉数：{{ { idle: '空闲', running: '进行中', done: '完成', error: '失败' }[pull.status] }}
          </el-tag>
        </template>
        <div class="pull-log">
          <div v-for="(l, i) in pull.log" :key="i">{{ l }}</div>
          <div v-if="!pull.log.length" class="muted">暂无日志</div>
        </div>
      </el-popover>
      <el-button :icon="Refresh" :loading="pulling" @click="runPull">立即拉数</el-button>
      <el-button type="primary" :icon="Plus" @click="router.push({ name: 'trades', query: { add: '1' } })">记一笔</el-button>
    </template>
  </PageHeader>

  <StateBlock :loading="loading" :error="error" :empty="!!data && !rows.length" :has-data="!!data" empty-text="还没有持仓，先去记一笔流水" @retry="load">
    <template #empty-action>
      <el-button type="primary" @click="router.push({ name: 'trades', query: { add: '1' } })">记一笔</el-button>
    </template>

    <template v-if="data">
      <div class="grid grid-4">
        <StatCard label="总资产" :value="fmtAmount(data.totals.market_value)" sub="按最新净值/收盘价计" />
        <StatCard
          label="浮动盈亏"
          :value="fmtSigned(data.totals.unrealized)"
          :tone="pnlClass(data.totals.unrealized)"
          sub="市值 − 持仓成本"
        />
        <StatCard label="组合 XIRR" :value="fmtPct(data.totals.xirr)" :tone="pnlClass(data.totals.xirr)" sub="资金加权年化收益" />
        <StatCard
          v-if="pension"
          :label="`养老金缴存 · ${pension.year}`"
          :value="`${fmtAmount(pension.contributed, 0)} / ${fmtAmount(pension.cap, 0)}`"
          sub=" "
        >
          <template #sub>
            <el-progress :percentage="Math.round(pension.pct)" :stroke-width="6" />
          </template>
        </StatCard>
        <StatCard v-else label="持仓标的" :value="String(rows.length)" sub="含已清仓留痕" />
      </div>

      <div v-if="mix.length" class="panel panel-gap">
        <div class="panel-title">品类占比</div>
        <div class="mix-bar">
          <div v-for="m in mix" :key="m.label" class="mix-seg" :style="{ width: m.pct + '%', background: m.color }" />
        </div>
        <div class="mix-legend">
          <span v-for="m in mix" :key="m.label" class="mix-item">
            <i :style="{ background: m.color }" />{{ m.label }}
            <b class="num">{{ m.pct.toFixed(1) }}%</b>
            <span class="muted num">{{ fmtAmount(m.value, 0) }}</span>
          </span>
        </div>
      </div>

      <div class="panel panel-gap">
        <div class="panel-title">持仓明细 <span class="muted hint">点击行查看标的详情</span></div>
        <el-table :data="rows" row-key="id" class="clickable" :default-sort="{ prop: 'market_value', order: 'descending' }" @row-click="openInstrument">
          <el-table-column prop="name" label="标的" min-width="180" show-overflow-tooltip />
          <el-table-column prop="group_label" label="品类" width="100" :filters="groupFilters" :filter-method="filterGroup" />
          <el-table-column prop="account" label="账户" width="110" show-overflow-tooltip />
          <el-table-column label="份额" align="right" width="110">
            <template #default="{ row }">{{ fmtQty(row.quantity) }}</template>
          </el-table-column>
          <el-table-column label="最新价" align="right" width="110">
            <template #default="{ row }">
              <el-tooltip :content="row.price_date ? `价格日期 ${row.price_date}` : '无行情'" placement="top">
                <span>{{ row.price === null ? '—' : fmtAmount(row.price, 4) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="成本" align="right" width="100">
            <template #default="{ row }">{{ row.avg_cost === null ? '—' : fmtAmount(row.avg_cost, 4) }}</template>
          </el-table-column>
          <el-table-column prop="market_value" label="市值" align="right" width="130" sortable>
            <template #default="{ row }">{{ fmtAmount(row.market_value) }}</template>
          </el-table-column>
          <el-table-column prop="unrealized" label="浮动盈亏" align="right" width="130" sortable>
            <template #default="{ row }"><span :class="pnlClass(row.unrealized)">{{ fmtSigned(row.unrealized) }}</span></template>
          </el-table-column>
          <el-table-column prop="unrealized_pct" label="收益率" align="right" width="100" sortable>
            <template #default="{ row }"><span :class="pnlClass(row.unrealized_pct)">{{ fmtPct(row.unrealized_pct) }}</span></template>
          </el-table-column>
          <el-table-column prop="xirr" label="XIRR" align="right" width="100" sortable>
            <template #default="{ row }">
              <el-tooltip v-if="row.xirr_error" content="现金流不足以求解年化" placement="top"><span class="muted">—</span></el-tooltip>
              <span v-else :class="pnlClass(row.xirr)">{{ fmtPct(row.xirr) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.state === 'noprice'" type="warning" size="small">缺行情</el-tag>
              <el-tag v-else-if="row.state === 'empty'" type="info" size="small">已清仓</el-tag>
              <el-tag v-else type="success" size="small" effect="plain">持有</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="grid grid-2 panel-gap">
        <div class="panel">
          <div class="panel-title">基准估值 <el-button link type="primary" @click="router.push('/valuation')">全部指数</el-button></div>
          <el-table :data="data.benchmarks" size="small" empty-text="暂无基准">
            <el-table-column prop="name" label="指数" min-width="110" show-overflow-tooltip />
            <el-table-column label="PE(TTM)" align="right" width="90">
              <template #default="{ row }">{{ row.pe_ttm ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="5年分位" align="right" width="90">
              <template #default="{ row }">{{ fmtPlainPct(row.pct_5y, 0) }}</template>
            </el-table-column>
            <el-table-column label="股息率" align="right" width="80">
              <template #default="{ row }">{{ fmtPlainPct(row.dyield, 2) }}</template>
            </el-table-column>
            <el-table-column label="5年回撤" align="right" width="90">
              <template #default="{ row }">{{ row.drawdown_5y === null ? '—' : (row.drawdown_5y * 100).toFixed(1) + '%' }}</template>
            </el-table-column>
          </el-table>
        </div>
        <div class="panel">
          <div class="panel-title">近期信号 <el-button link type="primary" @click="router.push('/signals')">全部信号</el-button></div>
          <el-table :data="data.signals.slice(0, 8)" size="small" empty-text="暂无信号">
            <el-table-column prop="date" label="日期" width="100" />
            <el-table-column prop="instrument" label="标的" min-width="110" show-overflow-tooltip />
            <el-table-column prop="action" label="建议" min-width="120" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="80" />
          </el-table>
        </div>
      </div>
    </template>
  </StateBlock>
</template>

<style scoped>
.pull-tag {
  align-self: center;
}
.pull-log {
  max-height: 260px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.7;
}
.hint {
  font-size: 12px;
  font-weight: 400;
}
.mix-bar {
  display: flex;
  height: 12px;
  border-radius: 6px;
  overflow: hidden;
  background: #f2f3f5;
}
.mix-seg {
  height: 100%;
}
.mix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-top: 12px;
  font-size: 13px;
}
.mix-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.mix-item i {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
</style>
