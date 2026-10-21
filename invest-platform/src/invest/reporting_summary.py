"""月度收益统计视图（L2）：组合市值时序推演 → 月度盈亏聚合。

口径（诚实优先）：
- 逐日组合市值：每标的 当日持仓份额（流水 as-of）× 当日净值/行情（series as-of，缺失前值沿用）；
- 当月净投入 = 当月 buy+contribute 现金流出 − sell+dividend_cash 现金流入（流水口径，精确）；
- 当月浮盈变化 = 月末市值 − 月初市值 − 当月净投入（对账恒等式：Δ市值 = 净投入 + 浮盈变化）；
- 已实现盈亏与现金分红单列（不混入浮盈）。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .config import Portfolio, series_kind
from .data.local import LocalStore
from .ledger.ledger import Position, build_positions
from .ledger.trades import Trade


def _month_of(d: str) -> str:
    return d[:7]


def build_daily_mv_series(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> dict[str, float]:
    """逐日组合市值（date→市值），口径与月度统计完全一致：份额 as-of 流水 × 净值 as-of 前值沿用。

    R3 资产总曲线的单一数据源（与月度聚合同源，杜绝两套口径）。
    """
    if not trades:
        return {}
    return _compute_mv(conf, store, trades)


def _compute_mv(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> dict[str, float]:
    """逐日组合市值推演（build_monthly_summary 的推演核心，抽出复用）。"""
    nav: dict[str, pd.Series] = {}
    for ins in conf.instruments:
        key = ins.code or ins.id
        df = store.read_series(key, series_kind(ins.type))
        if not df.empty:
            nav[ins.id] = df.set_index("date")["close"]
    all_dates = sorted(set().union(*[set(df.index) for df in nav.values()])) if nav else []
    if not all_dates:
        return {}
    events: dict[str, dict[str, float]] = {}
    for t in trades:
        if t.action == "contribute":
            continue
        delta = t.quantity if t.action in ("buy", "dividend_reinvest", "adjust") else -t.quantity
        events.setdefault(t.date, {}).setdefault(t.instrument_id, 0.0)
        events[t.date][t.instrument_id] += delta
    holdings: dict[str, float] = {i.id: 0.0 for i in conf.instruments}
    mv_by_date: dict[str, float] = {}
    nav_ptr = {i.id: None for i in conf.instruments}
    di = 0
    for d in sorted(set(all_dates) | set(events.keys())):
        if d in events:
            for iid, delta in events[d].items():
                holdings[iid] = holdings.get(iid, 0.0) + delta
        while di < len(all_dates) and all_dates[di] <= d:
            for iid, series_ in nav.items():
                if all_dates[di] in series_.index:
                    nav_ptr[iid] = float(series_.loc[all_dates[di]])
            di += 1
        mv_by_date[d] = sum(
            holdings.get(iid, 0.0) * (nav_ptr[iid] or 0.0)
            for iid in nav
            if nav_ptr[iid] is not None
        )
    return mv_by_date


def build_monthly_summary(
    conf: Portfolio, store: LocalStore, trades: list[Trade], months: int = 12
) -> dict[str, Any]:
    """近 N 个月的月度投入/市值/浮盈变化 + 年度汇总。"""
    if not trades:
        return {"months": [], "years": []}

    # 每标的：净值序列（as-of 前值沿用）+ 逐笔份额变化
    nav: dict[str, pd.DataFrame] = {}
    for ins in conf.instruments:
        key = ins.code or ins.id
        df = store.read_series(key, series_kind(ins.type))
        if not df.empty:
            nav[ins.id] = df.set_index("date")["close"]

    all_dates = sorted(set().union(*[set(df.index) for df in nav.values()])) if nav else []
    if not all_dates:
        return {"months": [], "years": []}

    # 逐笔份额事件：date → instrument → Δ份额
    # contribute=账户入金（缴存），不折基金份额，只进现金流；故跳过份额推演
    events: dict[str, dict[str, float]] = {}
    for t in trades:
        if t.action == "contribute":
            continue
        delta = t.quantity if t.action in ("buy", "dividend_reinvest", "adjust") else -t.quantity
        events.setdefault(t.date, {}).setdefault(t.instrument_id, 0.0)
        events[t.date][t.instrument_id] += delta

    # 日度组合市值（持仓份额 as-of 流水 × 净值 as-of 序列）
    holdings: dict[str, float] = {i.id: 0.0 for i in conf.instruments}
    mv_by_date: dict[str, float] = {}
    nav_ptr = {i.id: None for i in conf.instruments}
    di = 0
    dates_sorted = sorted(set(all_dates) | set(events.keys()))
    for d in dates_sorted:
        if d in events:
            for iid, delta in events[d].items():
                holdings[iid] = holdings.get(iid, 0.0) + delta
        while di < len(all_dates) and all_dates[di] <= d:
            for iid, series_ in nav.items():
                if all_dates[di] in series_.index:
                    nav_ptr[iid] = float(series_.loc[all_dates[di]])
            di += 1
        mv_by_date[d] = sum(
            holdings.get(iid, 0.0) * (nav_ptr[iid] or 0.0)
            for iid in nav
            if nav_ptr[iid] is not None
        )

    # 月度现金流（精确，来自流水）
    flows: dict[str, dict[str, float]] = {}
    for t in trades:
        m = _month_of(t.date)
        f = flows.setdefault(m, {"invested": 0.0, "returned": 0.0, "realized": 0.0, "cash_div": 0.0})
        amount = t.quantity * t.price
        if t.action in ("buy", "contribute"):
            f["invested"] += amount + t.fee
        elif t.action in ("sell",):
            f["returned"] += amount - t.fee
        elif t.action == "dividend_cash":
            f["cash_div"] += amount

    # 已实现盈亏（按月分摊：重放 Position.apply 取每月 realized_pnl 增量）
    pos_cost: dict[str, Position] = {}
    realized_by_month: dict[str, float] = {}
    prev_realized_total = 0.0
    for t in sorted(trades, key=lambda x: x.date):
        m = _month_of(t.date)
        pos = pos_cost.setdefault(t.instrument_id, Position(instrument_id=t.instrument_id))
        pos.apply(t)
        delta = pos.realized_pnl - prev_realized_total
        if abs(delta) > 1e-9:
            realized_by_month[m] = realized_by_month.get(m, 0.0) + delta
        prev_realized_total = pos.realized_pnl

    # 月度聚合：月初市值（上月末）/月末市值/净投入/浮盈变化
    month_ends: dict[str, str] = {}
    for d in mv_by_date:
        month_ends[_month_of(d)] = d  # 每月最后一个有市值的日期
    sorted_months = sorted(month_ends.keys())[-months:]

    rows = []
    # 窗口首月的月初市值 = 窗口前最后一个有市值日期的市值（而非 0，否则首月浮盈虚大）
    first_month = sorted_months[0] if sorted_months else None
    prev_mv = 0.0
    if first_month:
        for d in sorted(mv_by_date):
            if _month_of(d) < first_month:
                prev_mv = mv_by_date[d]
            else:
                break
    for m in sorted_months:
        end_d = month_ends[m]
        end_mv = mv_by_date[end_d]
        f = flows.get(m, {"invested": 0.0, "returned": 0.0, "cash_div": 0.0})
        net_invested = f["invested"] - f["returned"]
        pnl_change = end_mv - prev_mv - net_invested
        rows.append(
            {
                "month": m,
                "market_value": round(end_mv, 2),
                "net_invested": round(net_invested, 2),
                "invested": round(f["invested"], 2),
                "returned": round(f["returned"], 2),
                "cash_div": round(f["cash_div"], 2),
                "realized": round(realized_by_month.get(m, 0.0), 2),
                "pnl_change": round(pnl_change, 2),
            }
        )
        prev_mv = end_mv

    # 年度汇总
    years: dict[str, dict[str, float]] = {}
    for r in rows:
        y = r["month"][:4]
        acc = years.setdefault(
            y, {"market_value": 0.0, "net_invested": 0.0, "pnl_change": 0.0, "cash_div": 0.0, "realized": 0.0, "last_mv": 0.0}
        )
        acc["net_invested"] += r["net_invested"]
        acc["pnl_change"] += r["pnl_change"]
        acc["cash_div"] += r["cash_div"]
        acc["realized"] += r["realized"]
        acc["last_mv"] = r["market_value"]
    year_rows = [
        {"year": y, **{k: round(v, 2) for k, v in acc.items() if k != "last_mv"}, "market_value": round(acc["last_mv"], 2)}
        for y, acc in sorted(years.items())
    ]
    return {"months": rows[::-1], "years": year_rows[::-1]}


def build_daily_pnl(conf: Portfolio, store: LocalStore, trades: list[Trade], month: str) -> dict[str, Any]:
    """单月逐日收益（R4 日历视图）：当日收益 = 当日市值 − 前日市值 − 当日净投入。

    口径与月度统计同源（同一推演引擎）；月首日的前值为上月末市值。
    """
    mv = _compute_mv(conf, store, trades)
    if not mv:
        return {"days": {}, "month_total": 0.0}
    day_pnl: dict[str, float] = {}
    prev_mv = 0.0
    for d in sorted(mv):
        if _month_of(d) == month:
            invested = returned = 0.0
            for t in trades:
                if t.date != d:
                    continue
                amt = t.quantity * t.price
                if t.action in ("buy", "contribute"):
                    invested += amt + t.fee
                elif t.action == "sell":
                    returned += amt - t.fee
            day_pnl[d] = round(mv[d] - prev_mv - (invested - returned), 2)
        prev_mv = mv[d]
    return {"days": day_pnl, "month_total": round(sum(day_pnl.values()), 2)}


def build_annual_report(conf: Portfolio, store: LocalStore, trades: list[Trade], year: str) -> dict[str, Any]:
    """年度复盘（R7，年度账单式）：全年投入/收益/月度胜率/最佳最差月/品类贡献。

    数据全部来自既有引擎（月度统计+日收益），不引入新口径。
    """
    summary = build_monthly_summary(conf, store, trades, months=60)
    months = [r for r in summary["months"] if r["month"].startswith(year)]
    if not months:
        return {"year": year, "empty": True}
    # 账户现金余额（存量概念）：缴存+赎回+现金分红 − 申购流出，**从最早流水累计至今**。
    # 不按年过滤——单年为负只是跨年结转（今年买去年存的钱），余额才诚实。
    cash = 0.0
    for t in trades:
        amt = t.quantity * t.price
        if t.action == "contribute":
            cash += amt
        elif t.action == "buy":
            cash -= amt + t.fee
        elif t.action == "sell":
            cash += amt - t.fee
        elif t.action == "dividend_cash":
            cash += amt
    invested = sum(r["invested"] for r in months)
    returned = sum(r["returned"] for r in months)
    pnl = sum(r["pnl_change"] for r in months)
    realized = sum(r["realized"] for r in months)
    cash_div = sum(r["cash_div"] for r in months)
    win = [r for r in months if r["pnl_change"] > 0]
    best = max(months, key=lambda r: r["pnl_change"])
    worst = min(months, key=lambda r: r["pnl_change"])
    end_mv = months[0]["market_value"]  # months 倒序（新→旧），首项为最新月末
    return {
        "year": year,
        "empty": False,
        "net_invested": round(invested - returned, 2),
        "invested": round(invested, 2),
        "returned": round(returned, 2),
        "pnl_change": round(pnl, 2),
        "account_cash": round(cash, 2),
        "realized": round(realized, 2),
        "cash_div": round(cash_div, 2),
        "year_end_mv": end_mv,
        "months_count": len(months),
        "win_months": len(win),
        "best_month": {"month": best["month"], "pnl_change": best["pnl_change"]},
        "worst_month": {"month": worst["month"], "pnl_change": worst["pnl_change"]},
        "monthly": [
            {"month": r["month"], "pnl_change": r["pnl_change"], "net_invested": r["net_invested"]}
            for r in months
        ],
    }
