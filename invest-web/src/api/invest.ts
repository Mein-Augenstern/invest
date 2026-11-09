/**
 * invest-platform /api/invest/* 全量封装（PC 端 13 屏共用；端点清单见 docs/tech/backend/api-contract.md）。
 * 页面层只调用本文件导出的函数，不直接拼 URL。
 */
import { download, request, upload } from './client'
import type {
  AnnualReport,
  AssetCurve,
  BacktestPayload,
  BackupInfo,
  DailyPnl,
  DataHealth,
  DiaryEntry,
  HoldingDetail,
  InstrumentForm,
  InstrumentRow,
  LatestReport,
  NewTrade,
  OcrResult,
  Overview,
  PullStatus,
  ReportJobStatus,
  Signal,
  SummaryPayload,
  TradesPayload,
  ValuationPayload,
} from '@/types'

type Ok = { ok: boolean }

/* ---------- 总览 / 拉数 ---------- */

export function getOverview(): Promise<Overview> {
  return request({ url: '/overview' })
}

export function startPull(): Promise<Ok> {
  return request({ url: '/pull', method: 'POST' })
}

export function getPullStatus(): Promise<PullStatus> {
  return request({ url: '/pull/status' })
}

/* ---------- 流水 ---------- */

export function getTrades(instrumentId?: string, limit = 500): Promise<TradesPayload> {
  return request({ url: '/trades', params: { instrument_id: instrumentId, limit } })
}

export function addTrade(payload: NewTrade): Promise<Ok & { trade: Record<string, string> }> {
  return request({ url: '/trades', method: 'POST', data: payload })
}

/** 流水无 id：按整行匹配删除（后端对数值列做容差比较，传原始行即可） */
export function deleteTrade(row: Record<string, string | number>): Promise<Ok> {
  return request({ url: '/trades/delete', method: 'POST', data: { row } })
}

/** 智能录入 v1：一句话 → 流水草稿（不落库，确认走 addTrade） */
export function parseTradeText(text: string): Promise<{
  draft: Partial<NewTrade> | null
  instrument: { id: string; name: string } | null
  candidates: { id: string; name: string }[]
  missing: string[]
  explanation: string
}> {
  return request({ url: '/trades/parse', method: 'POST', data: { text }, timeoutMs: 15_000 })
}

/* ---------- 标的详情 / 手工净值 ---------- */

export function getInstrumentDetail(id: string): Promise<HoldingDetail> {
  return request({ url: `/instrument/${encodeURIComponent(id)}` })
}

export function addNav(payload: { instrument_id: string; date: string; value: number }): Promise<Ok> {
  return request({ url: '/nav', method: 'POST', data: payload })
}

/* ---------- 统计 / 年度 ---------- */

export function getSummary(months = 12): Promise<SummaryPayload> {
  return request({ url: '/summary', params: { months } })
}

export function getAssetCurve(days = 365): Promise<AssetCurve> {
  return request({ url: '/asset-curve', params: { days } })
}

export function getDailyPnl(month: string): Promise<DailyPnl> {
  return request({ url: '/daily-pnl', params: { month } })
}

export function getAnnualReport(year: string): Promise<AnnualReport> {
  return request({ url: '/annual-report', params: { year } })
}

/* ---------- 信号（仅用已挂载端点：/signals、/signals/evaluate、/signals/{id}/status） ---------- */

export function getSignals(): Promise<{ signals: Signal[] }> {
  return request({ url: '/signals' })
}

export function evaluateSignals(): Promise<Ok & { new: number[] | number }> {
  return request({ url: '/signals/evaluate', method: 'POST', timeoutMs: 60_000 })
}

export function setSignalStatus(id: number, status: '已确认' | '已忽略' | '建议'): Promise<Ok> {
  return request({ url: `/signals/${id}/status`, method: 'POST', data: { status } })
}

/* ---------- 回测 ---------- */

export function runBacktest(payload: { start: string; monthly: number; drag?: number }): Promise<BacktestPayload> {
  return request({ url: '/backtest', method: 'POST', data: payload, timeoutMs: 120_000 })
}

/* ---------- 周报 ---------- */

export function getLatestReport(): Promise<LatestReport> {
  return request({ url: '/report/latest' })
}

export function generateReport(ai: boolean): Promise<Ok> {
  return request({ url: '/reports/generate', method: 'POST', data: { ai } })
}

export function getReportStatus(): Promise<ReportJobStatus> {
  return request({ url: '/reports/status' })
}

/* ---------- 估值 ---------- */

export function getValuation(): Promise<ValuationPayload> {
  return request({ url: '/valuation' })
}

/* ---------- 日记 ---------- */

export function getDiary(): Promise<{ entries: DiaryEntry[] }> {
  return request({ url: '/diary' })
}

export function saveDiary(entry: DiaryEntry): Promise<Ok> {
  return request({ url: '/diary', method: 'POST', data: entry })
}

export function deleteDiary(date: string): Promise<Ok> {
  return request({ url: '/diary/delete', method: 'POST', data: { date } })
}

/* ---------- 标的管理 ---------- */

export function getInstruments(): Promise<{ instruments: InstrumentRow[] }> {
  return request({ url: '/instruments' })
}

export function saveInstrument(form: InstrumentForm): Promise<Ok & { id: string }> {
  return request({ url: '/instruments', method: 'POST', data: form })
}

/** 409=仍有持仓不可删；404=YAML 种子标的不可删 */
export function deleteInstrument(id: string): Promise<Ok> {
  return request({ url: '/instruments/delete', method: 'POST', data: { id } })
}

/** 截图 → OCR → 标的草稿（依赖 macOS Vision；Linux 部署返回 422 语义错误，S10 AC-6） */
export function parseInstrumentImage(file: File): Promise<{ text: string; instrument: Partial<InstrumentForm> | null; ai_parsed: boolean }> {
  return upload('/instruments/parse-image', file)
}

/** S12 策略库：按品类获取模板 */
export function getStrategyTemplates(type: string): Promise<{
  templates: { id: string; name: string; desc: string; params: { key: string; label: string; type: string; default?: number | string; unit?: string; options?: string[]; placeholder?: string }[]; types: string[]; bound?: boolean }[]
}> {
  return request({ url: '/strategies/templates', params: { type } })
}

/** S12 策略库：评估当前建议 */
export function evaluateStrategy(payload: { template_id: string; instrument_id: string; params?: Record<string, unknown> }): Promise<{
  ok: boolean
  template: string
  instrument: string
  action: string
  detail: string
  severity: string
}> {
  return request({ url: '/strategies/evaluate', method: 'POST', data: payload })
}

/** 搜索标的目录（基金/ETF/股票 + 中证指数）→ 一键加入 */
export function searchInstrumentCatalog(q: string): Promise<{
  results: { code: string; name: string; full_name: string; itype: string; suggested_type: string; benchmark_index: string; already_added: boolean }[]
}> {
  return request({ url: '/instruments/catalog', params: { q } })
}

/* ---------- 截图识别 ---------- */

export function ocrTrades(file: File): Promise<OcrResult> {
  return upload('/ocr', file)
}

/* ---------- 设置：GLM key / 备份 / 数据健康 ---------- */

export function getGlmKeyStatus(): Promise<{ configured: boolean }> {
  return request({ url: '/settings/glm-key' })
}

export function saveGlmKey(key: string): Promise<Ok & { configured: boolean }> {
  return request({ url: '/settings/glm-key', method: 'POST', data: { key } })
}

export function getBackupInfo(): Promise<BackupInfo> {
  return request({ url: '/backup/info' })
}

export function downloadBackup(): Promise<void> {
  return download('/backup/export', 'invest-backup.zip')
}

export function getDataHealth(): Promise<DataHealth> {
  return request({ url: '/health/data' })
}
