"""报表视图模型层：纯数据（数值/None/字符串），格式化归渲染层（CLI markdown / Jinja2）。

此前同一份"持仓+市值+盈亏+XIRR+基准估值"计算散落三处（cli/_build_snapshot_md、
dashboard.build_dashboard、entry_server.state_payload），本模块是唯一实现。
分层约定：webapp 只准调本模块，禁止直接 import pandas/metrics/ledger 做计算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from . import metrics
from .config import TYPE_LABELS, Portfolio, series_kind
from .data.local import LocalStore
from .ledger.ledger import avg_cost, build_positions, unrealized_pnl
from .ledger.returns import xirr
from .ledger.trades import Trade

ACTION_LABELS = {
    "buy": "申购",
    "contribute": "缴存",
    "sell": "赎回",
    "dividend_cash": "现金分红",
    "dividend_reinvest": "红利再投资",
    "adjust": "份额校准",
}

# 场内品类（股票/债券/ETF）的动词口径
ACTION_LABELS_SECURITIES = {"buy": "买入", "sell": "卖出"}


def action_label(action: str, itype: str = "open_end_fund") -> str:
    if itype in ("stock", "bond", "etf"):
        return ACTION_LABELS_SECURITIES.get(action, ACTION_LABELS.get(action, action))
    return ACTION_LABELS.get(action, action)


# ---------- 持仓快照视图 ----------

@dataclass
class HoldingRow:
    instrument_id: str
    name: str
    account_name: str
    type: str = ""  # 品类（P9）：etf/open_end_fund/stock/bond/wealth
    type_label: str = ""
    state: str = ""  # full=有持仓有价格 | noprice=有持仓缺价格 | empty=无持仓
    quantity: float = 0.0
    price: float | None = None
    price_date: str = "—"
    avg_cost: float | None = None
    market_value: float | None = None
    unrealized: float | None = None
    realized_pnl: float = 0.0
    cash_dividend: float = 0.0
    xirr: float | None = None  # 小数；None 且 xirr_error=False 表示未算
    xirr_error: bool = False


@dataclass
class BenchmarkRow:
    name: str
    code: str | None = None
    close: float | None = None
    pe_ttm: float | None = None  # 中证官网 hist 口径滚动PE
    pct_5y: float | None = None
    pct_all: float | None = None
    dyield: float | None = None
    drawdown_5y: float | None = None


@dataclass
class PortfolioView:
    date: str
    config_source: str
    is_example_config: bool
    rows: list[HoldingRow] = field(default_factory=list)
    total_market_value: float | None = None
    total_unrealized: float | None = None
    total_xirr: float | None = None
    benchmarks: list[BenchmarkRow] = field(default_factory=list)
    correlation: float | None = None


def build_portfolio_view(
    conf: Portfolio, store: LocalStore, trades: list[Trade], value_date: str | None = None
) -> PortfolioView:
    today = value_date or datetime.now().strftime("%Y-%m-%d")
    positions = build_positions(trades)
    view = PortfolioView(
        date=today,
        config_source=conf.source,
        is_example_config=conf.source.endswith("example.yaml"),
    )

    total_mv = total_unreal = 0.0
    flows_total: list[tuple[str, float]] = []
    for ins in conf.instruments:
        pos = positions.get(ins.id)
        account = conf.accounts.get(ins.account)
        row = HoldingRow(
            instrument_id=ins.id,
            name=ins.name,
            account_name=account.name if account else ins.account,
            type=ins.type,
            type_label=TYPE_LABELS.get(ins.type, ins.type),
            quantity=pos.quantity if pos else 0.0,
            realized_pnl=pos.realized_pnl if pos else 0.0,
            cash_dividend=pos.cash_dividend if pos else 0.0,
        )
        series_key = ins.code or ins.id  # wealth 无交易代码，序列键回退 id
        latest = store.latest(series_key, series_kind(ins.type))
        if latest:
            row.price, row.price_date = latest[1], latest[0]
        if pos and row.price is not None:
            row.state = "full"
            row.avg_cost = avg_cost(pos)
            row.market_value = pos.quantity * row.price
            row.unrealized = unrealized_pnl(pos, row.price)
            total_mv += row.market_value
            total_unreal += row.unrealized
            inst_flows = [(t.date, t.cash_flow) for t in trades if t.instrument_id == ins.id]
            flows_total.extend(inst_flows)
            try:
                row.xirr = xirr(inst_flows, row.price_date, row.market_value) if inst_flows else None
            except ValueError:
                row.xirr_error = True
        elif pos:
            row.state = "noprice"
            row.avg_cost = avg_cost(pos)
        else:
            row.state = "empty"
        view.rows.append(row)

    if flows_total:
        view.total_market_value = total_mv
        view.total_unrealized = total_unreal
        try:
            view.total_xirr = xirr(flows_total, today, total_mv)
        except ValueError:
            pass

    # 基准估值
    closes: dict[str, pd.DataFrame] = {}
    seen: set[str] = set()
    for ins in conf.instruments:
        name = ins.benchmark_index
        if not name or name in seen:
            continue
        seen.add(name)
        b = BenchmarkRow(name=name)
        code = store.resolve_index_code(name)
        if not code:
            view.benchmarks.append(b)
            continue
        b.code = code
        close_df = store.read_series(code, "index_close")
        pe_hist = store.read_series(code, "pe_ttm_hist")
        dy = store.latest(code, "dyield_1y")
        if not close_df.empty:
            b.close = float(close_df["close"].iloc[-1])
            closes[name] = close_df
        if not pe_hist.empty:
            b.pe_ttm = float(pe_hist["close"].iloc[-1])
        b.pct_5y = metrics.percentile_rank(pe_hist, years=5)
        b.pct_all = metrics.percentile_rank(pe_hist, years=None)
        if dy:
            b.dyield = dy[1]
        b.drawdown_5y = metrics.drawdown(close_df, years=5)
        view.benchmarks.append(b)

    if len(closes) >= 2:
        (n1, d1), (n2, d2) = list(closes.items())[:2]
        view.correlation = metrics.correlation(d1, d2, years=3)
    return view


def render_snapshot_markdown(v: PortfolioView) -> str:
    """CLI/周报用 markdown 渲染（与重构前 _build_snapshot_md 输出逐字节一致，golden test 锁定）。"""

    def fmt(x: float, digits: int = 2) -> str:
        return f"{x:,.{digits}f}"

    lines = [
        f"# 持仓快照 {v.date}",
        "",
        f"- 配置来源: `{v.config_source}`"
        + ("（示例配置——请复制为 portfolio.local.yaml 并填写真实代码/持仓）" if v.is_example_config else ""),
        "",
        "| 标的 | 账户 | 持仓 | 现价/净值 | 均价成本 | 市值 | 浮动盈亏 | 已实现盈亏 | 现金分红 | XIRR |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in v.rows:
        if r.state == "full":
            xirr_s = "n/a" if r.xirr_error else (f"{r.xirr * 100:.2f}%" if r.xirr is not None else "—")
            lines.append(
                f"| {r.name} | {r.account_name} | {fmt(r.quantity, 0)} | {r.price:.4f}({r.price_date}) "
                f"| {fmt(r.avg_cost, 4)} | {fmt(r.market_value)} | {fmt(r.unrealized)} "
                f"| {fmt(r.realized_pnl)} | {fmt(r.cash_dividend)} | {xirr_s} |"
            )
        elif r.state == "noprice":
            lines.append(
                f"| {r.name} | {r.account_name} | {fmt(r.quantity, 0)} | 缺价格 | {fmt(r.avg_cost, 4)} "
                f"| — | — | {fmt(r.realized_pnl)} | {fmt(r.cash_dividend)} | — |"
            )
        else:
            lines.append(f"| {r.name} | {r.account_name} | 0 | — | — | — | — | — | — | — |")

    if v.total_market_value is not None:
        tail = f"，组合 XIRR **{v.total_xirr * 100:.2f}%**" if v.total_xirr is not None else ""
        lines += [
            "",
            f"**组合合计**：市值 {fmt(v.total_market_value)} 元，浮动盈亏 {fmt(v.total_unrealized)} 元{tail}",
        ]

    lines += [
        "",
        "## 基准指数估值",
        "",
        "| 指数 | 代码 | 收盘 | PE(TTM) | PE分位(5y) | PE分位(全历史) | 股息率(近12月) | 距5年高点回撤 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in v.benchmarks:
        close_s = f"{b.close:,.0f}" if b.close is not None else "—"
        pe_s = f"{b.pe_ttm:.2f}" if b.pe_ttm is not None else "—"
        p5 = f"{b.pct_5y:.0f}%" if b.pct_5y is not None else "—"
        pa = f"{b.pct_all:.0f}%" if b.pct_all is not None else "—"
        dy = f"{b.dyield:.2f}%" if b.dyield is not None else "—"
        dd = f"{b.drawdown_5y * 100:.1f}%" if b.drawdown_5y is not None else "—"
        lines.append(f"| {b.name} | {b.code or '?'} | {close_s} | {pe_s} | {p5} | {pa} | {dy} | {dd} |")

    if v.correlation is not None:
        lines += ["", f"- 两基准近3年日收益相关系数：**{v.correlation:.2f}**（越低分散效果越好）"]
    return "\n".join(lines) + "\n"


# ---------- 录入页状态 ----------

def build_entry_state(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> dict[str, Any]:
    """录入页/流水页状态（entry_server.state_payload 的参数化版本）。"""
    positions = build_positions(trades)
    year = datetime.now().strftime("%Y")

    instruments = []
    for ins in conf.instruments:
        latest = store.latest(ins.code or ins.id, series_kind(ins.type))
        pos = positions.get(ins.id)
        is_pension = ins.account == "pension"
        contributions = [
            t.quantity * t.price
            for t in trades
            if t.instrument_id == ins.id and t.action == "contribute" and t.date.startswith(year)
        ]
        contributed = sum(contributions)
        instruments.append(
            {
                "id": ins.id,
                "name": ins.name,
                "type": ins.type,
                "is_pension": is_pension,
                "price": latest[1] if latest else None,
                "price_date": latest[0] if latest else "",
                "price_label": "净值" if ins.type in ("open_end_fund", "wealth") else "现价",
                "quantity": pos.quantity if pos else 0,
                "avg_cost": round(avg_cost(pos), 4) if pos and pos.quantity else None,
                "market_value": round(pos.quantity * latest[1], 2) if pos and latest else None,
                "unrealized": round(unrealized_pnl(pos, latest[1]), 2) if pos and latest else None,
                "cash_dividend": round(pos.cash_dividend, 2) if pos else 0,
                "year_contribution": round(contributed, 2),
                "contribution_entered": bool(contributions),
                "annual_cap": conf.strategy.pension_annual_cap if is_pension else None,
            }
        )

    rows = [
        {
            "date": t.date,
            "instrument_id": t.instrument_id,
            "action": t.action,
            "action_label": ACTION_LABELS.get(t.action, t.action),
            "quantity": t.quantity,
            "price": t.price,
            "fee": t.fee,
            "note": t.note,
        }
        for t in trades
    ]
    return {"instruments": instruments, "trades": rows, "year": year}


# ---------- 静态看板数据 ----------

def downsample(df: pd.DataFrame, max_points: int = 500) -> list[list[float]]:
    """等距抽点保留末点；时间戳为 UTC 毫秒（datetime 生成，不依赖 pandas 内部精度）。"""
    if len(df) <= max_points:
        idx = list(range(len(df)))
    else:
        step = len(df) // max_points
        idx = list(range(0, len(df), step))
        if idx[-1] != len(df) - 1:
            idx.append(len(df) - 1)
    rows = df.iloc[idx]
    ms = [
        int(datetime.strptime(str(d), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        for d in rows["date"]
    ]
    return [list(pair) for pair in zip(ms, rows["close"].astype(float).tolist())]


def build_dashboard_data(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> dict[str, Any]:
    """静态看板/总览页共用的数据块（原 dashboard.build_dashboard 的数据部分）。"""
    window_years = conf.strategy.percentile_windows_years
    indexes: list[dict] = []
    closes: dict[str, pd.DataFrame] = {}
    for i, ins in enumerate(conf.instruments):
        code = store.resolve_index_code(ins.benchmark_index) if ins.benchmark_index else None
        if not code:
            continue
        pe_hist = store.read_series(code, "pe_ttm_hist")
        close_df = store.read_series(code, "index_close")
        dy = store.latest(code, "dyield_1y")
        if pe_hist.empty or close_df.empty:
            continue
        closes[ins.benchmark_index] = close_df
        indexes.append(
            {
                "name": ins.benchmark_index,
                "code": code,
                "note": f"{ins.name}的估值基准；分位窗口近{window_years}年",
                "pe": float(pe_hist["close"].iloc[-1]),
                "pe_date": pe_hist["date"].iloc[-1],
                "pct5y": metrics.percentile_rank(pe_hist, years=window_years) or 0.0,
                "pctAll": metrics.percentile_rank(pe_hist, years=None) or 0.0,
                "dyield": dy[1] if dy else 0.0,
                "dyield_date": dy[0] if dy else "",
                "dd5y": metrics.drawdown(close_df, years=5) or 0.0,
                "close": float(close_df["close"].iloc[-1]),
                "peSeries": downsample(pe_hist),
            }
        )

    cmp_data = None
    corr = None
    if len(closes) >= 2:
        (n1, d1), (n2, d2) = list(closes.items())[:2]
        m = pd.merge(d1, d2, on="date", suffixes=("_a", "_b"))
        if not m.empty:
            base_a, base_b = m["close_a"].iloc[0], m["close_b"].iloc[0]
            ia = m.assign(v=m["close_a"] / base_a * 100.0)[["date", "v"]]
            ib = m.assign(v=m["close_b"] / base_b * 100.0)[["date", "v"]]
            corr = metrics.correlation(d1, d2, years=3)
            cmp_data = {
                "series": [
                    {"name": n1, "points": downsample(ia.rename(columns={"v": "close"}))},
                    {"name": n2, "points": downsample(ib.rename(columns={"v": "close"}))},
                ]
            }

    # 我的持仓
    positions = build_positions(trades)
    holdings = []
    for i, ins in enumerate(conf.instruments):
        if not ins.code and ins.type != "wealth":
            continue
        pos = positions.get(ins.id)
        if not pos or not pos.quantity:
            continue
        series_key = ins.code or ins.id
        nav_df = store.read_series(series_key, series_kind(ins.type))
        latest = store.latest(series_key, series_kind(ins.type))
        if not latest or nav_df.empty:
            continue
        flows = [(t.date, t.cash_flow) for t in trades if t.instrument_id == ins.id]
        try:
            r = xirr(flows, latest[0], pos.quantity * latest[1]) if flows else None
        except ValueError:
            r = None
        holdings.append(
            {
                "name": ins.name,
                "code": ins.code,
                "hue": i,
                "price_label": "最新净值" if ins.type == "open_end_fund" else "最新价",
                "chart_title": "单位净值走势" if ins.type == "open_end_fund" else "价格走势",
                "quantity": pos.quantity,
                "avg_cost": round(avg_cost(pos), 4),
                "price": latest[1],
                "price_date": latest[0],
                "market_value": round(pos.quantity * latest[1], 2),
                "unrealized": round(unrealized_pnl(pos, latest[1]), 2),
                "xirr": f"{r * 100:.2f}%" if r is not None else "—",
                "navSeries": downsample(nav_df),
                "events": build_trade_events(trades, ins.id),
            }
        )

    name_of = {i.id: i.name for i in conf.instruments}
    signals = [
        [str(s[0]), s[1], name_of.get(s[2], s[2]), s[3], s[4], s[5], s[6], s[7]]
        for s in store.recent_signals(limit=12)
    ][::-1]

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "windowYears": window_years,
        "corr": f"{corr:.2f}" if cmp_data and corr is not None else None,
        "holdings": holdings,
        "indexes": indexes,
        "cmp": cmp_data,
        "signals": signals,
    }


# ---------- 周报（CLI 与 Web 共用单一实现） ----------

def evaluate_and_store_signals(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> int:
    """评估并落库信号（显式动作：仅信号页/信号命令/周报生成时调用，页面刷新不触发）。"""
    from .strategy import evaluate_all

    signals = evaluate_all(conf, store, trades)
    return len(store.add_signals(signals))


def render_signals_markdown(conf: Portfolio, store: LocalStore, today: str | None = None) -> str:
    lines = [
        f"## 策略信号（{today or datetime.now().strftime('%Y-%m-%d')}）",
        "",
        "| # | 标的 | 规则 | 依据 | 取值 | 建议动作 | 状态 |",
        "|---|---|---|---|---|---|---|",
    ]
    name_of = {i.id: i.name for i in conf.instruments}
    for s in reversed(store.recent_signals(limit=12)):
        lines.append(
            f"| {s[0]} | {name_of.get(s[2], s[2])} | {s[3]} | {s[4]} | {s[5]} | {s[6]} | {s[7]} |"
        )
    return "\n".join(lines) + "\n"


def build_weekly_report_md(
    conf: Portfolio, store: LocalStore, trades: list[Trade], with_ai: bool = False, now: datetime | None = None
) -> str:
    from .digest import generate_digest

    today = (now or datetime.now()).strftime("%Y-%m-%d")
    evaluate_and_store_signals(conf, store, trades)
    body = render_snapshot_markdown(build_portfolio_view(conf, store, trades))
    body += "\n" + render_signals_markdown(conf, store)
    header = f"# 投资周报 {today}\n\n"
    if with_ai:
        header += "> AI 解读 = 信息压缩与推理，不构成预测；策略执行以规则书信号为准。\n\n"
        body += f"\n## AI 解读（GLM）\n\n{generate_digest(body)}\n"
    return header + body


# ---------- 策略视图（每个投资品类的规则显性化） ----------

def build_strategy_view(conf: Portfolio, store: LocalStore, trades: list[Trade]) -> list[dict[str, Any]]:
    """每个标的一张策略卡：规则逻辑 + 当前所处状态 + 当前建议（小白可直接读懂）。

    与 strategy.evaluate_all 的区别：本视图是"给人看的规则说明书+当前进度"，
    evaluate_all 是"给系统用的信号生成"；两者引用同一份规则参数(conf.strategy)。
    """
    from .strategy import zone_multiplier

    year = datetime.now().strftime("%Y")
    cards: list[dict[str, Any]] = []
    for ins in conf.instruments:
        if ins.type == "etf":
            card = {
                "id": ins.id,
                "name": ins.name,
                "kind_label": "场内ETF · 估值分位定投",
                "rulebook_ref": "规则书§1（参数待P2回看定稿）",
                "logic": "指数越便宜买越多、越贵买越少直至停止——用PE历史分位衡量贵贱，"
                         "把'什么时候买多少'变成一张写死的表，避免凭感觉操作。",
                "zones": [
                    {"lo": z[0], "hi": z[1], "mult": z[2], "active": False}
                    for z in conf.strategy.zones
                ],
                "current": None,
                "notes": [
                    f"仓位上限：该标的占总权益 ≤ 30%（P4组合层定稿）",
                    "备用工具：网格交易、趋势止损（规则书§1，暂未启用）",
                ],
            }
            code = store.resolve_index_code(ins.benchmark_index) if ins.benchmark_index else None
            if code:
                pe_hist = store.read_series(code, "pe_ttm_hist")
                pct = metrics.percentile_rank(pe_hist, years=conf.strategy.percentile_windows_years)
                if pct is not None:
                    mult, zone_desc = zone_multiplier(pct, conf.strategy.zones)
                    base = conf.strategy.base_monthly_invest
                    action = (
                        f"停止买入（分位>85%），评估分批止盈" if mult == 0
                        else f"本期定投 {base:,.0f} × {mult} = {base * mult:,.0f} 元"
                    )
                    card["current"] = {
                        "metric": f"PE分位（近{conf.strategy.percentile_windows_years}年，hist口径）",
                        "value": pct,
                        "zone_desc": zone_desc,
                        "mult": mult,
                        "action": action,
                    }
                    for z in card["zones"]:
                        z["active"] = z["lo"] <= pct < z["hi"]
            cards.append(card)
        else:
            contributed = sum(
                t.quantity * t.price + t.fee
                for t in trades
                if t.instrument_id == ins.id and t.action == "buy" and t.date.startswith(year)
            )
            cap = conf.strategy.pension_annual_cap
            cards.append(
                {
                    "id": ins.id,
                    "name": ins.name,
                    "kind_label": "个人养老金 · 配置与纪律",
                    "rulebook_ref": "规则书§2",
                    "logic": "这个账户的钱锁到退休，且缴存抵扣个税（领取只缴3%）——"
                             "所以策略核心不是择时，而是'缴满、拿住、少折腾'。",
                    "rules": [
                        {"title": "缴满", "desc": f"每年缴满 {cap:,.0f} 元上限（年初一次性，早投入早复利）",
                         "progress": contributed / cap * 100 if cap else 0,
                         "progress_label": f"{contributed:,.0f} / {cap:,.0f} 元"},
                        {"title": "拿住", "desc": "不因短期波动卖出；账户锁定本身帮你管住了手"},
                        {"title": "少折腾", "desc": "仅当与另一标的的配置比例偏离目标 ±10pct 时，在账户内再平衡（§2.3）"},
                        {"title": "分红方式", "desc": "当前设置为红利再投资（2025-10-20起）；规则书§2.4默认现金分红，待定夺"},
                    ],
                }
            )
    return cards


# ---------- 单标的详情视图（持仓分页 + 趋势图事件标记） ----------

def _to_ms(date_str: str) -> int:
    return int(datetime.strptime(str(date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def build_trade_events(trades: list[Trade], instrument_id: str) -> list[dict[str, Any]]:
    """该标的的交易事件（用于趋势图标记）：买入/赎回/红利再投资/现金分红。"""
    events: list[dict[str, Any]] = []
    for t in trades:
        if t.instrument_id != instrument_id or t.action == "adjust":
            continue
        amount = t.quantity * t.price
        if t.action == "buy":
            label = f"申购 {amount:,.0f} 元"
        elif t.action == "sell":
            label = f"赎回 {amount:,.0f} 元"
        elif t.action == "dividend_reinvest":
            label = f"红利再投资 +{t.quantity:,.2f} 份"
        else:
            label = f"现金分红 {amount:,.0f} 元"
        events.append({"ts": _to_ms(t.date), "label": label, "kind": t.action})
    return events


def build_instrument_view(conf: Portfolio, store: LocalStore, trades: list[Trade], instrument_id: str) -> dict[str, Any] | None:
    """单标的详情：账本行、基准估值、净值/PE序列、交易事件、相关信号。"""
    view = build_portfolio_view(conf, store, trades)
    row = next((r for r in view.rows if r.instrument_id == instrument_id), None)
    if row is None:
        return None
    ins = next(i for i in conf.instruments if i.id == instrument_id)
    out: dict[str, Any] = {
        "id": instrument_id,
        "name": ins.name,
        "code": ins.code,
        "type": ins.type,
        "account": conf.accounts.get(ins.account),
        "row": row,
        "nav_series": [],
        "pe_series": [],
        "benchmark": None,
        "events": build_trade_events(trades, instrument_id),
        "signals": [
            {"id": s[0], "date": s[1], "rule": s[3], "metric": s[4], "value": s[5], "action": s[6], "status": s[7]}
            for s in store.recent_signals(limit=30)
            if s[2] == instrument_id
        ][:10],
    }
    series_key = ins.code or ins.id
    if series_key:
        nav_df = store.read_series(series_key, series_kind(ins.type))
        if not nav_df.empty:
            out["nav_series"] = downsample(nav_df)
            out["nav_start"] = nav_df["date"].iloc[0]
    # 基金透视（持仓穿透）
    if ins.type == "open_end_fund" and ins.code:
        period = store.fund_holdings_period(ins.code)
        if period:
            out["lookthrough"] = {
                "period": period,
                "holdings": [
                    {"rank": r[0], "code": r[1], "name": r[2], "weight_pct": round(r[3] * 100, 2)}
                    for r in store.fund_holdings(ins.code)
                ],
                "industry": [
                    {"name": r[0], "weight_pct": round(r[1] * 100, 2)}
                    for r in store.fund_industry(ins.code)
                ][:8],
                "industry_total_pct": round(sum(r[1] for r in store.fund_industry(ins.code)) * 100, 1),
            }

    if ins.benchmark_index:
        b = next((b for b in view.benchmarks if b.name == ins.benchmark_index), None)
        out["benchmark"] = b
        if b and b.code:
            pe_df = store.read_series(b.code, "pe_ttm_hist")
            if not pe_df.empty:
                out["pe_series"] = downsample(pe_df)
    return out
