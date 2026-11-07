"""资金加权收益率（XIRR）：含现金流时点，反映真实投资体验。"""
from __future__ import annotations

from datetime import datetime


def _parse(d: str) -> datetime:
    return datetime.strptime(d, "%Y-%m-%d")


def _year_frac(d0: datetime, d: datetime) -> float:
    return (d - d0).days / 365.0


#: 年化合理性封顶：超出 ±1000% 视为数学发散（小额现金流 × 短持有期 × 大幅盈亏
#: 的组合会产生天文数字"解"，如 1000 元几天涨到 7788 → 年化 +1 万亿%）——
#: 展示层不该给用户看这种数字，抛错让调用方降级为 xirr_error/None。
XIRR_PLAUSIBLE_CAP = 10.0


def _ensure_plausible(rate: float) -> None:
    if abs(rate) > XIRR_PLAUSIBLE_CAP:
        raise ValueError(
            f"XIRR 年化超出可参考范围（±1000%）：持有期过短或现金流异常（{rate:.2%}）"
        )


def xirr(cashflows: list[tuple[str, float]], value_date: str, current_value: float) -> float:
    """解 r 使 Σ cf_i / (1+r)^t_i = 0，t_i 为年化期限。

    cashflows: [(日期, 金额)]，负=投入 正=回收；
    current_value: value_date 时点的市值（作为期末正流入参与求解）。
    收敛结果超出 ±1000% 时抛 ValueError（调用方统一降级为 xirr_error/None）。
    """
    if not cashflows:
        raise ValueError("现金流为空，无法计算 XIRR")
    d0 = _parse(min(d for d, _ in cashflows + [(value_date, 0.0)]))
    flows = [(_parse(d), a) for d, a in cashflows]
    flows.append((_parse(value_date), current_value))

    def npv(rate: float) -> float:
        if rate <= -1.0:
            return float("inf")
        return sum(a / (1 + rate) ** _year_frac(d0, d) for d, a in flows)

    def dnpv(rate: float) -> float:
        return sum(
            -a * _year_frac(d0, d) / (1 + rate) ** (_year_frac(d0, d) + 1) for d, a in flows
        )

    # 牛顿迭代
    rate = 0.1
    for _ in range(100):
        v, dv = npv(rate), dnpv(rate)
        if abs(dv) < 1e-12:
            break
        new_rate = rate - v / dv
        if new_rate <= -1.0:
            new_rate = (rate - 1.0) / 2  # 防跨出定义域
        if abs(new_rate - rate) < 1e-10:
            _ensure_plausible(new_rate)
            return new_rate
        rate = new_rate

    # 兜底：二分（在合理区间内找符号变化）
    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        raise ValueError("XIRR 未收敛：现金流无解或超出区间 [-99.9%, 1000%]")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-9:
            _ensure_plausible(mid)
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    _ensure_plausible((lo + hi) / 2)
    return (lo + hi) / 2
