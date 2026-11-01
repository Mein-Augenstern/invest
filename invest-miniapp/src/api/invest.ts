/** invest-platform /api/mp/* 的 API 封装 */
import { ApiError, request } from './client'
import type { HoldingDetail, Overview, PullStatus, ReportJobStatus, TradesPayload } from '@/types'

export function ping(): Promise<{ ok: boolean; service: string }> {
  return request({ url: '/ping' })
}

export function getOverview(): Promise<Overview> {
  return request({ url: '/overview' })
}

export function getTrades(instrumentId?: string, limit = 100): Promise<TradesPayload> {
  return request({
    url: '/trades',
    params: instrumentId ? { instrument_id: instrumentId, limit } : { limit },
  })
}

export function addTrade(payload: {
  instrument_id: string
  action: string
  date: string
  quantity: number
  price: number
  fee?: number
  note?: string
}): Promise<{ ok: boolean; trade: Record<string, string> }> {
  return request({ url: '/trades', method: 'POST', data: payload })
}

export function deleteTrade(row: Record<string, string | number>): Promise<{ ok: boolean }> {
  return request({ url: '/trades/delete', method: 'POST', data: { row } })
}

/* ---------- S02 策略引擎：信号 v2（综合信号 + 规则明细 + 纸面交易） ---------- */

/** 策略规则（strategy.yaml 中的定义，results 内为命中时点的快照） */
export interface StrategyRuleInfo {
  id: string
  name: string
  signal?: string // 该规则单独投票的方向 buy/hold/sell/rebalance
  weight?: number
  note?: string
}

/** 单条规则对某个标的的评估结果 */
export interface SignalRuleResult {
  rule: StrategyRuleInfo
  triggered: boolean
  metric_value?: number | string | null
  description?: string
}

/**
 * 信号（S02 富格式）。旧后端（S02 上线前）仍返回 id/date/instrument/rule/metric/value/action/status
 * 平铺结构，这些字段以可选形式保留，页面层做兼容渲染。
 */
export interface SignalItem {
  id: string | number
  instrument_id?: string
  instrument_name?: string
  final_signal?: 'buy' | 'hold' | 'sell' | 'rebalance' | string
  confidence?: number // 0~1
  status?: string
  date?: string
  results?: SignalRuleResult[]
  summary?: string
  /* 旧版字段（S02 前） */
  instrument?: string
  rule?: string
  metric?: string
  value?: string
  action?: string
}

/** 纸面交易（信号确认后自动开启的虚拟仓位，非真实交易） */
export interface PaperTrade {
  id: string | number
  signal_id?: string | number
  instrument_id?: string
  instrument_name: string
  action: string
  quantity: number
  price_at_signal: number
  status: 'open' | 'closed' | 'expired' | string
  return_pct?: number | null // 小数（0.038 = +3.8%），open 为浮盈、closed 为最终收益
  created_at?: string
  closed_at?: string
  close_price?: number | null
}

export interface SignalsPayload {
  signals: SignalItem[]
  paper_trades?: PaperTrade[]
}

export function getSignals(): Promise<SignalsPayload> {
  return request({ url: '/signals' })
}

export function setSignalStatus(id: number | string, status: '已确认' | '已忽略' | '建议'): Promise<{ ok: boolean }> {
  return request({ url: `/signals/${id}/status`, method: 'POST', data: { status } })
}

/** 确认信号 → 自动开纸面交易（S02 契约）。后端 S02 未上线（404）时回退旧状态接口，保持可用。 */
export async function confirmSignal(id: number | string): Promise<{ ok: boolean }> {
  try {
    return await request({ url: `/signals/${id}/confirm`, method: 'POST' })
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return setSignalStatus(id, '已确认')
    throw e
  }
}

/** 忽略信号（S02 契约）。后端 S02 未上线（404）时回退旧状态接口，保持可用。 */
export async function ignoreSignal(id: number | string): Promise<{ ok: boolean }> {
  try {
    return await request({ url: `/signals/${id}/ignore`, method: 'POST' })
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return setSignalStatus(id, '已忽略')
    throw e
  }
}

/** 历史信号（含已关闭纸面交易的最终收益） */
export function getSignalHistory(): Promise<SignalsPayload> {
  return request({ url: '/signals/history' })
}

export function startPull(): Promise<{ ok: boolean }> {
  return request({ url: '/pull', method: 'POST' })
}

export function getPullStatus(): Promise<PullStatus> {
  return request({ url: '/pull/status' })
}

export function getInstrumentDetail(id: string): Promise<HoldingDetail> {
  return request({ url: `/instrument/${encodeURIComponent(id)}` })
}

export function addNav(payload: { instrument_id: string; date: string; value: number }): Promise<{ ok: boolean }> {
  return request({ url: '/nav', method: 'POST', data: payload })
}

export function getLatestReport(): Promise<{ report: null } | { file: string; markdown: string }> {
  return request({ url: '/report/latest' })
}

export function generateReport(ai: boolean): Promise<{ ok: boolean }> {
  return request({ url: '/reports/generate', method: 'POST', data: { ai } })
}

export function getReportStatus(): Promise<ReportJobStatus> {
  return request({ url: '/reports/status' })
}

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

export function getSummary(months = 12): Promise<{ months: SummaryRow[]; years: SummaryRow[] }> {
  return request({ url: '/summary', params: { months } })
}
