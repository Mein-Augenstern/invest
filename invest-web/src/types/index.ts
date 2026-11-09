/**
 * 与 invest-platform /api/invest/* 的返回结构一一对应（契约见 docs/tech/backend/api-contract.md）。
 * 前半部分搬运自 invest-miniapp/src/types/index.ts（口径同源）；后半部分为 PC 端全量页面补齐的响应类型。
 * 数值口径：xirr / unrealized_pct / drawdown_5y 为小数（×100 展示）；pct_5y / pct_all 已是百分数。
 */

export type InstrumentType = 'etf' | 'open_end_fund' | 'stock' | 'bond' | 'wealth'

export interface Position {
  id: string
  name: string
  account: string
  type: InstrumentType
  type_label: string
  state: 'full' | 'noprice' | 'empty'
  quantity: number
  price: number | null
  price_date: string
  avg_cost: number | null
  market_value: number | null
  unrealized: number | null
  unrealized_pct: number | null
  realized_pnl: number | null
  cash_dividend: number | null
  xirr: number | null
  xirr_error: boolean
}

export interface PositionGroup {
  type: InstrumentType
  label: string
  market_value: number | null
  positions: Position[]
}

export interface Benchmark {
  name: string
  code: string | null
  close: number | null
  pe_ttm: number | null
  pct_5y: number | null
  pct_all: number | null
  dyield: number | null
  drawdown_5y: number | null
}

export interface Signal {
  id: number
  date: string
  instrument: string
  rule: string
  metric: string
  value: string
  action: string
  status: string
}

export interface Overview {
  date: string
  config_source: string
  is_example: boolean
  /** S09：任一行情序列超过 6 小时未更新（S10 AC-5 消费） */
  data_stale?: boolean
  totals: {
    market_value: number | null
    unrealized: number | null
    xirr: number | null
  }
  pension_progress: {
    instrument_id: string
    name: string
    year: string
    contributed: number
    cap: number
  } | null
  groups: PositionGroup[]
  benchmarks: Benchmark[]
  signals: Signal[]
}

export interface ReportJobStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  started: string | null
  finished: string | null
  file: string
  log: string[]
}

export interface TradeRow {
  date: string
  instrument_id: string
  action: string
  action_label: string
  quantity: number
  price: number
  fee: number
  note: string
}

export interface InstrumentBrief {
  id: string
  name: string
  type: InstrumentType
  price: number | null
  price_label: string
}

export interface TradesPayload {
  trades: TradeRow[]
  instruments: InstrumentBrief[]
  actions: string[]
}

export interface PullStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  started: string | null
  finished: string | null
  log: string[]
}

export interface TradeEvent {
  ts: number
  label: string
  kind: string
}

export interface HoldingDetail {
  id: string
  name: string
  code: string
  type: InstrumentType
  account_name: string
  row: Position
  nav_series: [number, number][]
  nav_start?: string
  pe_series: [number, number][]
  benchmark: Benchmark | null
  events: TradeEvent[]
  signals: Signal[]
  lookthrough?: {
    period: string
    holdings: { rank: number; code: string; name: string; weight_pct: number }[]
    industry: { name: string; weight_pct: number }[]
    industry_total_pct: number
  }
  /** 行情源超时降级返回缓存时为 true（S05） */
  stale?: boolean
  performance?: InstrumentPerformance
  profile?: InstrumentProfile
}

export const ACTION_LABELS: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  contribute: '缴存',
  dividend_cash: '现金分红',
  dividend_reinvest: '红利再投资',
  adjust: '份额校准',
}

/* ---------------- PC 端全量页面补齐的响应类型 ---------------- */

/** POST /trades 请求体 */
export interface NewTrade {
  instrument_id: string
  action: string
  date: string
  quantity: number
  price: number
  fee?: number
  note?: string
}

/** GET /summary：months 为月度行，years 为年度行（带 year 字段） */
export interface SummaryRow {
  month: string
  market_value: number
  net_invested: number
  invested: number
  returned: number
  cash_div: number
  realized: number
  pnl_change: number
}

export interface SummaryYearRow {
  year: string
  net_invested: number
  pnl_change: number
  cash_div: number
  realized: number
  market_value: number
}

export interface SummaryPayload {
  months: SummaryRow[]
  years: SummaryYearRow[]
}

/** GET /asset-curve */
export interface AssetCurve {
  curve: [number, number][]
  start: string
  end: string
}

/** GET /daily-pnl?month=YYYY-MM */
export interface DailyPnl {
  days: Record<string, number>
  month_total: number
}

/** GET /annual-report?year=YYYY */
export interface AnnualReport {
  year: string
  empty: boolean
  net_invested: number
  invested: number
  returned: number
  pnl_change: number
  realized: number
  account_cash: number
  cash_div: number
  year_end_mv: number
  months_count: number
  win_months: number
  best_month: { month: string; pnl_change: number }
  worst_month: { month: string; pnl_change: number }
  monthly: { month: string; pnl_change: number; net_invested: number }[]
}

/** POST /backtest */
export interface BacktestResult {
  code: string
  name: string
  params: string
  metrics: Record<string, string | number | null>
  curve: [number, number][]
}

export interface BacktestPayload {
  ok: boolean
  span: string
  results: BacktestResult[]
}

/** GET /valuation */
export interface ValuationRow {
  name: string
  code: string
  close: number | null
  pe: number | null
  pct_5y: number | null
  pct_all: number | null
  dyield: number | null
  ready: boolean
}

export interface ValuationPayload {
  indexes: ValuationRow[]
  temperature: number | null
}

/** GET /diary */
export interface DiaryEntry {
  date: string
  content: string
  mood: string
}

/** GET /instruments */
export interface InstrumentRow {
  id: string
  name: string
  type: string
  code: string
  benchmark_index: string
  account: string
  held_qty: number
  from_db: boolean
}

/** POST /instruments 请求体（新增或更新） */
export interface InstrumentForm {
  id: string
  name: string
  type: string
  code: string
  benchmark_index?: string
  account?: string
}

/** GET /report/latest：无周报时 report 为 null */
export type LatestReport = { report: null } | { file: string; markdown: string }

/** POST /ocr：trades 为 null 表示 AI 结构化未成功，仅返回原文 */
export interface OcrDraft {
  date: string
  action: string
  instrument_id: string
  quantity: number | string
  price: number | string
  fee: number | string
  note: string
}

export interface OcrResult {
  text: string
  trades: OcrDraft[] | null
  ai_parsed: boolean
}

/** GET /backup/info */
export interface BackupInfo {
  trades_count: number
  data_dir: string
  files: string[]
  exportable: boolean
}

/** GET /health/data（S04） */
export interface DataHealth {
  files: Record<
    string,
    { total_rows?: number; valid_rows?: number; corrupted_rows?: number; size_bytes?: number; last_modified: string }
  >
  healthy: boolean
}

/** 标的业绩表现（后端 _compute_performance） */
export interface InstrumentPerformance {
  returns: Record<string, number | null>
  volatility: number | null
  max_drawdown: number | null
  trend: string
}

/** 标的概况卡（后端 _instrument_profile） */
export interface InstrumentProfile {
  title: string
  type_label: string
  code: string
  account: string
  fields: { label: string; value: string }[]
}
