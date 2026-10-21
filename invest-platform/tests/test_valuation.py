"""R1/R2 估值表与市场温度：分位计算复用 metrics 口径，无数据指数优雅降级。"""
import pandas as pd

from invest.data.local import LocalStore
from invest.valuation import VALUATION_TABLE_INDEXES, build_valuation_table, market_temperature


def _seed(store: LocalStore, code: str, dates, pes, closes=None):
    store.upsert_series(code, "pe_ttm_hist", pd.DataFrame({"date": dates, "close": pes}), source="test")
    if closes:
        store.upsert_series(code, "index_close", pd.DataFrame({"date": dates, "close": closes}), source="test")


def test_valuation_table_shapes_and_missing(tmp_path):
    store = LocalStore(tmp_path / "invest.db")
    dates = [f"2026-01-{d:02d}" for d in range(1, 21)]
    _seed(store, "000300", dates, [10.0 + i * 0.1 for i in range(20)])
    rows = build_valuation_table(store)
    assert len(rows) == len(VALUATION_TABLE_INDEXES)
    hs = next(r for r in rows if r["code"] == "000300")
    assert hs["ready"] is True
    assert abs(hs["pe"] - 11.9) < 1e-9
    assert hs["pct_5y"] == 100.0  # 持续走高 → 最新值是最贵
    # 未拉取的指数：ready=False、分位 None
    miss = next(r for r in rows if r["code"] == "931186")
    assert miss["ready"] is False and miss["pct_5y"] is None and miss["pe"] is None


def test_market_temperature_requires_enough_indexes(tmp_path):
    store = LocalStore(tmp_path / "invest.db")
    dates = [f"2026-01-{d:02d}" for d in range(1, 21)]
    # 只种 3 个 → 数据不足，温度 None
    for code in ["000300", "000905", "000906"]:
        _seed(store, code, dates, [10 + i * 0.1 for i in range(20)])
    assert market_temperature(store) is None
    # 种满 5 个 → 等权平均分位
    for code in ["000922", "000852"]:
        _seed(store, code, dates, [20 - i * 0.1 for i in range(20)])  # 走低 → 分位 5%（含自身 1/20）
    t = market_temperature(store)
    assert t == 62.0  # 3 个 100 + 2 个 5 → 等权 62
