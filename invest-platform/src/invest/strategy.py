"""策略引擎 v1：按规则书(docs/business/strategy-rules.md)评估当前状态，输出建议信号。

信号 = 规则 + 数据，仅作为纪律工具；执行与否由用户确认（红线：不自动下单）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import metrics
from .config import Portfolio, series_kind
from .data.local import LocalStore
from .data.mysql_store import MySQLStore
from .ledger.ledger import Position
from .ledger.trades import Trade


@dataclass
class Signal:
    instrument_id: str
    rule_ref: str  # 规则书条目引用
    metric: str  # 依据指标名（含口径）
    metric_value: str
    action: str  # 建议动作
    date: str = ""
    status: str = "建议"

    def __post_init__(self) -> None:
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d")


def zone_multiplier(percentile: float, zones: list[tuple[float, float, float]]) -> tuple[float, str]:
    """分位→定投系数。zones: [(下界, 上界, 系数), ...]，返回 (系数, 区间描述)。"""
    for lo, hi, mult in zones:
        if lo <= percentile < hi:
            return mult, f"{lo:.0f}%~{hi:.0f}%"
    return zones[-1][2], f">={zones[-1][1]:.0f}%"


def evaluate_etf_percentile_invest(
    ins, conf: Portfolio, store: LocalStore | MySQLStore
) -> Signal | None:
    """规则书§1：消费50 估值分位定投（当前以 hist 口径滚动PE分位为依据）。"""
    code = store.resolve_index_code(ins.benchmark_index) if ins.benchmark_index else None
    if not code:
        return None
    pe_hist = store.read_series(code, "pe_ttm_hist")
    pct = metrics.percentile_rank(pe_hist, years=conf.strategy.percentile_windows_years)
    if pct is None:
        return None
    mult, zone_desc = zone_multiplier(pct, conf.strategy.zones)
    base = conf.strategy.base_monthly_invest
    if mult == 0:
        action = f"停止买入（分位>85%），评估分批止盈"
    else:
        action = f"本期定投 {base:,.0f} × {mult} = {base * mult:,.0f} 元"
    return Signal(
        instrument_id=ins.id,
        rule_ref="规则书§1 估值分位定投",
        metric=f"PE分位(近{conf.strategy.percentile_windows_years}年, hist口径)",
        metric_value=f"{pct:.0f}%（{zone_desc}）",
        action=action,
    )


def evaluate_pension_contribution(
    ins, conf: Portfolio, trades: list[Trade]
) -> Signal | None:
    """规则书§2.1：养老金年度缴存进度。

    口径：年度上限约束的是"缴存"（contribute=账户入金），不是"申购"（buy=用账户
    资金买基金）——历年缴存未申购的现金结余可在以后年份申购，不占当年额度。
    """
    year = datetime.now().strftime("%Y")
    contributions = [
        t.quantity * t.price
        for t in trades
        if t.instrument_id == ins.id and t.action == "contribute" and t.date.startswith(year)
    ]
    cap = conf.strategy.pension_annual_cap

    if not contributions:
        return Signal(
            instrument_id=ins.id,
            rule_ref="规则书§2.1 年度缴存",
            metric=f"{year}年缴存进度",
            metric_value="未录入缴存记录",
            action="在流水页录入「缴存」（账户入金，与申购区分）后可精确跟踪年度进度",
        )

    contributed = sum(contributions)
    if contributed >= cap:
        action = f"{year}年已缴满 {cap:,.0f} 元，保持持有（§2.5 不折腾）"
    else:
        action = f"距年度上限还差 {cap - contributed:,.0f} 元，按§2.1节奏缴存（12月检查补足）"
    pct = contributed / cap * 100 if cap else 0
    return Signal(
        instrument_id=ins.id,
        rule_ref="规则书§2.1 年度缴存",
        metric=f"{year}年缴存进度",
        metric_value=f"{contributed:,.0f}/{cap:,.0f} 元（{pct:.0f}%）",
        action=action,
    )


def evaluate_rebalance(
    conf: Portfolio, store: LocalStore | MySQLStore, positions: dict[str, Position]
) -> Signal | None:
    """规则书§2.3：目标配置偏离检查（需已有持仓与价格数据，否则跳过）。"""
    targets = conf.strategy.target_weights
    if not targets:
        return None
    values: dict[str, float] = {}
    for ins in conf.instruments:
        pos = positions.get(ins.id)
        if not pos or not ins.code:
            return None  # 持仓/代码不全时跳过，不给出误导信号
        row = store.latest(ins.code, series_kind(ins.type))
        if not row:
            return None
        values[ins.id] = pos.quantity * row[1]
    total = sum(values.values())
    if total <= 0 or not set(targets).issubset(values):
        return None
    deviations = {k: values[k] / total * 100 - w * 100 for k, w in targets.items() if k in values}
    worst_id, worst_dev = max(deviations.items(), key=lambda kv: abs(kv[1]))
    if abs(worst_dev) < conf.strategy.rebalance_deviation_pct:
        return None
    ins_name = next(i.name for i in conf.instruments if i.id == worst_id)
    return Signal(
        instrument_id=worst_id,
        rule_ref="规则书§2.3 再平衡",
        metric="配置偏离",
        metric_value=f"{ins_name} {values[worst_id] / total * 100:.1f}% vs 目标 {targets[worst_id] * 100:.0f}%",
        action=f"偏离超±{conf.strategy.rebalance_deviation_pct:.0f}pct，在养老金账户内调整（§2.3）",
    )


def evaluate_all(
    conf: Portfolio, store: LocalStore | MySQLStore, trades: list[Trade]
) -> list[Signal]:
    from .ledger.ledger import build_positions

    positions = build_positions(trades)
    signals: list[Signal] = []
    rebalance_done = False
    for ins in conf.instruments:
        if ins.type == "etf":
            sig = evaluate_etf_percentile_invest(ins, conf, store)
            if sig:
                signals.append(sig)
        elif conf.accounts.get(ins.account) and ins.account == "pension":
            sig = evaluate_pension_contribution(ins, conf, trades)
            if sig:
                signals.append(sig)
            if not rebalance_done:
                reb = evaluate_rebalance(conf, store, positions)
                if reb:
                    signals.append(reb)
                rebalance_done = True
    return signals
