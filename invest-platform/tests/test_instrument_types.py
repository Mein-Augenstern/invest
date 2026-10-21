"""P9 品类扩展：类型校验、series_kind 映射、新品类记账与市值口径（全部 tmp 目录）。"""
import yaml

from invest import config as cfg
from invest.ledger.trades import Trade, load_trades
from invest.reporting import action_label, build_portfolio_view


def _write_conf(tmp_path, instruments):
    src = cfg.CONFIG_DIR / "portfolio.example.yaml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    raw["instruments"] = instruments
    p = tmp_path / "portfolio.local.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return cfg.load_config(p)


def test_series_kind_covers_all_types():
    for t in cfg.INSTRUMENT_TYPES:
        assert cfg.series_kind(t)
    assert cfg.series_kind("wealth") == "manual_nav"
    assert cfg.series_kind("stock") == "stock_daily"
    assert cfg.series_kind("bond") == "bond_daily"


def test_config_rejects_unknown_type(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="type 非法"):
        _write_conf(tmp_path, [{"id": "x", "type": "crypto", "name": "X"}])


def test_wealth_position_uses_manual_nav_as_price(tmp_path):
    """wealth 无 code：序列键回退 id，手工净值即市值。"""
    from invest.data.local import LocalStore
    import pandas as pd

    conf = _write_conf(tmp_path, [
        {"id": "bank_wealth_1", "type": "wealth", "name": "示例银行理财", "account": "bank"},
    ])
    store = LocalStore(tmp_path / "invest.db")
    store.upsert_series(
        "bank_wealth_1", "manual_nav",
        pd.DataFrame({"date": ["2026-10-17"], "close": [1.0234]}), source="manual",
    )
    trades = [
        Trade(date="2026-01-05", instrument_id="bank_wealth_1", action="buy", quantity=10000, price=1.0),
    ]
    view = build_portfolio_view(conf, store, trades, value_date="2026-10-17")
    row = view.rows[0]
    assert row.type == "wealth" and row.type_label == "理财/固收"
    assert row.state == "full"
    assert row.market_value == 10000 * 1.0234  # 10234.0
    assert row.unrealized == 234.0


def test_stock_position_uses_stock_daily(tmp_path):
    from invest.data.local import LocalStore
    import pandas as pd

    conf = _write_conf(tmp_path, [
        {"id": "sample_stock", "type": "stock", "name": "示例个股", "code": "600519", "account": "a_stock"},
    ])
    store = LocalStore(tmp_path / "invest.db")
    store.upsert_series(
        "600519", "stock_daily",
        pd.DataFrame({"date": ["2026-10-16"], "close": [1500.0]}), source="akshare",
    )
    trades = [Trade(date="2026-01-05", instrument_id="sample_stock", action="buy",
                    quantity=100, price=1400.0, fee=5.0)]
    view = build_portfolio_view(conf, store, trades, value_date="2026-10-17")
    row = view.rows[0]
    assert row.state == "full"
    assert row.market_value == 150000.0
    assert row.unrealized == 100 * 1500.0 - (100 * 1400.0 + 5.0)


def test_action_label_verbs_follow_type():
    assert action_label("buy", "stock") == "买入"
    assert action_label("sell", "bond") == "卖出"
    assert action_label("buy", "etf") == "买入"
    assert action_label("buy", "open_end_fund") == "申购"
    assert action_label("contribute", "wealth") == "缴存"
    assert action_label("dividend_reinvest", "stock") == "红利再投资"


def test_trades_csv_roundtrip_with_new_instrument(tmp_path):
    p = tmp_path / "trades.csv"
    p.write_text(
        "date,instrument_id,action,quantity,price,fee,note\n"
        "2026-10-17,bank_wealth_1,buy,20000,1.0,,示例理财按金额记份额\n",
        encoding="utf-8",
    )
    trades = load_trades(p)
    assert trades[0].instrument_id == "bank_wealth_1"
    assert trades[0].cash_flow == -20000.0
