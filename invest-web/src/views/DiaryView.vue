<!--
  投资日记（对齐小程序 diary）：按日倒序卡片流 · 写/编辑弹窗（日期 + 心情单选 + 正文）· 删除确认。
  后端按日 upsert：同一天只有一篇，新写撞日期时仅提示会覆盖，不拦截。
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { EditPen } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StateBlock from '@/components/StateBlock.vue'
import { ApiError, errMsg } from '@/api/client'
import { deleteDiary, getDiary, saveDiary } from '@/api/invest'
import type { DiaryEntry } from '@/types'
import { localDate } from '@/utils/format'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

/** 心情五标签：与小程序 diary.vue 的 MOODS、后端 POST /diary 白名单逐字一致；可不选（空串） */
const MOODS = ['平静', '贪婪', '恐惧', '犹豫', '坚定']

/** 列表着色沿用小程序 MOOD_CLASS：贪婪=红、恐惧=绿、坚定=主色，其余中性 */
const MOOD_TAG: Record<string, TagType> = { 贪婪: 'danger', 恐惧: 'success', 坚定: 'primary' }
const moodType = (mood: string): TagType => MOOD_TAG[mood] || 'info'

/** 正文上限与小程序 textarea 一致（后端不限长）：两端共用数据，PC 更短会让手机写的长日记在这里超限 */
const CONTENT_MAX = 1000

const entries = ref<DiaryEntry[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await getDiary()
    entries.value = res.entries
  } catch (e) {
    error.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

/** 倒序：日期新→旧（YYYY-MM-DD 字典序即时间序） */
const sorted = computed(() => [...entries.value].sort((a, b) => b.date.localeCompare(a.date)))
const existingDates = computed(() => new Set(entries.value.map((e) => e.date)))

/* ---------- 写 / 编辑 ---------- */

const dialog = ref(false)
const editing = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive<DiaryEntry>({ date: localDate(), mood: '', content: '' })

const rules: FormRules = {
  date: [{ required: true, message: '请选择日期', trigger: 'change' }],
  content: [{ required: true, whitespace: true, message: '写点什么吧', trigger: 'blur' }],
}

/** 新写时日期已有日记：后端 upsert 会覆盖原文，给提示但不拦截 */
const willOverwrite = computed(() => !editing.value && existingDates.value.has(form.date))

/** 编辑时日期锁定：按日 upsert 下改日期等于「另存一篇（可能覆盖目标日）」而非移动，易误伤 */
function openDialog(entry?: DiaryEntry) {
  editing.value = !!entry
  Object.assign(form, entry ? { date: entry.date, mood: entry.mood || '', content: entry.content } : { date: localDate(), mood: '', content: '' })
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}

/** 单选，再点一次取消（心情可空） */
function toggleMood(mood: string) {
  form.mood = form.mood === mood ? '' : mood
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    await saveDiary({ date: form.date, mood: form.mood, content: form.content.trim() })
    ElMessage.success(editing.value ? '已更新' : '已记录')
    dialog.value = false
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

/* ---------- 删除 ---------- */

async function remove(entry: DiaryEntry) {
  try {
    await ElMessageBox.confirm(`删除 ${entry.date} 的日记？删除后不可恢复。`, '删除日记', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return // 取消 / 关闭
  }
  try {
    await deleteDiary(entry.date)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(errMsg(e))
    if (e instanceof ApiError && e.status === 404) load() // 该日日记已不存在：列表过期，刷新
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="投资日记" desc="记录当日的判断与情绪——复盘是把情绪变成纪律的唯一路径">
    <template #actions>
      <el-button type="primary" :icon="EditPen" @click="openDialog()">写日记</el-button>
    </template>
  </PageHeader>

  <div class="panel">
    <StateBlock
      :loading="loading"
      :error="error"
      :empty="!entries.length"
      :has-data="!!entries.length"
      empty-text="还没有日记。任何一天都值得记一笔。"
      @retry="load"
    >
      <template #empty-action>
        <el-button type="primary" @click="openDialog()">写日记</el-button>
      </template>

      <div class="entries">
        <article v-for="e in sorted" :key="e.date" class="entry">
          <header class="entry-head">
            <span class="entry-date num">{{ e.date }}</span>
            <el-tag v-if="e.mood" :type="moodType(e.mood)" size="small" effect="light">{{ e.mood }}</el-tag>
            <span class="entry-ops">
              <el-button link type="primary" @click="openDialog(e)">编辑</el-button>
              <el-button link type="danger" @click="remove(e)">删除</el-button>
            </span>
          </header>
          <div class="entry-content">{{ e.content }}</div>
        </article>
      </div>
    </StateBlock>
  </div>

  <el-dialog v-model="dialog" :title="editing ? '编辑日记' : '写日记'" width="620px" :close-on-click-modal="false">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="64px">
      <el-form-item label="日期" prop="date">
        <el-date-picker
          v-model="form.date"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          :disabled="editing"
          style="width: 200px"
        />
        <span v-if="willOverwrite" class="overwrite-hint">该日已有日记，保存将覆盖原内容</span>
      </el-form-item>
      <el-form-item label="心情">
        <div class="moods">
          <el-check-tag v-for="m in MOODS" :key="m" type="primary" :checked="form.mood === m" @change="toggleMood(m)">
            {{ m }}
          </el-check-tag>
          <span class="muted mood-hint">可不选，再点一次取消</span>
        </div>
      </el-form-item>
      <el-form-item label="内容" prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="8"
          :maxlength="CONTENT_MAX"
          show-word-limit
          placeholder="今天的判断、操作、情绪…"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.entry {
  padding: 16px 0;
  border-bottom: 1px solid var(--iv-border);
}
.entry:first-child {
  padding-top: 0;
}
.entry:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.entry-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.entry-date {
  font-size: 15px;
  font-weight: 600;
}
.entry-ops {
  margin-left: auto;
}
.entry-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.8;
  color: var(--iv-text);
}
.overwrite-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--iv-warn);
}
.moods {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.mood-hint {
  font-size: 12px;
  margin-left: 4px;
}
</style>
