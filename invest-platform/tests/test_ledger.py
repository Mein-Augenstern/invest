import pytest

from invest.ledger.ledger import avg_cost, build_positions, unrealized_pnl
from invest.ledger.trades import Trade, load_trades


def test_buy_sell_avg_cost():
    trades = [
        Trade("2025-01-10", "etf_a", "buy", 10000, 1.000, fee=5),
        Trade("2025-03-10", "etf_a", "buy", 10000, 1.200, fee=5),
        Trade("2025-06-10", "etf_a", "sell", 5000, 1.500, fee=5),
    ]
    pos = build_positions(trades)["etf_a"]
    assert pos.quantity == 15000
    # 总成本 10000*1.0 + 10000*1.2 + 10 = 22010，均价 1.1005；卖出不影响均价
    assert abs(avg_cost(pos) - 1.1005) < 1e-9
    # 已实现: 5000*(1.5-1.1005) - 5 = 1992.5
    assert abs(pos.realized_pnl - 1992.5) < 1e-6
    # @1.3 浮动: 15000*1.3 - (22010-5000*1.1005)
    assert abs(unrealized_pnl(pos, 1.3) - (19500 - 16507.5)) < 1e-6


def test_dividend_reinvest_adds_shares_no_cost_no_cashflow():
    trades = [
        Trade("2025-01-10", "fund_a", "buy", 10000, 1.000),
        Trade("2025-10-21", "fund_a", "dividend_reinvest", 211.5, 1.2900),
    ]
    pos = build_positions(trades)["fund_a"]
    assert abs(pos.quantity - 10211.5) < 1e-9
    assert abs(pos.cost - 10000.0) < 1e-9  # 成本不变 → 盈亏口径与基金App一致
    assert abs(trades[1].cash_flow) < 1e-12  # XIRR视角无现金流


def test_adjust_reconciles_shares():
    trades = [
        Trade("2025-01-10", "fund_a", "buy", 10000, 1.000),
        Trade("2025-06-10", "fund_a", "adjust", -67.99, 1.2500, note="与App对账校准"),
    ]
    pos = build_positions(trades)["fund_a"]
    assert abs(pos.quantity - 9932.01) < 1e-9
    assert abs(pos.cost - 10000.0) < 1e-9  # 校准不动成本
    assert abs(trades[1].cash_flow) < 1e-12  # 校准无现金流，不影响XIRR


def test_dividend_cash_accumulates():
    trades = [
        Trade("2025-01-10", "fund_a", "buy", 15000, 1.000),
        Trade("2025-06-10", "fund_a", "dividend_cash", 15000, 0.05),
        Trade("2025-12-10", "fund_a", "dividend_cash", 15000, 0.06),
    ]
    pos = build_positions(trades)["fund_a"]
    assert pos.quantity == 15000  # 现金分红不减份额
    assert abs(pos.cash_dividend - 1650.0) < 1e-9
    assert abs(avg_cost(pos) - 1.0) < 1e-9


def test_oversell_rejected():
    trades = [
        Trade("2025-01-10", "etf_a", "buy", 1000, 1.0),
        Trade("2025-02-10", "etf_a", "sell", 2000, 1.0),
    ]
    with pytest.raises(ValueError, match="卖出超过持仓"):
        build_positions(trades)


def test_load_trades_csv(tmp_path):
    csv_file = tmp_path / "trades.csv"
    csv_file.write_text(
        "date,instrument_id,action,quantity,price,fee,note\n"
        "2025-01-10,fund_a,buy,12000,1.05,0,养老金缴存\n",
        encoding="utf-8",
    )
    trades = load_trades(csv_file)
    assert len(trades) == 1
    assert trades[0].instrument_id == "fund_a"
    assert trades[0].cash_flow == -12600.0
