<!--
  指数估值（对齐小程序 valuation）：市场温度（5y PE 分位等权，页头温度条）· 估值表（收盘 / PE / 5年与全历史分位 / 股息率）。
  估值语义着色（与盈亏红绿口径无关）：分位低 = 便宜 = 绿，分位高 = 贵 = 红；未就绪（无 PE 历史）指数整行置灰。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { QuestionFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { errMsg } from '@/api/client'
import { getValuation } from '@/api/invest'
import type { ValuationPayload, ValuationRow } from '@/types'
import { fmtAmount, fmtPlainPct } from '@/utils/format'

const router = useRouter()

const data = ref<ValuationPayload | null>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getValuation()
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/* ---------- 市场温度：<20 偏冷（蓝绿）/ 20-50 适中（橙）/ >50 偏热（红） ---------- */

const TEMP_TIP =
  '市场温度 = 估值表各指数 5 年 PE 分位的等权平均（0-100）：低于 20 偏冷，20-50 适中，高于 50 偏热；5 年分位就绪的指数不足 5 个时不显示'

const temp = computed(() => data.value?.temperature ?? null)

const tempTone = computed(() => {
  const t = temp.value
  if (t === null) return null
  if (t < 20) return { color: '#0e8a9e', label: '偏冷' }
  if (t <= 50) return { color: '#d46b08', label: '适中' }
  return { color: '#d54941', label: '偏热' }
})

const tempPct = computed(() => Math.min(100, Math.max(0, temp.value ?? 0)))

function fmtTemp(): string {
  return temp.value === null ? '' : `${temp.value.toFixed(1)}℃`
}

const desc = computed(() => {
  if (!data.value) return ''
  if (temp.value === null) return '市场温度暂不可用：5 年分位就绪的指数不足 5 个'
  return `市场温度 ${temp.value.toFixed(1)}℃ · 5y 分位等权`
})

/* ---------- 估值表 ---------- */

/** 估值语义：分位 <30 便宜（绿）/ 30-60 中性 / >60 偏贵（红） */
function pctTone(p: number | null): string {
  if (p === null) return 'muted'
  if (p > 60) return 'danger'
  if (p < 30) return 'success'
  return ''
}

function rowClass({ row }: { row: ValuationRow }): string {
  return row.ready ? '' : 'row-pending'
}

const pendingCount = computed(() => (data.value?.indexes ?? []).filter((r) => !r.ready).length)

type SortProp = 'pe' | 'pct_5y' | 'pct_all' | 'dyield'
const sort = ref<{ prop: SortProp; order: 'ascending' | 'descending' } | null>(null)

function onSortChange({ prop, order }: { prop: string | null; order: 'ascending' | 'descending' | null }) {
  sort.value = prop && order ? { prop: prop as SortProp, order } : null
}

/** 自定义排序：无值（未就绪）恒排末尾，不随升降序翻到表头 */
const rows = computed<ValuationRow[]>(() => {
  const list = data.value?.indexes ?? []
  const s = sort.value
  if (!s) return list
  const dir = s.order === 'ascending' ? 1 : -1
  return [...list].sort((a, b) => {
    const va = a[s.prop]
    const vb = b[s.prop]
    if (va === null || vb === null) return va === vb ? 0 : va === null ? 1 : -1
    return (va - vb) * dir
  })
})

onMounted(load)
</script>

<template>
  <PageHeader title="指数估值" :desc="desc">
    <template #actions>
      <el-tooltip v-if="tempTone" :content="TEMP_TIP" placement="bottom-end">
        <div class="temp">
          <span class="temp-label" :style="{ color: tempTone.color }">{{ tempTone.label }}</span>
          <el-progress class="temp-bar" :percentage="tempPct" :color="tempTone.color" :stroke-width="10" :format="fmtTemp" />
        </div>
      </el-tooltip>
    </template>
  </PageHeader>

  <StateBlock
    :loading="loading"
    :error="error"
    :empty="!!data && !data.indexes.length"
    :has-data="!!data"
    empty-text="暂无估值数据，需先拉取指数估值"
    @retry="load"
  >
    <template #empty-action>
      <el-button type="primary" @click="router.push('/settings')">去设置页拉数</el-button>
    </template>

    <div class="panel">
      <div class="panel-title">
        <span>估值表 <span class="muted hint">分位越低越便宜：低于 30% 绿 · 30%-60% 中性 · 高于 60% 红</span></span>
        <el-button v-if="pendingCount" link type="primary" @click="router.push('/settings')">
          {{ pendingCount }} 个指数未就绪，去拉数
        </el-button>
      </div>

      <el-table :data="rows" row-key="code" :row-class-name="rowClass" class="val-table" @sort-change="onSortChange">
        <el-table-column label="指数" min-width="180">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="!row.ready" type="info" size="small" effect="plain" class="pending-tag">未就绪</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="代码" width="110" />
        <el-table-column label="收盘" align="right" width="130">
          <template #default="{ row }">{{ fmtAmount(row.close) }}</template>
        </el-table-column>
        <el-table-column prop="pe" label="PE(TTM)" align="right" width="120" sortable="custom">
          <template #default="{ row }">{{ row.pe === null ? '—' : row.pe.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="pct_5y" label="5年分位" align="right" width="130" sortable="custom">
          <template #header>
            <el-tooltip content="当前 PE 在近 5 年历史区间的位置：0% 为区间最低（最便宜），100% 为最高（最贵）" placement="top">
              <span class="th-tip">5年分位<el-icon><QuestionFilled /></el-icon></span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span :class="pctTone(row.pct_5y)">{{ fmtPlainPct(row.pct_5y, 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="pct_all" label="全历史分位" align="right" width="140" sortable="custom">
          <template #header>
            <el-tooltip content="当前 PE 在全部历史区间的位置：0% 为历史最低（最便宜），100% 为历史最高（最贵）" placement="top">
              <span class="th-tip">全历史分位<el-icon><QuestionFilled /></el-icon></span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <span :class="pctTone(row.pct_all)">{{ fmtPlainPct(row.pct_all, 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="dyield" label="股息率" align="right" width="110" sortable="custom">
          <template #default="{ row }">{{ fmtPlainPct(row.dyield, 2) }}</template>
        </el-table-column>
      </el-table>

      <p class="note muted">
        分位 = 当前 PE 在历史窗口内的位置，仅作低买高卖的纪律参考，不构成投资建议；股息率为近 12 个月口径。数据随「立即拉数」更新，未就绪指数需先拉取 PE 历史。
      </p>
    </div>
  </StateBlock>
</template>

<style scoped>
.temp {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 280px;
  align-self: center;
  cursor: help;
}
.temp-label {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
}
.temp-bar {
  flex: 1;
}
.hint {
  font-size: 12px;
  font-weight: 400;
  margin-left: 8px;
}
.th-tip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: help;
}
.pending-tag {
  margin-left: 8px;
}
.val-table :deep(.row-pending td.el-table__cell) {
  background: #fafbfc;
  color: var(--iv-text-3);
}
.note {
  font-size: 12px;
  line-height: 1.6;
  margin: 12px 0 0;
}
</style>
