"""数据拉取管线（CLI pull-data 与 Web 设置页共用，唯一实现）。"""
from __future__ import annotations

from . import config as cfg
from .data.local import LocalStore


def _tail(df) -> str:
    if df is None or getattr(df, "empty", True):
        return "EMPTY"
    last = df.iloc[-1]
    return f"rows={len(df)}, last={last['date']} close={last['close']}"


def run_pull(conf, store: LocalStore, provider, log=print, start: str = "2015-01-01") -> None:
    """刷新指数目录 → 标的行情/净值 → 基准指数估值（每日增量沉淀历史）。"""
    store.upsert_catalog(provider.refresh_catalog())
    log("中证指数目录已刷新")

    for ins in conf.instruments:
        if ins.type == "wealth":
            log(f"[SKIP] {ins.name}: 理财/固收无公开行情，用 `invest nav` 录入净值")
        elif not ins.code:
            log(f"[SKIP] {ins.name}: 未配置代码（config/portfolio.local.yaml 的 code 字段）")
        elif ins.type == "etf":
            df = provider.etf_daily(ins.code, start=start)
            store.upsert_series(ins.code, "etf_daily", df, source="akshare")
            log(f"[OK] {ins.name} 行情: {_tail(df)}")
        elif ins.type == "stock":
            df = provider.stock_daily(ins.code, start=start)
            store.upsert_series(ins.code, "stock_daily", df, source="akshare")
            log(f"[OK] {ins.name} 行情: {_tail(df)}")
        elif ins.type == "bond":
            df = provider.bond_daily(ins.code, start=start)
            store.upsert_series(ins.code, "bond_daily", df, source="akshare")
            log(f"[OK] {ins.name} 行情: {_tail(df)}")
        elif ins.type == "open_end_fund":
            df = provider.fund_nav(ins.code, start=start)
            store.upsert_series(ins.code, "fund_nav", df, source="akshare")
            log(f"[OK] {ins.name} 净值: {_tail(df)}")
            try:
                cum = provider.fund_nav_cumulative(ins.code, start=start)
                store.upsert_series(ins.code, "fund_nav_cum", cum, source="akshare")
                log(f"[OK] {ins.name} 累计净值: {_tail(cum)}")
            except Exception as e:  # noqa: BLE001
                log(f"[WARN] {ins.name} 累计净值拉取失败: {type(e).__name__}")

    seen: set[str] = set()
    for ins in conf.instruments:
        name = ins.benchmark_index
        if not name or name in seen:
            continue
        seen.add(name)
        code = store.resolve_index_code(name)
        if not code:
            log(f"[WARN] {name}: 中证目录未检索到对应指数代码")
            continue
        try:
            val = provider.index_valuation(code)
            for key, df in val.items():
                store.upsert_series(code, key, df, source="csindex-value")
            long_hist = provider.index_price_pe(code)
            for key, df in long_hist.items():
                store.upsert_series(code, key, df, source="csindex-hist")
            summary = "; ".join(
                f"{k}={v.iloc[-1]['close']}" for k, v in {**val, **long_hist}.items() if not v.empty
            )
            log(f"[OK] {name}({code}) 估值: {summary}")
        except Exception as e:  # noqa: BLE001 - 单个指数失败不阻断整体
            log(f"[WARN] {name} 估值拉取失败: {type(e).__name__}: {e}")

    # 3b) 估值表指数集（R1）：主流宽基/红利/行业指数长历史沉淀（产品定义清单，见 valuation.py）
    from .valuation import VALUATION_TABLE_INDEXES

    for vname, vcode in VALUATION_TABLE_INDEXES:
        try:
            long_hist = provider.index_price_pe(vcode)
            for key, df in long_hist.items():
                store.upsert_series(vcode, key, df, source="csindex-hist")
            val = provider.index_valuation(vcode)
            for key, df in val.items():
                store.upsert_series(vcode, key, df, source="csindex-value")
            pe_now = long_hist["pe_ttm_hist"].iloc[-1]["close"] if not long_hist["pe_ttm_hist"].empty else "n/a"
            log(f"[OK] 估值表 {vname}({vcode}): pe={pe_now}")
        except Exception as e:  # noqa: BLE001 - 单个指数失败不阻断整体
            log(f"[WARN] 估值表 {vname}({vcode}) 拉取失败: {type(e).__name__}")

    # 4) 基金透视（季报前十大重仓+行业配置，源：基金定期报告）
    year = __import__("datetime").datetime.now().strftime("%Y")
    for ins in conf.instruments:
        if ins.type != "open_end_fund" or not ins.code:
            continue
        try:
            holds = provider.fund_holdings(ins.code, year)
            for period, rows in holds.items():
                store.upsert_fund_holdings(ins.code, period, rows)
            log(f"[OK] {ins.name} 重仓股: {sum(len(v) for v in holds.values())}行({len(holds)}期)")
            rdate, ind_rows = provider.fund_industry(ins.code, year)
            if rdate:
                store.upsert_fund_industry(ins.code, rdate, ind_rows)
                log(f"[OK] {ins.name} 行业配置: {len(ind_rows)}行({rdate})")
        except Exception as e:  # noqa: BLE001
            log(f"[WARN] {ins.name} 透视拉取失败: {type(e).__name__}: {e}")

    # 5) 回测数据：10Y国债收益率 + 基准全收益指数
    try:
        bond = provider.bond_yield_10y()
        store.upsert_series("CN10Y", "bond_yield", bond, source="chinabond")
        log(f"[OK] 中国10Y国债收益率: {_tail(bond)}")
    except Exception as e:  # noqa: BLE001
        log(f"[WARN] 国债收益率拉取失败: {type(e).__name__}: {e}")
    for ins in conf.instruments:
        if not ins.benchmark_tr_code:
            continue
        try:
            tr = provider.index_price_pe(ins.benchmark_tr_code)
            for key, df in tr.items():
                store.upsert_series(ins.benchmark_tr_code, "tr_close" if key == "index_close" else key, df, source="csindex-hist")
            log(f"[OK] {ins.name} 全收益指数({ins.benchmark_tr_code}): {_tail(tr['index_close'])}")
        except Exception as e:  # noqa: BLE001
            log(f"[WARN] 全收益指数拉取失败: {type(e).__name__}: {e}")
