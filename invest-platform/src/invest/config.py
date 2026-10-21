"""配置加载：portfolio.local.yaml（真实，gitignore）优先，回退 example。

数据/配置目录支持环境变量覆盖（容器形态挂载用）：
- INVEST_DATA_DIR：账本/SQLite/报告目录（默认 <repo>/data）
- INVEST_CONFIG_DIR：portfolio 配置目录（默认 <repo>/config）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]  # invest-platform/
CONFIG_DIR = Path(os.environ.get("INVEST_CONFIG_DIR") or ROOT / "config")
DATA_DIR = Path(os.environ.get("INVEST_DATA_DIR") or ROOT / "data")


# 品类体系（P9 扩展）：记账层通用（买/卖/分红/XIRR），差异在行情来源
INSTRUMENT_TYPES = {"etf", "open_end_fund", "stock", "bond", "wealth"}
TYPE_LABELS = {
    "etf": "ETF",
    "open_end_fund": "场外基金",
    "stock": "股票",
    "bond": "债券",
    "wealth": "理财/固收",
}
# 各品类在 series 表中的行情序列 kind（wealth 为手工净值，`invest nav` 录入）
SERIES_KINDS = {
    "etf": "etf_daily",
    "open_end_fund": "fund_nav",
    "stock": "stock_daily",
    "bond": "bond_daily",
    "wealth": "manual_nav",
}


def series_kind(itype: str) -> str:
    try:
        return SERIES_KINDS[itype]
    except KeyError:
        raise ValueError(f"未知品类 {itype!r}（合法值: {sorted(INSTRUMENT_TYPES)}）") from None


@dataclass
class Instrument:
    id: str
    type: str  # INSTRUMENT_TYPES 之一；wealth=银行理财/存款等无公开行情品种
    name: str
    code: str = ""  # 交易/基金代码，未填则跳过行情拉取（wealth 常为空，序列键回退 id）
    benchmark_index: str = ""  # 估值基准指数名称
    benchmark_tr_code: str = ""  # 基准全收益指数代码（如中证红利H00922，回测用）
    account: str = ""


@dataclass
class Account:
    id: str
    name: str
    tax_note: str = ""


DEFAULT_ZONES: list[tuple[float, float, float]] = [
    (0, 20, 2.0), (20, 50, 1.5), (50, 70, 1.0), (70, 85, 0.5), (85, 101, 0.0),
]


@dataclass
class StrategyConfig:
    """策略参数（与规则书 docs/business/strategy-rules.md 对应，改参数先改规则书）。"""

    base_monthly_invest: float = 2000.0
    percentile_windows_years: int = 5
    zones: list[tuple[float, float, float]] = field(default_factory=lambda: list(DEFAULT_ZONES))
    pension_annual_cap: float = 12000.0
    rebalance_deviation_pct: float = 10.0
    target_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class Portfolio:
    source: str  # 使用的配置文件名（提示当前是示例还是真实配置）
    instruments: list[Instrument]
    accounts: dict[str, Account]
    strategy: StrategyConfig = field(default_factory=StrategyConfig)


def load_config(path: Path | None = None) -> Portfolio:
    """真实配置 portfolio.local.yaml 不存在时回退示例，快照会提示待填字段。"""
    src = path or (CONFIG_DIR / "portfolio.local.yaml")
    if not src.exists():
        src = CONFIG_DIR / "portfolio.example.yaml"
    raw: dict[str, Any] = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    instruments = [Instrument(**i) for i in raw.get("instruments", [])]
    for ins in instruments:
        if ins.type not in INSTRUMENT_TYPES:
            raise ValueError(f"instrument {ins.id}.type 非法: {ins.type!r}（合法值: {sorted(INSTRUMENT_TYPES)}）")
    accounts = {a["id"]: Account(**a) for a in raw.get("accounts", [])}
    s = raw.get("strategy") or {}
    zones = [(z[0], z[1], float(z[2])) for z in s.get("zones", [])] or list(DEFAULT_ZONES)
    strategy = StrategyConfig(
        base_monthly_invest=float(s.get("base_monthly_invest", 2000.0)),
        percentile_windows_years=int(s.get("percentile_windows_years", 5)),
        zones=zones,
        pension_annual_cap=float(s.get("pension_annual_cap", 12000.0)),
        rebalance_deviation_pct=float(s.get("rebalance_deviation_pct", 10.0)),
        target_weights=dict(s.get("target_weights", {})),
    )
    return Portfolio(
        source=src.name, instruments=instruments, accounts=accounts, strategy=strategy
    )
