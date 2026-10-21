"""reporting 视图模型与 markdown 渲染的合成 golden 测试。

真实数据的逐字节回归在重构当天用 data/golden/*.md diff 验证过；
本文件用合成数据锁定口径，防止后续改动悄悄变格式。
"""
from datetime import datetime

import pandas as pd

from invest import config as cfg
from invest.data.local import LocalStore
from invest.ledger.trades import Trade
from invest.reporting import (
    build_entry_state,
    build_portfolio_view,
    render_snapshot_markdown,
)


def _conf():
    return cfg.Portfolio(
        source="test.yaml",
        instruments=[
            cfg.Instrument(id="etf_b", type="etf", name="测试ETF", code="510000", account="a_stock"),
            cfg.Instrument(
                id="fund_a", type="open_end_fund", name="测试基金", code="022000",
                benchmark_index="中证测试", account="pension",
            ),
        ],
        accounts={
            "a_stock": cfg.Account(id="a_stock", name="A股账户"),
            "pension": cfg.Account(id="pension", name="养老金账户"),
        },
        strategy=cfg.StrategyConfig(),
    )


def _series(rows):
    return pd.DataFrame(rows, columns=["date", "close"])


def _store(tmp_path):
    store = LocalStore(tmp_path / "invest.db")
    store.upsert_catalog(pd.DataFrame([{"index_code": "999999", "name": "中证测试", "full_name": "中证测试指数"}]))
    store.upsert_series("999999", "index_close", _series([("2022-01-03", 100.0), ("2023-01-03", 120.0), ("2026-01-05", 90.0)]))
    store.upsert_series("999999", "pe_ttm_hist", _series([("2022-01-03", 10.0), ("2023-01-03", 12.0), ("2024-01-03", 14.0), ("2025-01-03", 16.0), ("2026-01-05", 12.0)]))
    store.upsert_series("999999", "dyield_1y", _series([("2026-01-05", 4.2)]))
    store.upsert_series("022000", "fund_nav", _series([("2026-01-05", 1.0), ("2027-01-05", 1.1)]))
    return store


TRADES = [
    Trade("2026-01-05", "fund_a", "buy", 10000, 1.0),
    Trade("2026-02-01", "fund_a", "contribute", 6000, 1.0),  # 账户入金6000元
]


def test_view_model_fields(tmp_path):
    view = build_portfolio_view(_conf(), _store(tmp_path), TRADES, value_date="2027-01-05")
    fund = next(r for r in view.rows if r.instrument_id == "fund_a")
    assert fund.state == "full"
    assert fund.quantity == 10000
    assert fund.price == 1.1 and fund.price_date == "2027-01-05"
    assert abs(fund.avg_cost - 1.0) < 1e-9
    assert fund.market_value == 11000.0
    assert fund.unrealized == 1000.0
    assert abs(fund.xirr - 0.10) < 1e-6  # 365天 10%
    etf = next(r for r in view.rows if r.instrument_id == "etf_b")
    assert etf.state == "empty"
    b = view.benchmarks[0]
    assert b.code == "999999" and b.close == 90.0 and b.pe_ttm == 12.0
    assert b.pct_all == 60.0 and abs(b.drawdown_5y - (90 / 120 - 1)) < 1e-9


def test_markdown_golden(tmp_path):
    view = build_portfolio_view(_conf(), _store(tmp_path), TRADES, value_date="2027-01-05")
    md = render_snapshot_markdown(view)
    lines = md.splitlines()
    assert lines[0] == "# 持仓快照 2027-01-05"
    assert "- 配置来源: `test.yaml`" in lines[2]
    assert "| 测试ETF | A股账户 | 0 | — | — | — | — | — | — | — |" in md
    assert (
        "| 测试基金 | 养老金账户 | 10,000 | 1.1000(2027-01-05) "
        "| 1.0000 | 11,000.00 | 1,000.00 | 0.00 | 0.00 | 10.00% |" in md
    )
    assert "**组合合计**：市值 11,000.00 元，浮动盈亏 1,000.00 元，组合 XIRR **10.00%**" in md
    assert "| 中证测试 | 999999 | 90 | 12.00 | 60% | 60% | 4.20% | -25.0% |" in md
    assert "相关系数" not in md  # 只有一个基准 → 无相关性行


def test_entry_state(tmp_path):
    state = build_entry_state(_conf(), _store(tmp_path), TRADES)
    fund = next(i for i in state["instruments"] if i["id"] == "fund_a")
    assert fund["quantity"] == 10000
    assert fund["avg_cost"] == 1.0
    assert fund["market_value"] == 11000.0
    assert fund["annual_cap"] == 12000.0
    # 缴存进度只统计 contribute 行（buy 不占年度额度）
    expected_contrib = 6000.0 if str(datetime.now().year) == "2026" else 0.0
    assert fund["year_contribution"] == expected_contrib
    assert fund["contribution_entered"] is True
    assert state["trades"][0]["action_label"] == "申购"
