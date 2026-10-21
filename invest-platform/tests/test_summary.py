"""L2 月度收益统计：恒等式对账（Δ市值 = 净投入 + 浮盈变化）与月度现金流口径。"""
import pandas as pd

from invest import config as cfg
from invest.ledger.trades import Trade
from invest.reporting_summary import build_monthly_summary


def _conf(tmp_path):
    import yaml

    src = cfg.CONFIG_DIR / "portfolio.example.yaml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    raw["instruments"] = [{"id": "fund_a", "type": "open_end_fund", "name": "基金A", "code": "F1"}]
    p = tmp_path / "portfolio.local.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return cfg.load_config(p)


def _seed_nav(store, dates, closes, key="F1", kind="fund_nav"):
    store.upsert_series(key, kind, pd.DataFrame({"date": dates, "close": closes}), source="test")


def test_monthly_identity_and_flows(tmp_path):
    """单基金两月场景：投入1000@1.0 → 次月涨到1.1 → 再投500@1.1 → 月末市值与浮盈变化核对。"""
    from invest.data.local import LocalStore

    conf = _conf(tmp_path)
    store = LocalStore(tmp_path / "invest.db")
    _seed_nav(
        store,
        ["2026-01-05", "2026-01-31", "2026-02-10", "2026-02-28"],
        [1.0, 1.0, 1.1, 1.1],
    )
    trades = [
        Trade(date="2026-01-05", instrument_id="fund_a", action="buy", quantity=1000, price=1.0),
        Trade(date="2026-02-10", instrument_id="fund_a", action="buy", quantity=454.55, price=1.1),
    ]
    out = build_monthly_summary(conf, store, trades, months=6)
    rows = {r["month"]: r for r in out["months"]}

    jan = rows["2026-01"]
    assert jan["net_invested"] == 1000.0
    assert jan["market_value"] == 1000.0  # 1000份 × 1.0
    assert jan["pnl_change"] == 0.0

    feb = rows["2026-02"]
    # 月初市值 1000（1月遗留），当月净投入 454.55×1.1≈500.0，月末市值 = 1454.55份 × 1.1
    assert abs(feb["net_invested"] - 500.0) < 0.1
    assert abs(feb["market_value"] - 1454.55 * 1.1) < 0.5  # ≈1600.0
    # 恒等式：浮盈变化 = 月末 − 月初 − 净投入 = 1600 − 1000 − 500 = 100（1月买的1000份涨了10%）
    assert abs(feb["pnl_change"] - 100.0) < 0.5

    # 年度汇总
    y = out["years"][0]
    assert y["year"] == "2026"
    assert abs(y["net_invested"] - 1500.0) < 0.1
    assert abs(y["pnl_change"] - 100.0) < 0.5


def test_sell_and_dividend_flows(tmp_path):
    from invest.data.local import LocalStore

    conf = _conf(tmp_path)
    store = LocalStore(tmp_path / "invest.db")
    _seed_nav(store, ["2026-01-05", "2026-01-31", "2026-02-20", "2026-02-28"], [1.0, 1.0, 1.2, 1.2])
    trades = [
        Trade(date="2026-01-05", instrument_id="fund_a", action="buy", quantity=1000, price=1.0),
        Trade(date="2026-02-20", instrument_id="fund_a", action="sell", quantity=500, price=1.2, fee=2.0),
        Trade(date="2026-02-20", instrument_id="fund_a", action="dividend_cash", quantity=500, price=0.05),
    ]
    out = build_monthly_summary(conf, store, trades, months=6)
    feb = {r["month"]: r for r in out["months"]}["2026-02"]
    assert abs(feb["returned"] - (500 * 1.2 - 2.0)) < 1e-6  # 赎回净回款
    assert abs(feb["cash_div"] - 25.0) < 1e-6
    # 已实现：500份成本500，卖得598 → +98
    assert abs(feb["realized"] - 98.0) < 1e-6


def test_empty_trades(tmp_path):
    from invest.data.local import LocalStore

    conf = _conf(tmp_path)
    store = LocalStore(tmp_path / "invest.db")
    out = build_monthly_summary(conf, store, [], months=6)
    assert out == {"months": [], "years": []}


def test_contribute_is_cashflow_not_shares(tmp_path):
    """回归（真实数据抓出）：contribute=账户缴存入金，计入净投入但不折基金份额——
    曾被当卖出扣份额，导致月末市值虚低 8000（缴存额）。"""
    from invest.data.local import LocalStore

    conf = _conf(tmp_path)
    store = LocalStore(tmp_path / "invest.db")
    _seed_nav(store, ["2026-01-05", "2026-01-31", "2026-02-10", "2026-02-28"], [1.0, 1.0, 1.25, 1.25])
    trades = [
        Trade(date="2026-01-05", instrument_id="fund_a", action="contribute", quantity=2000, price=1.0),
        Trade(date="2026-01-05", instrument_id="fund_a", action="buy", quantity=2000, price=1.0),
        Trade(date="2026-02-10", instrument_id="fund_a", action="contribute", quantity=8000, price=1.0),
        Trade(date="2026-02-10", instrument_id="fund_a", action="buy", quantity=6400, price=1.25),
    ]
    out = build_monthly_summary(conf, store, trades, months=6)
    rows = {r["month"]: r for r in out["months"]}
    feb = rows["2026-02"]
    # 2月末持仓 = 2000 + 6400 = 8400 份 × 1.25 = 10500（contribute 不加份额）
    assert abs(feb["market_value"] - 10500.0) < 1e-6
    # 1月净投入 = contribute 2000 + buy 2000 = 4000；2月 = 8000 + 6400×1.25 = 16000
    assert abs(rows["2026-01"]["net_invested"] - 4000.0) < 1e-6
    assert abs(feb["net_invested"] - 16000.0) < 1e-6
