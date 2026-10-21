"""回测引擎：月度重放 + 组合模拟。

防前视是结构保证：引擎把"截至当日的数据切片"递给策略函数，策略拿不到未来。
所有金额按全收益指数（TR）折算份额——红利策略必须计入分红再投资；
如需模拟基金代理，可用 tracking_drag 年化损耗参数保守调整。

口径声明（详见 docs/05-backtest.md）：
- 价格序列 = 中证红利全收益指数（H00922），非基金净值；
- 成分股历史变迁不可复原 → 存在幸存者偏差（与指数本身口径一致）；
- 费用默认 0（Y 份额申购费为 0），未建模赎回费与税费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from . import metrics
from .ledger.returns import xirr


@dataclass
class BacktestConfig:
    monthly_amount: float = 1000.0
    start: str = "2013-06-03"
    fee_rate: float = 0.0  # 申购费率（Y份额为0）
    tracking_drag: float = 0.0  # 指数代理基金的年化跟踪损耗（保守假设用）


@dataclass
class BacktestResult:
    name: str
    params: str
    equity: pd.DataFrame  # date, invested(累计投入), value(账户市值)
    orders: list[dict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class MonthlyClock:
    """生成回测时间轴：start 起每月一个执行日（该月首个交易日），并提供截至切片。"""

    def __init__(self, price_df: pd.DataFrame, start: str):
        self.df = price_df[price_df["date"] >= start].reset_index(drop=True)
        self.df["ym"] = self.df["date"].str[:7]
        # 每月首个交易日执行（贴近"月初缴存"节奏）
        self.exec_dates = self.df.groupby("ym").first()["date"].tolist()

    def as_of(self, df: pd.DataFrame, date: str) -> pd.DataFrame:
        """裁剪出 date 当日及之前的切片——防前视的唯一入口。"""
        return df[df["date"] <= date].reset_index(drop=True)

    def price_on(self, date: str) -> float | None:
        row = self.df[self.df["date"] <= date]
        return float(row["close"].iloc[-1]) if len(row) else None


def run_backtest(
    name: str,
    params: str,
    price_df: pd.DataFrame,
    signal_df: pd.DataFrame,
    bond_df: pd.DataFrame,
    strategy_fn: Callable[[dict], float],
    cfg: BacktestConfig,
    lumpsum_total: float | None = None,
    series: dict[str, pd.DataFrame] | None = None,
) -> BacktestResult | None:
    """重放一个策略。

    strategy_fn(ctx) -> 本月投入倍率(相对monthly_amount；0=停投)。
    ctx = {date, price, signal_asof, bond_yield, months_left, series_asof}
    series: 附加命名序列(如价格指数/推算股息率)，引擎统一做截至裁剪——
    策略拿到的任何数据都不含未来（防前视的结构保证同样覆盖附加序列）。
    lumpsum_total 提供时：首月一次性投入该总额，此后倍率强制 0。
    """
    clock = MonthlyClock(price_df, cfg.start)
    if not clock.exec_dates:
        return None

    # tracking_drag：对价格序列做年化等比损耗调整
    t0 = pd.Timestamp(clock.exec_dates[0])
    price_adj = price_df.copy()
    if cfg.tracking_drag > 0:
        days = (pd.to_datetime(price_adj["date"]) - t0).dt.days
        price_adj["close"] = price_adj["close"] * (1 - cfg.tracking_drag) ** (days / 365.0)
    clock = MonthlyClock(price_adj, cfg.start)

    shares = 0.0
    invested = 0.0
    rows: list[dict] = []
    orders: list[dict] = []
    n = len(clock.exec_dates)

    for i, date in enumerate(clock.exec_dates):
        price = clock.price_on(date)
        if price is None:
            continue
        signal_asof = clock.as_of(signal_df, date)
        bond_asof = clock.as_of(bond_df, date)
        bond_yield = float(bond_asof["close"].iloc[-1]) if len(bond_asof) else float("nan")

        if lumpsum_total is not None and i == 0:
            amount = lumpsum_total
            note = "期初一次性"
        elif lumpsum_total is not None:
            amount = 0.0
            note = ""
        else:
            series_asof = {k: clock.as_of(v, date) for k, v in (series or {}).items()}
            mult = float(strategy_fn(
                {"date": date, "price": price, "signal_asof": signal_asof,
                 "bond_yield": bond_yield, "months_left": n - i - 1,
                 "series_asof": series_asof}
            ))
            amount = cfg.monthly_amount * mult
            note = f"倍率×{mult}"

        if amount > 0:
            fee = amount * cfg.fee_rate
            shares += (amount - fee) / price
            invested += amount
            orders.append({"date": date, "amount": round(amount, 2), "price": price, "note": note})

        value = shares * price
        rows.append({"date": date, "invested": invested, "value": round(value, 2)})

    equity = pd.DataFrame(rows)
    result = BacktestResult(name=name, params=params, equity=equity, orders=orders)

    final_value = float(equity["value"].iloc[-1])
    total_invested = float(equity["invested"].iloc[-1])
    # 账户最大浮亏：min(（市值-已投入)/已投入)——定投视角比价格MDD更真实
    # 仅对已投入>0的月份计算（零投入策略/期初月份跳过）
    uw_rows = equity[equity["invested"] > 0]
    underwater = ((uw_rows["value"] - uw_rows["invested"]) / uw_rows["invested"]) if len(uw_rows) else None
    flows = [(o["date"], -o["amount"]) for o in orders]
    try:
        r = xirr(flows, equity["date"].iloc[-1], final_value) if flows else None
    except ValueError:
        r = None
    result.metrics = {
        "总投入": round(total_invested, 2),
        "期末市值": round(final_value, 2),
        "累计收益倍数": round(final_value / total_invested, 4) if total_invested else None,
        "XIRR年化": f"{r * 100:.2f}%" if r is not None else "n/a",
        "账户最大浮亏": (f"{underwater.min() * 100:.1f}%" if underwater is not None and len(underwater) else "n/a"),
        "指数自身最大回撤": f"{metrics.max_drawdown(clock.as_of(price_adj, equity['date'].iloc[-1])) * 100:.1f}%",
        "投入笔数": len(orders),
    }
    return result


# ---------- 股息率序列推算（红利本命锚） ----------
# 口径：滚动一年 股息率 ≈ TR/P 两序列同期涨幅之差（分红再投资贡献的年化比率），
# 与中证官网"股息率1(近12个月)"口径同源近似（当前推算值≈4.2% vs 官网4.16%，交叉验证过）。

def derive_dividend_yield(tr_df: pd.DataFrame, price_df: pd.DataFrame, window_days: int = 365) -> pd.DataFrame:
    """由全收益/价格指数推算滚动股息率(%)序列。首年无窗口数据为 NaN。"""
    m = pd.merge(tr_df, price_df, on="date", suffixes=("_tr", "_p")).sort_values("date").reset_index(drop=True)
    import numpy as np

    # 用 DatetimeIndex.searchsorted 做一年前定位——不碰 pandas 内部精度单位
    # （pandas 3.x 默认 us，手算毫秒曾把窗口算成"三万年前"导致序列全空）
    ts_idx = pd.DatetimeIndex(pd.to_datetime(m["date"]))
    left = ts_idx.searchsorted(ts_idx - pd.Timedelta(days=window_days), side="left")
    valid = left > 0
    idx = np.where(valid, left - 1, 0)
    tr = m["close_tr"].astype(float).values
    pr = m["close_p"].astype(float).values
    dy = np.full(len(m), np.nan)
    dy[valid] = ((tr[valid] / tr[idx[valid]]) / (pr[valid] / pr[idx[valid]]) - 1.0) * 100.0
    out = pd.DataFrame({"date": m["date"], "close": dy}).dropna().reset_index(drop=True)
    return out


# ---------- 策略库（六个；参数口径登记 docs/05-backtest.md） ----------

def strat_dca(ctx: dict) -> float:
    """基准1：无脑定投，每月固定。"""
    return 1.0


def make_value_dca(zones: list, window_years: int = 5):
    """策略A：估值增强定投——as-of PE分位决定倍率（与规则书§1同源参数）。"""
    from .strategy import zone_multiplier

    def fn(ctx: dict) -> float:
        pct = metrics.asof_percentile(ctx["signal_asof"], ctx["date"], years=window_years)
        if pct is None:
            return 1.0  # 数据不足时按普通定投
        return zone_multiplier(pct, zones)[0]

    return fn


# E/P利差分档（百分点 → 倍率）；阈值待回看验证后定稿，登记 docs/05
SPREAD_TIERS = [(6.0, 2.0), (4.0, 1.5), (2.0, 1.0), (0.0, 0.5), (-1e9, 0.0)]


def strat_ep_spread(ctx: dict) -> float:
    """策略B：股债利差（FED口径 E/P−10Y国债）分档投入。"""
    sig = ctx["signal_asof"]
    if sig.empty or ctx["bond_yield"] != ctx["bond_yield"]:
        return 1.0
    pe = float(sig["close"].iloc[-1])
    spread = metrics.ep_spread(pe, ctx["bond_yield"])
    if spread != spread:
        return 1.0
    for lo, mult in SPREAD_TIERS:
        if spread >= lo:
            return mult
    return 0.0


# 股息率−10Y利差分档（百分点 → 倍率）；红利指数的本命锚，阈值待回看定稿
DIV_SPREAD_TIERS = [(4.0, 2.0), (3.0, 1.5), (2.0, 1.0), (1.0, 0.5), (-1e9, 0.0)]


def make_div_spread():
    """策略C：股息率−10Y国债利差（红利指数的"本命"择时锚）。

    股息率序列由引擎注入(series_asof['div_yield'])，推算口径见上。
    """
    def fn(ctx: dict) -> float:
        dy_df = ctx["series_asof"].get("div_yield")
        if dy_df is None or dy_df.empty or ctx["bond_yield"] != ctx["bond_yield"]:
            return 1.0
        dy = float(dy_df["close"].iloc[-1])
        spread = dy - ctx["bond_yield"]
        for lo, mult in DIV_SPREAD_TIERS:
            if spread >= lo:
                return mult
        return 0.0
    return fn


# 年线乖离分档（价格相对250日均线：跌破年线=低位加倍，大幅超越=过热停投）
MA_DEV_TIERS = [(0.50, 0.0), (0.30, 0.5), (0.0, 1.0), (-1e9, 2.0)]


def strat_ma_trend(ctx: dict) -> float:
    """策略D：年线择时定投——250日均线乖离分档。

    当前价与均线必须同序列：都用价格指数(000922)。
    （ctx["price"]是TR执行价，拿它比价格均线=苹果比橘子，首版真犯过。）
    """
    px_df = ctx["series_asof"].get("price_index")
    if px_df is None or len(px_df) < 60:
        return 1.0
    ma = float(px_df["close"].tail(250).mean())
    if ma <= 0:
        return 1.0
    dev = float(px_df["close"].iloc[-1]) / ma - 1.0
    for lo, mult in MA_DEV_TIERS:
        if dev >= lo:
            return mult
    return 1.0


# 策略说明（报告与网页共用）
STRATEGY_DOCS = {
    "dca": "每月固定投入，不择时——一切策略的对照组",
    "lumpsum": "期初一次投入同等总资金——衡量'早投入的价值'，月度缴存者不可执行",
    "value_dca": "按滚动PE分位调节倍率（便宜加倍/贵了停投），与规则书§1同源参数",
    "ep_spread": "盈利收益率−10Y国债(FED口径)。注意：红利PE常年低位，此锚在红利上几乎恒显示便宜（教育案例）",
    "div_spread": "股息率−10Y国债——红利指数的'本命'锚：吃息资产与债券直接比性价比",
    "ma_trend": "价格相对250日年线的乖离分档：跌破年线加倍投、大幅超越(>30%/50%)减停",
}


def render_backtest_markdown(results: list, cfg: BacktestConfig, span: str) -> str:
    lines = [
        f"# 中证红利策略回测报告",
        "",
        f"- 区间：{span}（月度重放，月初执行）",
        f"- 资金流：每月 {cfg.monthly_amount:,.0f} 元（期初一次性基准用同等总资金）",
        f"- 价格序列：中证红利全收益指数 H00922；信号：滚动PE分位(hist口径)；利差：E/P−10Y国债",
        f"- 费用：申购费 {cfg.fee_rate:.2%}；跟踪损耗假设 {cfg.tracking_drag:.2%}/年",
        "",
        "## 对照总表",
        "",
        "| 策略 | " + " | ".join(results[0].metrics.keys() if results else []) + " |",
        "|---" * (len(results) + 1) + "|",
    ]
    keys = list(results[0].metrics.keys()) if results else []
    for r in results:
        lines.append(f"| {r.name}({r.params}) | " + " | ".join(str(r.metrics[k]) for k in keys) + " |")

    lines += ["", "## 各策略订单明细（首3笔+末3笔）", ""]
    for r in results:
        lines.append(f"### {r.name}（{r.params}，共{r.metrics['投入笔数']}笔）")
        lines += ["", "| 日期 | 金额 | 执行点位(H00922) | 说明 |", "|---|---|---|---|"]
        head, tail = r.orders[:3], r.orders[-3:]
        for o in head + ([{"date": "…", "amount": "…", "price": "…", "note": ""}] if len(r.orders) > 6 else []) + tail:
            lines.append(f"| {o['date']} | {o['amount']} | {o['price']} | {o['note']} |")
        lines.append("")

    lines += [
        "## 口径与局限（必读）",
        "",
        "1. 用全收益指数代理基金（分红再投资计入收益）；未含联接基金跟踪误差（可用 --drag 保守模拟）。",
        "2. 指数历史成分已变迁，存在幸存者偏差——回测结论偏乐观，看相对排序比看绝对数字更可靠。",
        "3. 所有信号只用执行日之前的数据（as-of），已由单测锁定。",
        "4. 回答不了的问题：未来是否重演；参数在别的区间是否稳健（避免过拟合，阈值以规则书定稿为准）。",
    ]
    return "\n".join(lines) + "\n"


# ---------- 跑批（CLI 与 Web 共用唯一实现） ----------

def run_all_backtests(conf, store, start: str, monthly: float, drag: float = 0.0,
                      codes: list[str] | None = None) -> dict:
    """跑选定的策略集。返回 {results, span, cfg, div_yield_now, missing}。"""
    ins = next((i for i in conf.instruments if i.benchmark_tr_code), None)
    if ins is None:
        return {"missing": "配置缺少 benchmark_tr_code（全收益指数）"}
    tr = store.read_series(ins.benchmark_tr_code, "tr_close")
    bench_code = store.resolve_index_code(ins.benchmark_index)
    price_index = store.read_series(bench_code, "index_close")
    signal = store.read_series(bench_code, "pe_ttm_hist")
    bond = store.read_series("CN10Y", "bond_yield")
    if tr.empty or signal.empty:
        return {"missing": "缺少全收益/PE历史数据，请先在设置页拉数"}

    div_yield = derive_dividend_yield(tr, price_index)
    series = {"price_index": price_index, "div_yield": div_yield}
    cfg = BacktestConfig(monthly_amount=monthly, start=start, tracking_drag=drag)
    months = len(set(tr[tr["date"] >= start]["date"].str[:7]))
    lump_total = monthly * months

    catalog: dict[str, tuple] = {
        "dca": ("无脑定投", "基准", lambda c: strat_dca(c), None),
        "lumpsum": ("期初一次性", "基准", None, lump_total),
        "value_dca": ("估值增强定投", "PE分位", make_value_dca(conf.strategy.zones, conf.strategy.percentile_windows_years), None),
        "ep_spread": ("股债利差·E/P", "FED口径", strat_ep_spread, None),
        "div_spread": ("股息率利差", "股息率−10Y", make_div_spread(), None),
        "ma_trend": ("年线择时定投", "250日均线", strat_ma_trend, None),
    }
    results = []
    for code in (codes or list(catalog)):
        if code not in catalog:
            continue
        name, params, fn, lump = catalog[code]
        r = run_backtest(name, params, tr, signal, bond, fn or (lambda c: 0.0), cfg,
                         lumpsum_total=lump, series=series)
        if r:
            r.code = code
            results.append(r)
    span = (f"{results[0].equity['date'].iloc[0]} ~ {results[0].equity['date'].iloc[-1]}"
            if results else "")
    div_now = float(div_yield["close"].iloc[-1]) if not div_yield.empty else None
    return {"results": results, "span": span, "cfg": cfg, "div_yield_now": div_now, "missing": None}


def measured_tracking_drag(store, fund_code: str, tr_code: str) -> dict | None:
    """实测年化跟踪差：基金真实净值 vs 全收益指数（费率+现金拖累+打新增强的净效果）。

    这是"跟踪损耗"最诚实的口径——不猜费率，直接量你这笔钱的实际落差。
    注意标的基金成立尚短（真实代码不入公开仓），年化外推有噪声，随时间自动更准。
    """
    nav = store.read_series(fund_code, "fund_nav_cum")  # 累计净值口径(分红加回)
    basis = "累计净值"
    if nav.empty:
        nav = store.read_series(fund_code, "fund_nav")
        basis = "单位净值(分红未加回,偏低估)"
    tr = store.read_series(tr_code, "tr_close")
    if len(nav) < 60 or len(tr) < 60:
        return None
    m = pd.merge(nav, tr, on="date", suffixes=("_f", "_t")).sort_values("date")
    if len(m) < 60:
        return None
    days = (pd.Timestamp(m["date"].iloc[-1]) - pd.Timestamp(m["date"].iloc[0])).days
    if days < 180:
        return None
    fund_total = float(m["close_f"].iloc[-1]) / float(m["close_f"].iloc[0])
    tr_total = float(m["close_t"].iloc[-1]) / float(m["close_t"].iloc[0])
    fund_ann = fund_total ** (365.0 / days) - 1
    tr_ann = tr_total ** (365.0 / days) - 1
    return {
        "annualized_pct": round((fund_ann - tr_ann) * 100, 2),
        "basis": basis,
        "period": f"{m['date'].iloc[0]} ~ {m['date'].iloc[-1]}",
        "days": days,
        "fund_total_pct": round((fund_total - 1) * 100, 2),
        "tr_total_pct": round((tr_total - 1) * 100, 2),
    }
