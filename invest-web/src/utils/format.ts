/** 展示格式化：千分位金额、百分比、盈亏着色口径（红涨绿跌，A股习惯）——搬运自 invest-miniapp，口径同源 */

export function fmtAmount(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = fmtAmount(Math.abs(v), digits)
  if (v > 0) return `+${s}`
  if (v < 0) return `-${s}`
  return s
}

/** 小数口径百分比（xirr / unrealized_pct / drawdown_5y）：×100 并带符号 */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = (Math.abs(v) * 100).toFixed(digits)
  if (v > 0) return `+${s}%`
  if (v < 0) return `-${s}%`
  return `${s}%`
}

/** 已是百分数的口径（pct_5y / pct_all / weight_pct）：不再 ×100 */
export function fmtPlainPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)}%`
}

export function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return ''
  return v > 0 ? 'danger' : 'success' // 红涨绿跌
}

export function fmtQty(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

/** 本地日期 YYYY-MM-DD（toISOString 是 UTC，北京时间 08:00 前会差一天） */
export function localDate(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 毫秒时间戳 → 本地 YYYY-MM-DD */
export function fmtTs(ms: number): string {
  return localDate(new Date(ms))
}
