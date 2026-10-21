/** invest-platform /api/mp/* 的 API 封装 */
import { request } from './client'
import type { HoldingDetail, Overview, PullStatus, ReportJobStatus, Signal, TradesPayload } from '@/types'

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

export function getSignals(): Promise<{ signals: Signal[] }> {
  return request({ url: '/signals' })
}

export function setSignalStatus(id: number, status: '已确认' | '已忽略' | '建议'): Promise<{ ok: boolean }> {
  return request({ url: `/signals/${id}/status`, method: 'POST', data: { status } })
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
