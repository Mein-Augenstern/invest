/** 展示格式化：千分位金额、百分比、盈亏着色口径（红涨绿跌，A股习惯） */

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

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = (Math.abs(v) * 100).toFixed(digits)
  if (v > 0) return `+${s}%`
  if (v < 0) return `-${s}%`
  return `${s}%`
}

export function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return ''
  return v > 0 ? 'danger' : 'success' // 红涨绿跌
}

export function fmtQty(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
