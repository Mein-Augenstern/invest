<!--
  信号（对齐小程序 signals「当前信号」页签）：立即评估 · 信号表（新→旧）· 「建议」态行内确认 / 忽略。
  仅用已挂载端点 /signals、/signals/evaluate、/signals/{id}/status；小程序 S02 的规则明细 / 纸面交易 PC 端暂不接。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { ApiError, errMsg } from '@/api/client'
import { evaluateSignals, getSignals, setSignalStatus } from '@/api/invest'
import type { Signal } from '@/types'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const signals = ref<Signal[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getSignals()
    signals.value = res.signals
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/** 倒序：日期新→旧，同日按 id 新→旧（后端已按 id 倒序，这里显式兜底） */
const rows = computed(() => [...signals.value].sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id))

/* ---------- 立即评估（后端同步计算，API 层已放宽到 60s 超时） ---------- */

const evaluating = ref(false)

async function evaluate() {
  evaluating.value = true
  try {
    const res = await evaluateSignals()
    // 后端口径：new 为新增条数（旧版为新增 id 列表），两种都兼容
    const added = Array.isArray(res.new) ? res.new.length : Number(res.new) || 0
    ElMessage.success(added ? `评估完成，新增 ${added} 条信号` : '评估完成，暂无新增信号')
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    evaluating.value = false
  }
}

/* ---------- 确认 / 忽略 ---------- */

const busyId = ref<number | null>(null)

async function mark(row: Signal, status: '已确认' | '已忽略') {
  busyId.value = row.id
  try {
    await setSignalStatus(row.id, status)
    row.status = status // 先本地落态，操作按钮立即消失；随后刷新与后端对齐
    ElMessage.success(status)
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
    if (e instanceof ApiError && e.status === 404) load() // 信号已不存在：列表过期，刷新
  } finally {
    busyId.value = null
  }
}

/* ---------- 着色 ---------- */

/** 「停止买入」「暂停加仓」之类的否定表述不算买入（真实动作如「停止买入（分位>85%），评估分批止盈」） */
const NEGATED_BUY = /(停止|暂停|不宜|避免)(买入|加仓|定投)/g

/** 建议动作是自由文本，按关键词着色：买入/加仓/定投 → 红，卖出/减仓/止盈 → 绿（红买绿卖，与流水页一致），其余中性 */
function actionTagType(action: string): TagType {
  const text = action.replace(NEGATED_BUY, '')
  if (/买入|加仓|定投/.test(text)) return 'danger'
  if (/卖出|减仓|止盈/.test(text)) return 'success'
  return 'info'
}

/** 状态：建议 = info；已确认 = success；已忽略 = 灰（plain + 降低不透明度，与「建议」区分） */
function statusTag(status: string): { type: TagType; effect: 'light' | 'plain'; dim: boolean } {
  if (status === '已确认') return { type: 'success', effect: 'light', dim: false }
  if (status === '已忽略') return { type: 'info', effect: 'plain', dim: true }
  return { type: 'info', effect: 'light', dim: false }
}

onMounted(load)
</script>

<template>
  <PageHeader title="信号" desc="规则化纪律信号，非投资建议">
    <template #actions>
      <el-button type="primary" :icon="Refresh" :loading="evaluating" @click="evaluate">
        {{ evaluating ? '评估中…' : '立即评估' }}
      </el-button>
    </template>
  </PageHeader>

  <div class="panel">
    <StateBlock
      :loading="loading"
      :error="error"
      :empty="!rows.length"
      :has-data="!!signals.length"
      empty-text="暂无信号，点右上角立即评估"
      @retry="load"
    >
      <el-table :data="rows" row-key="id" class="signal-table">
        <el-table-column prop="date" label="日期" width="110" />
        <el-table-column prop="instrument" label="标的" min-width="150" show-overflow-tooltip />
        <el-table-column prop="rule" label="规则" min-width="170" show-overflow-tooltip />
        <el-table-column label="指标" min-width="240">
          <template #default="{ row }">
            <span class="muted">{{ row.metric || '—' }}</span>
            <span v-if="row.value" class="metric-value num">{{ row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column label="建议" min-width="260">
          <template #default="{ row }">
            <el-tag v-if="row.action" :type="actionTagType(row.action)" effect="plain" class="wrap-tag">
              {{ row.action }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              :type="statusTag(row.status).type"
              :effect="statusTag(row.status).effect"
              :class="{ 'tag-dim': statusTag(row.status).dim }"
              size="small"
            >
              {{ row.status || '—' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === '建议'">
              <el-button link type="primary" :loading="busyId === row.id" @click="mark(row as Signal, '已确认')">确认</el-button>
              <el-button link :disabled="busyId === row.id" @click="mark(row as Signal, '已忽略')">忽略</el-button>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </StateBlock>
  </div>
</template>

<style scoped>
.metric-value {
  margin-left: 8px;
  font-weight: 600;
  color: var(--iv-text);
}
/* 建议动作是整句文本：允许标签换行，避免撑破单元格 */
.signal-table :deep(.wrap-tag) {
  height: auto;
  min-height: 24px;
  padding: 3px 8px;
  line-height: 1.5;
  white-space: normal;
  text-align: left;
}
.signal-table :deep(.tag-dim) {
  opacity: 0.6;
}
</style>
