"""分析指标：分位、回撤、波动率、相关性。

约定：入参序列为 (date, close) 结构，date 为 YYYY-MM-DD 升序。
"""
from __future__ import annotations

import pandas as pd


def _tail_window(df: pd.DataFrame, years: int) -> pd.DataFrame:
    """截取最近 N 年（按最新日期回推 365*N 天）。"""
    if not years or df.empty:
        return df
    dates = pd.to_datetime(df["date"])
    cutoff = dates.max() - pd.Timedelta(days=365 * years)
    return df[dates >= cutoff]


def percentile_rank(df: pd.DataFrame, years: int | None = 5) -> float | None:
    """当前值在历史窗口内的分位（0~100）。

    口径：历史值 <= 当前值的占比。df 需含 date/close 列。
    """
    if df.empty:
        return None
    window = _tail_window(df, years or 0)
    if window.empty:
        return None
    current = window["close"].iloc[-1]
    return float((window["close"] <= current).mean() * 100)


def drawdown(df: pd.DataFrame, years: int | None = None) -> float | None:
    """当前值距窗口内最高点的回撤（负数或0，单位：小数）。"""
    if df.empty:
        return None
    window = _tail_window(df, years or 0)
    if window.empty:
        return None
    peak = window["close"].max()
    current = window["close"].iloc[-1]
    return float(current / peak - 1) if peak > 0 else None


def annualized_volatility(df: pd.DataFrame, years: int | None = 1) -> float | None:
    """日收益率年化波动率（小数）。"""
    if len(df) < 3:
        return None
    window = _tail_window(df, years or 0)
    if len(window) < 3:
        return None
    ret = window["close"].astype(float).pct_change().dropna()
    if ret.std() == 0:
        return 0.0
    return float(ret.std() * (252**0.5))


def correlation(df_a: pd.DataFrame, df_b: pd.DataFrame, years: int | None = 3) -> float | None:
    """两序列日收益率相关系数（按日期内连接）。"""
    a = _tail_window(df_a, years or 0)[["date", "close"]]
    b = _tail_window(df_b, years or 0)[["date", "close"]]
    merged = pd.merge(a, b, on="date", suffixes=("_a", "_b"))
    if len(merged) < 10:
        return None
    ra = merged["close_a"].astype(float).pct_change()
    rb = merged["close_b"].astype(float).pct_change()
    valid = pd.concat([ra, rb], axis=1).dropna()
    if len(valid) < 10:
        return None
    r = float(valid.iloc[:, 0].corr(valid.iloc[:, 1]))
    return r if pd.notna(r) else None


# ---------- 回测专用：时点正确（防前视）与绩效度量 ----------

def asof_percentile(df: pd.DataFrame, date: str, years: int = 5) -> float | None:
    """date 时点的滚动分位：只用 date 当日及之前、且在 years 年窗口内的数据。

    防前视偏差的命门：回测站在历史某天，只允许用那天已知的序列。
    （percentile_rank 是全序列口径，仅用于"当前"展示，不可用于回测。）
    """
    if df.empty:
        return None
    dates = pd.to_datetime(df["date"])
    asof = pd.Timestamp(date)
    end = dates <= asof
    if not end.any():
        return None
    start = asof - pd.Timedelta(days=365 * years)
    window = df[end & (dates >= start)]
    if window.empty:
        window = df[end]
    current = window["close"].iloc[-1]
    return float((window["close"] <= current).mean() * 100)


def ep_spread(pe: float, bond_yield_pct: float) -> float:
    """股债利差（FED模型口径，百分点）：E/P − 10Y国债收益率。

    E/P = 1/滚动PE × 100（盈利收益率%）；pe 无效返回 None 语义由调用方处理。
    """
    if not pe or pe <= 0:
        return float("nan")
    return 100.0 / pe - bond_yield_pct


def max_drawdown(df: pd.DataFrame) -> float | None:
    """全期最大回撤（负数，小数）：min(price / 历史累计最高 - 1)。"""
    if df.empty:
        return None
    close = df["close"].astype(float)
    peak = close.cummax()
    return float((close / peak - 1).min())


def cagr(df: pd.DataFrame) -> float | None:
    """区间年化收益（小数），按首尾收盘与自然年数。"""
    if len(df) < 2:
        return None
    days = (pd.Timestamp(df["date"].iloc[-1]) - pd.Timestamp(df["date"].iloc[0])).days
    if days <= 0:
        return None
    total = float(df["close"].iloc[-1]) / float(df["close"].iloc[0])
    return total ** (365.0 / days) - 1


def sharpe(close_df: pd.DataFrame, bond_df: pd.DataFrame, years: int | None = None) -> float | None:
    """年化夏普（简版）：日超额收益均值/标准差 × √252，超额=收益-当日国债日收益(近似0持有)。

    无风险利率用国债收益率序列的均值（%→日化），单资产回测够用。
    """
    if len(close_df) < 20:
        return None
    ret = close_df["close"].astype(float).pct_change().dropna()
    if len(bond_df) >= 20:
        bmean = float(bond_df["close"].astype(float).tail(252).mean()) / 100.0 / 252.0
    else:
        bmean = 0.0
    excess = ret - bmean
    if excess.std() == 0:
        return None
    return float(excess.mean() / excess.std() * (252**0.5))
