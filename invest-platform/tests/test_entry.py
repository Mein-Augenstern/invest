from invest import config as cfg
from invest.entry_server import append_trade, delete_trade, validate_trade
from invest.ledger.trades import Trade, load_trades


def _conf():
    return cfg.Portfolio(
        source="test",
        instruments=[
            cfg.Instrument(id="fund_a", type="open_end_fund", name="红利Y", account="pension"),
            cfg.Instrument(id="etf_b", type="etf", name="消费50ETF", account="a_stock"),
        ],
        accounts={"pension": cfg.Account(id="pension", name="养老金")},
    )


def test_append_and_delete_roundtrip(tmp_path):
    csv_file = tmp_path / "trades.csv"
    trade = {
        "date": "2026-01-05", "instrument_id": "fund_a", "action": "buy",
        "quantity": "11753.94", "price": "1.0215", "fee": "", "note": "年度缴存",
    }
    append_trade(csv_file, trade)
    trades = load_trades(csv_file)
    assert len(trades) == 1
    assert trades[0].instrument_id == "fund_a"
    assert abs(trades[0].quantity - 11753.94) < 1e-9

    # 按整行内容删除成功；再删同内容返回 False
    assert delete_trade(csv_file, trade) is True
    assert delete_trade(csv_file, trade) is False
    assert load_trades(csv_file) == []


def test_validate_trade_rejects_bad_input():
    conf = _conf()
    base = {"instrument_id": "fund_a", "action": "buy", "date": "2026-01-05",
            "quantity": 1000, "price": 1.0, "fee": 0, "note": ""}

    ok, err = validate_trade(base, conf, [])
    assert err == "" and ok["instrument_id"] == "fund_a"

    _, err = validate_trade({**base, "instrument_id": "nope"}, conf, [])
    assert err == "未知标的"
    _, err = validate_trade({**base, "date": "2026/01/05"}, conf, [])
    assert "日期格式" in err
    _, err = validate_trade({**base, "quantity": -1}, conf, [])
    assert "正数" in err


def test_validate_trade_rejects_oversell():
    conf = _conf()
    existing = [Trade("2026-01-05", "fund_a", "buy", 1000, 1.0)]
    _, err = validate_trade(
        {"instrument_id": "fund_a", "action": "sell", "date": "2026-06-01",
         "quantity": 2000, "price": 1.1, "fee": 0, "note": ""},
        conf, existing,
    )
    assert "赎回超过持仓" in err and "1,000" in err
