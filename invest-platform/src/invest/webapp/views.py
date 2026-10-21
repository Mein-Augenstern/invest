"""视图组装层：只调 reporting/领域层 + 少量表单态；禁止在此做 pandas 计算。"""
from __future__ import annotations

from pathlib import Path

from ..ledger.trades import load_trades
from ..reporting import (
    build_dashboard_data,
    build_entry_state,
    build_instrument_view,
    build_portfolio_view,
    build_strategy_view,
)


def _load(data_dir: Path):
    return load_trades(Path(data_dir) / "trades.csv")


def index_context(conf, store, data_dir: Path) -> dict:
    trades = _load(data_dir)
    view = build_portfolio_view(conf, store, trades)
    name_of = {i.id: i.name for i in conf.instruments}

    def _sig_rows(rows):
        return [
            {
                "id": s[0], "date": s[1], "instrument": name_of.get(s[2], s[2]),
                "rule": s[3], "metric": s[4], "value": s[5], "action": s[6], "status": s[7],
            }
            for s in rows
        ][::-1]

    # 总览只显示活跃"建议"；无活跃时回退显示最近几条（含已忽略，避免空区块误导）
    signals = _sig_rows(store.recent_signals(limit=5, status="建议")) or _sig_rows(store.recent_signals(limit=3))
    chart_data = {"holdings": build_dashboard_data(conf, store, trades)["holdings"]}
    return {"view": view, "signals": signals, "chart_data": chart_data}


def positions_context(conf, store, data_dir: Path) -> dict:
    trades = _load(data_dir)
    view = build_portfolio_view(conf, store, trades)
    dash = build_dashboard_data(conf, store, trades)
    return {"view": view, "chart_data": {"cmp": dash["cmp"]}}


def instrument_context(conf, store, data_dir: Path, instrument_id: str) -> dict | None:
    data = build_instrument_view(conf, store, _load(data_dir), instrument_id)
    return {"d": data} if data else None


def trades_context(conf, store, data_dir: Path) -> dict:
    state = build_entry_state(conf, store, _load(data_dir))
    return {"state": state}


def signals_context(conf, store) -> dict:
    name_of = {i.id: i.name for i in conf.instruments}
    signals = [
        {
            "id": s[0], "date": s[1], "instrument": name_of.get(s[2], s[2]),
            "rule": s[3], "metric": s[4], "value": s[5], "action": s[6], "status": s[7],
        }
        for s in store.recent_signals(limit=20)
    ][::-1]
    return {"signals": signals}


def reports_context(data_dir: Path) -> dict:
    from datetime import datetime

    reports_dir = Path(data_dir) / "reports"
    files = []
    if reports_dir.exists():
        for p in sorted(reports_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
            st = p.stat()
            files.append(
                {
                    "name": p.name,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "size_kb": round(st.st_size / 1024, 1),
                }
            )
    return {"reports": files}


def strategy_context(conf, store, data_dir: Path) -> dict:
    return {"cards": build_strategy_view(conf, store, _load(data_dir))}


def settings_context(conf) -> dict:
    import os

    zones = [
        {"lo": z[0], "hi": z[1], "mult": z[2]} for z in conf.strategy.zones
    ]
    return {
        "conf": conf,
        "zones": zones,
        "glm_key_set": bool(os.environ.get("INVEST_GLM_API_KEY")),
        "glm_model": os.environ.get("INVEST_GLM_MODEL", "glm-5.3"),
    }


def backtest_context(conf, store) -> dict:
    from ..backtest import STRATEGY_DOCS, measured_tracking_drag

    drag_options = [{"value": 0, "label": "0%（理想指数）"}]
    drag_note = "费用事实（实测）：Y份额申购费 0、持有满7天赎回费 0；领取环节3%个税与缴存抵扣属账户层政策，不在年化损耗内。"
    md = None
    ins = next((i for i in conf.instruments if i.benchmark_tr_code and i.code), None)
    if ins:
        md = measured_tracking_drag(store, ins.code, ins.benchmark_tr_code)
    if md:
        drag_options.append({
            "value": round(abs(md["annualized_pct"]) / 100, 4),
            "label": f"实测跟踪差 {abs(md['annualized_pct']):.2f}%/年（{ins.code}累计净值 vs 全收益指数）",
            "selected": True,
        })
        drag_options[0]["selected"] = False
        drag_note = (f"实测口径：{md['period']}（{md['days']}天），基金累计净值 {md['fund_total_pct']:+.2f}% vs "
                     f"指数 {md['tr_total_pct']:+.2f}%，年化差 {md['annualized_pct']:+.2f}pct——含费率/现金缓冲/跟踪净效果，随净值数据自动更新。" + drag_note)
    else:
        drag_options.append({"value": 0.01, "label": "1%/年（很保守）"})
    drag_options.append({"value": 0.01, "label": "1%/年（很保守）"}) if md else None

    catalog = [
        {"code": "dca", "name": "无脑定投", "desc": STRATEGY_DOCS["dca"]},
        {"code": "lumpsum", "name": "期初一次性", "desc": STRATEGY_DOCS["lumpsum"]},
        {"code": "value_dca", "name": "估值增强定投", "desc": STRATEGY_DOCS["value_dca"]},
        {"code": "div_spread", "name": "股息率利差", "desc": STRATEGY_DOCS["div_spread"]},
        {"code": "ma_trend", "name": "年线择时定投", "desc": STRATEGY_DOCS["ma_trend"]},
        {"code": "ep_spread", "name": "股债利差·E/P", "desc": STRATEGY_DOCS["ep_spread"]},
    ]
    presets = [
        ("2013-06-03", "全程13年（含2015股灾/2018熊市）"),
        ("2016-01-01", "近10年"),
        ("2019-01-01", "近7年（疫情后）"),
        ("2021-01-01", "近5年（红利强势期）"),
    ]
    return {"catalog": catalog, "presets": presets, "drag_options": drag_options, "drag_note": drag_note}
