/** 与 invest-platform /api/invest/* 的返回结构一一对应（见 docs/tech/backend/api-contract.md 契约） */

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
}

export const ACTION_LABELS: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  contribute: '缴存',
  dividend_cash: '现金分红',
  dividend_reinvest: '红利再投资',
  adjust: '份额校准',
}
