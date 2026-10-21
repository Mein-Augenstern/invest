"""JSON API（变更操作全部 POST + JSON body；无 CORS 头=预检必失败，天然防跨站）。"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from .deps import get_conf, get_data_dir, get_store, get_trades_path
from ..ledger.trades import delete_trade, load_trades, save_validated_trade
from ..reporting import build_entry_state

router = APIRouter(prefix="/api")


@router.get("/ping")
def ping() -> dict:
    return {"ok": True}


@router.get("/state")
def state(conf=Depends(get_conf), store=Depends(get_store), trades_path=Depends(get_trades_path)) -> dict:
    return build_entry_state(conf, store, load_trades(trades_path))


@router.post("/trades")
def add_trade(
    payload: dict = Body(...),
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades_path=Depends(get_trades_path),
) -> dict:
    trade, err = save_validated_trade(trades_path, payload, conf, load_trades(trades_path))
    if err:
        return JSONResponse({"error": err}, status_code=422)
    return {"ok": True, "trade": trade, "state": build_entry_state(conf, store, load_trades(trades_path))}


@router.post("/trades/delete")
def delete_trade_api(
    payload: dict = Body(...),
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades_path=Depends(get_trades_path),
):
    row = payload.get("row") or {}
    if not delete_trade(trades_path, row):
        return JSONResponse({"error": "未找到该行（列表可能已变化），请刷新"}, status_code=409)
    return {"ok": True, "state": build_entry_state(conf, store, load_trades(trades_path))}


@router.post("/signals/evaluate")
def evaluate_signals(conf=Depends(get_conf), store=Depends(get_store), trades_path=Depends(get_trades_path)) -> dict:
    """显式动作：评估策略规则并落库新信号（页面刷新不触发）。"""
    from ..reporting import evaluate_and_store_signals

    new_count = evaluate_and_store_signals(conf, store, load_trades(trades_path))
    return {"ok": True, "new": new_count}


@router.post("/signals/{sid}/status")
def signal_status(sid: int, payload: dict = Body(...), store=Depends(get_store)):
    status = str(payload.get("status", ""))
    if status not in ("已确认", "已忽略", "建议"):
        return JSONResponse({"error": "非法状态"}, status_code=422)
    if not store.update_signal_status(sid, status):
        return JSONResponse({"error": "信号不存在"}, status_code=404)
    return {"ok": True, "id": sid, "status": status}


@router.post("/pull")
def start_pull(request: Request, data_dir=Depends(get_data_dir)) -> dict:
    """触发后台拉数（分钟级网络任务，前端轮询 /api/pull/status）。"""
    from . import pulljob

    ok, err = pulljob.start_pull(data_dir, request.app.state.config_path)
    if not ok:
        return JSONResponse({"error": err}, status_code=409)
    return {"ok": True}


@router.get("/pull/status")
def pull_status() -> dict:
    from . import pulljob

    return pulljob.status()


@router.post("/reports/generate")
def generate_report(
    payload: dict = Body(default={}),
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades_path=Depends(get_trades_path),
    data_dir=Depends(get_data_dir),
):
    """同步生成周报（单用户可接受；GLM 60s 上限由 digest 内部控制）。"""
    from datetime import datetime
    from pathlib import Path

    from ..reporting import build_weekly_report_md

    report = build_weekly_report_md(conf, store, load_trades(trades_path), with_ai=bool(payload.get("ai")))
    out_dir = Path(data_dir) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"weekly-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    (out_dir / name).write_text(report, encoding="utf-8")
    return {"ok": True, "file": name}


@router.post("/backtest")
def run_backtest_api(
    payload: dict = Body(default={}),
    conf=Depends(get_conf),
    store=Depends(get_store),
    data_dir=Depends(get_data_dir),
):
    """网页触发回测（秒级，同步返回；跑批与CLI共用 run_all_backtests）。"""
    from datetime import datetime
    from pathlib import Path as _Path

    from ..backtest import STRATEGY_DOCS, render_backtest_markdown, run_all_backtests
    from ..reporting import _to_ms

    out = run_all_backtests(
        conf, store,
        start=str(payload.get("start", "2013-06-03")),
        monthly=float(payload.get("monthly", 1000)),
        drag=float(payload.get("drag", 0) or 0),
        codes=payload.get("codes") or None,
    )
    if out.get("missing"):
        return JSONResponse({"error": out["missing"]}, status_code=422)

    results = []
    for r in out["results"]:
        eq = r.equity.copy()
        eq["ratio"] = (eq["value"] / eq["invested"]).where(eq["invested"] > 0)
        eq = eq.dropna(subset=["ratio"])
        step = max(1, len(eq) // 300)
        eq = eq.iloc[::step].copy()
        if not eq.empty and eq.index[-1] != r.equity.index[-1]:
            last_ratio = (r.equity["value"].iloc[-1] / r.equity["invested"].iloc[-1]
                          if r.equity["invested"].iloc[-1] > 0 else None)
            if last_ratio is not None:
                eq.loc[r.equity.index[-1], "ratio"] = last_ratio
        results.append(
            {
                "code": getattr(r, "code", ""),
                "name": r.name,
                "params": r.params,
                "desc": STRATEGY_DOCS.get(getattr(r, "code", ""), ""),
                "metrics": r.metrics,
                "curve": [[_to_ms(d), round(v, 3)] for d, v in zip(eq["date"], eq["ratio"])],
                "orders_preview": r.orders[:3] + r.orders[-3:],
            }
        )

    # 归档一份 Markdown 报告
    md = render_backtest_markdown(out["results"], out["cfg"], out["span"])
    reports = _Path(data_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"backtest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(md, encoding="utf-8")

    return {
        "ok": True,
        "span": out["span"],
        "div_yield_now": out["div_yield_now"],
        "results": results,
    }


import pandas as pd  # noqa: E402  (供上面对账曲线处理使用)
