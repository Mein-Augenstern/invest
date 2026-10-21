import pandas as pd

from invest.metrics import (
    annualized_volatility,
    asof_percentile,
    cagr,
    correlation,
    drawdown,
    ep_spread,
    max_drawdown,
    percentile_rank,
)


def _df(values, start="2024-01-01"):
    dates = pd.date_range(start, periods=len(values), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "close": [float(v) for v in values]})


def test_percentile_rank_basic():
    df = _df([1, 2, 3, 4, 5])
    # 当前值5为最大 → 100%分位
    assert percentile_rank(df, years=None) == 100.0
    # 当前值3：历史[1,2,3,3]中<=3占4/5 → 80%
    df2 = _df([1, 2, 3, 4, 3])
    assert abs(percentile_rank(df2, years=None) - 80.0) < 1e-9
    # 当前值为最小 → 20%
    df3 = _df([5, 4, 3, 2, 1])
    assert abs(percentile_rank(df3, years=None) - 20.0) < 1e-9


def test_percentile_rank_window():
    # 3年窗口外的历史极值不应影响分位：远处100，近处1~3
    old = pd.DataFrame(
        {
            "date": pd.date_range("2015-01-01", periods=50, freq="D").strftime("%Y-%m-%d"),
            "close": [100.0] * 50,
        }
    )
    recent = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=10, freq="D").strftime("%Y-%m-%d"),
            "close": [1.0, 2.0, 3.0, 2.5, 2.8, 3.0, 2.9, 3.1, 3.0, 3.2],
        }
    )
    df = pd.concat([old, recent], ignore_index=True)
    # 3年窗口内当前值3.2为最大 → 100%
    assert percentile_rank(df, years=3) == 100.0
    # 不限窗口则3.2远低于历史极值100 → 低分位
    assert percentile_rank(df, years=None) < 30.0


def test_drawdown():
    df = _df([10, 20, 15, 12])
    assert abs(drawdown(df, years=None) - (12 / 20 - 1)) < 1e-9
    # 新高点 → 0
    df2 = _df([10, 20, 25])
    assert drawdown(df2, years=None) == 0.0


def test_volatility_constant_is_zero():
    # 价格不变 → 波动率0（pct_change全为0）
    df = _df([5] * 10)
    assert annualized_volatility(df, years=None) == 0.0


def test_correlation_self_is_one():
    df = _df([1, 2, 1.5, 2.5, 2, 3, 2.8, 3.2, 3, 3.5, 3.3, 3.8])
    assert abs(correlation(df, df, years=None) - 1.0) < 1e-9


def test_correlation_flat_returns_none():
    # 一条序列无波动 → 有效样本不足
    df_a = _df([1, 2, 1.5, 2.5, 2, 3] * 3)
    df_b = _df([5] * 18)
    assert correlation(df_a, df_b, years=None) is None


def _series_dates(values, dates):
    return pd.DataFrame({"date": dates, "close": [float(v) for v in values]})


def test_asof_percentile_no_lookahead():
    dates = ["2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]
    base = _series_dates([10, 11, 12, 13, 14], dates)
    # 2022时点：只有前三值，当前12为窗口最大 → 100%
    assert asof_percentile(base, "2022-01-01", years=5) == 100.0
    # 防前视铁证：把2023/2024(未来)改成天文数字，2022时点分位不变
    tampered = _series_dates([10, 11, 12, 999, 999], dates)
    assert asof_percentile(tampered, "2022-01-01", years=5) == 100.0
    # 篡改未来只影响"当下及以后"的读数：2024时点当前值13不再压过999
    tampered2 = _series_dates([10, 11, 12, 999, 13], dates)
    assert asof_percentile(tampered2, "2024-01-01", years=5) == 80.0  # ≤13的占4/5


def test_asof_percentile_window_and_empty():
    dates = ["2015-01-01", "2016-01-01", "2020-01-01", "2021-01-01"]
    df = _series_dates([100, 200, 10, 20], dates)
    # 2021时点5年窗口只有2020/2021 → 当前20为最大 → 100%
    assert asof_percentile(df, "2021-01-01", years=5) == 100.0
    assert asof_percentile(df, "2014-01-01") is None  # 序列尚未开始


def test_ep_spread():
    assert abs(ep_spread(8.0, 2.0) - 10.5) < 1e-9  # 12.5% - 2%
    import math
    assert math.isnan(ep_spread(0, 2.0))


def test_max_drawdown_and_cagr():
    df = _series_dates([10, 20, 10, 15], ["2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01"])
    assert abs(max_drawdown(df) - (10 / 20 - 1)) < 1e-9
    # 2020-01-01→2023-01-01 = 1096天(含闰年): 1.5^(365/1096)-1
    assert abs(cagr(df) - (1.5 ** (365.0 / 1096) - 1)) < 1e-9
