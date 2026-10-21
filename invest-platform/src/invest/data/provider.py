"""数据提供方协议与归一化。

约定：所有序列统一为 date(str YYYY-MM-DD) + close(float) 两列，去重升序。
估值类序列（PE/股息率）复用 close 列，kind 区分含义。
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd


def normalize(df: pd.DataFrame, date_col: str, close_col: str) -> pd.DataFrame:
    """原始 DataFrame → 统一 date/close 两列。"""
    out = df[[date_col, close_col]].copy()
    out.columns = ["date", "close"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna().drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)


class IndexValuation(dict):
    """中证官网指数估值：pe_static / pe_ttm / dyield_1y / dyield_3y 各一条序列。"""


class DataProvider(Protocol):
    """外部数据源协议：新增数据源实现本协议即可接入。"""

    def etf_daily(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        """ETF 日行情（东财前复权优先，新浪不复权兜底）。"""
        ...

    def fund_nav(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        """场外基金单位净值。"""
        ...

    def refresh_catalog(self) -> pd.DataFrame:
        """刷新中证指数目录，返回 index_code/name/full_name。"""
        ...

    def index_valuation(self, index_code: str) -> IndexValuation:
        """中证官网估值（近20个交易日，靠每日增量沉淀历史）。"""
        ...
