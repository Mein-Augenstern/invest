"""回测引擎数学正确性：手算用例对账 + 防前视结构性验证。"""
import pandas as pd

from invest.backtest import BacktestConfig, run_backtest


def _px(dates, closes):
    return pd.DataFrame({"date": dates, "close": [float(c) for c in closes]})


def test_dca_rising_price_math():
    # 三个月价格 100/110/121（每月+10%），每月投1000
    dates = ["2024-01-02", "2024-02-01", "2024-03-01", "2024-03-29"]
    price = _px(dates, [100, 110, 121, 121])
    sig = _px(dates, [10, 10, 10, 10])
    bond = _px(["2024-01-01"], [2.0])
    res = run_backtest("定投", "x", price, sig, bond, lambda ctx: 1.0,
                       BacktestConfig(monthly_amount=1000, start="2024-01-01"))
    shares = 1000 / 100 + 1000 / 110 + 1000 / 121
    expect_value = shares * 121
    assert abs(res.metrics["期末市值"] - round(expect_value, 2)) < 0.01
    assert res.metrics["总投入"] == 3000.0
    assert res.metrics["投入笔数"] == 3
    assert res.metrics["XIRR年化"] != "n/a" and float(res.metrics["XIRR年化"].rstrip("%")) > 0


def test_lumpsum_beats_dca_in_monotonic_rise():
    dates = ["2024-01-02", "2024-02-01", "2024-03-01"]
    price = _px(dates, [100, 110, 121])
    sig = _px(dates, [10, 10, 10])
    bond = _px(["2024-01-01"], [2.0])
    cfg = BacktestConfig(monthly_amount=1000, start="2024-01-01")
    dca = run_backtest("定投", "x", price, sig, bond, lambda c: 1.0, cfg)
    lump = run_backtest("一次", "x", price, sig, bond, lambda c: 0.0, cfg, lumpsum_total=3000.0)
    assert lump.metrics["期末市值"] == 3630.0  # 30份×121
    assert lump.metrics["期末市值"] > dca.metrics["期末市值"]  # 单边上涨中早投占优


def test_engine_blocks_lookahead_by_construction():
    # 篡改未来PE，检查历史月份策略输入不受影响：策略里记录看到的最大日期
    dates = ["2024-01-02", "2024-02-01", "2024-03-01"]
    price = _px(dates, [100, 100, 100])
    seen = []
    def spy(ctx):
        seen.append(ctx["signal_asof"]["date"].iloc[-1])
        return 1.0
    tampered = _px(dates, [10, 10, 999])
    run_backtest("t", "x", price, tampered, _px(["2024-01-01"], [2.0]), spy,
                 BacktestConfig(start="2024-01-01"))
    assert seen == ["2024-01-02", "2024-02-01", "2024-03-01"]  # 每月只见当月及以前
    assert max(seen) == "2024-03-01"


def test_measured_tracking_drag_math():
    from invest.backtest import measured_tracking_drag

    # 函数要求 >=60 个对齐样本且跨度 >=180 天；用 61 点 × 6 天间隔 = 360 天（≈1年，年化口径与断言对齐）
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2024-01-02", periods=61, freq="6D").strftime("%Y-%m-%d").tolist()

    class FakeStore:
        def read_series(self, code, kind):
            if kind == "fund_nav_cum":
                return _px(dates, list(np.linspace(1.0, 1.02, 61)))  # 期间 +2%
            return _px(dates, list(np.linspace(100.0, 104.0, 61)))  # 期间 +4%

    md = measured_tracking_drag(FakeStore(), "F", "T")
    assert md["basis"] == "累计净值"
    assert abs(md["fund_total_pct"] - 2.0) < 0.01
    assert abs(md["tr_total_pct"] - 4.0) < 0.01
    assert abs(md["annualized_pct"] - (-2.0)) < 0.15  # 年化差≈-2pct


def test_measured_drag_requires_history():
    from invest.backtest import measured_tracking_drag

    class ShortStore:
        def read_series(self, code, kind):
            return _px(["2024-01-0%d" % i for i in range(1, 6)], [1.0, 1.01, 1.02, 1.03, 1.04])

    assert measured_tracking_drag(ShortStore(), "F", "T") is None  # 历史不足→None
