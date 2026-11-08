/** S10 AC-3：数值口径——xirr/unrealized_pct 小数×100；pct_5y 已是百分数；红涨绿跌；空值 — */
import { describe, expect, it } from 'vitest'
import { fmtAmount, fmtPlainPct, fmtPct, fmtQty, fmtSigned, localDate, pnlClass } from '@/utils/format'

describe('fmtPct（小数口径）', () => {
  it('0.1234 → +12.34%', () => expect(fmtPct(0.1234)).toBe('+12.34%'))
  it('-0.05 → -5.00%', () => expect(fmtPct(-0.05)).toBe('-5.00%'))
  it('0 → 0.00%（无符号）', () => expect(fmtPct(0)).toBe('0.00%'))
  it('null / undefined / NaN → —', () => {
    expect(fmtPct(null)).toBe('—')
    expect(fmtPct(undefined)).toBe('—')
    expect(fmtPct(Number.NaN)).toBe('—')
  })
})

describe('fmtPlainPct（已是百分数口径：pct_5y / weight_pct）', () => {
  it('37.5 → 37.5%（不再 ×100）', () => expect(fmtPlainPct(37.5)).toBe('37.5%'))
  it('保留 0 位用于分位显示', () => expect(fmtPlainPct(42.6, 0)).toBe('43%'))
})

describe('红涨绿跌（A 股口径）', () => {
  it('盈利 → danger（红）', () => expect(pnlClass(123)).toBe('danger'))
  it('亏损 → success（绿）', () => expect(pnlClass(-1)).toBe('success'))
  it('0 / null → 不着色', () => {
    expect(pnlClass(0)).toBe('')
    expect(pnlClass(null)).toBe('')
  })
})

describe('金额与份额', () => {
  it('千分位', () => expect(fmtAmount(7788)).toBe('7,788.00'))
  it('带符号', () => {
    expect(fmtSigned(2288)).toBe('+2,288.00')
    expect(fmtSigned(-541.63)).toBe('-541.63')
  })
  it('份额最多 4 位小数', () => expect(fmtQty(11000)).toBe('11,000'))
  it('空值 → —', () => expect(fmtAmount(null)).toBe('—'))
})

describe('localDate（UTC 边界）', () => {
  it('北京时间 00:30 仍是当天（toISOString 会差一天）', () => {
    // 2026-11-08T00:30 北京 = 2026-11-07T16:30 UTC
    const d = new Date('2026-11-08T00:30:00+08:00')
    expect(localDate(d)).toBe('2026-11-08')
  })
})
