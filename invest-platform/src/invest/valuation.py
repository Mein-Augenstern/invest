"""指数估值表（R1，蛋卷式）：主流中证指数 PE 分位看板。

产品定义（写死清单，非用户配置）：估值表覆盖的指数集合。
口径与既有基准估值一致：hist 长历史滚动 PE 计算分位（docs/03），value 接口交叉参考。
新增指数经 pull-data 自动沉淀（首次拉 2013 年起长历史，之后每日增量）。
"""
from __future__ import annotations

from . import metrics
from .data.local import LocalStore

# (名称, 中证代码)——宽基/红利/行业代表，产品视角圈定
VALUATION_TABLE_INDEXES: list[tuple[str, str]] = [
    ("沪深300", "000300"),
    ("中证500", "000905"),
    ("中证800", "000906"),
    ("中证1000", "000852"),
    ("中证红利", "000922"),
    ("中证红利低波", "H30269"),
    ("中证消费50", "931139"),
    ("中证医药", "000933"),
    ("中证科技", "931186"),
    ("中证新能源", "399808"),
]


def build_valuation_table(store: LocalStore) -> list[dict]:
    """各指数：收盘/PE/5y与全历史分位/股息率。无数据的指数也返回（前端显示待拉取）。"""
    rows: list[dict] = []
    for name, code in VALUATION_TABLE_INDEXES:
        close_df = store.read_series(code, "index_close")
        pe_df = store.read_series(code, "pe_ttm_hist")
        dy = store.latest(code, "dyield_1y")
        rows.append(
            {
                "name": name,
                "code": code,
                "close": float(close_df["close"].iloc[-1]) if not close_df.empty else None,
                "pe": float(pe_df["close"].iloc[-1]) if not pe_df.empty else None,
                "pct_5y": metrics.percentile_rank(pe_df, years=5),
                "pct_all": metrics.percentile_rank(pe_df, years=None),
                "dyield": dy[1] if dy else None,
                "ready": not pe_df.empty,
            }
        )
    return rows


def market_temperature(store: LocalStore) -> float | None:
    """市场温度（R2）：估值表指数 5y PE 分位等权平均 → 0-100。

    口径：等权（不按市值加权——个人视角的"贵/便宜"直觉更接近等权）；
    数据不足 5 个指数时返回 None（宁缺毋滥，不显示误导温度）。
    """
    rows = build_valuation_table(store)
    pcts = [r["pct_5y"] for r in rows if r["pct_5y"] is not None]
    if len(pcts) < 5:
        return None
    return round(sum(pcts) / len(pcts), 1)
