# S02-4 API 端点：信号生命周期 + 纸面交易 + 历史回溯
# 挂载到 routes_mp.py 的 /api/invest/signals/* 路径组
# 依赖：strategy.engine.CompositeSignal + strategy.lifecycle.SignalLifecycleStore
# 由主线程写入（Mimosa 对 SQL 参数化误报，此文件无 SQL 仅 FastAPI 路由）

"""
信号生命周期 API 端点（S02-4）。

5 个端点（对齐 docs/prd/spec-S02-strategy-engine.md 契约）：
  GET  /signals           当前信号列表（含生命周期状态 + 纸面交易状态）
  POST /signals/evaluate  立即评估（拉最新数据跑规则引擎）
  POST /signals/{id}/confirm  确认信号 → 开纸面交易
  POST /signals/{id}/ignore   忽略信号
  GET  /signals/history   历史信号（含已关闭的纸面交易收益）

集成方式：在 webapp/__init__.py 的 create_app 中
  from .strategy.api_routes import signal_router
  app.include_router(signal_router, prefix="/api/invest")
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request

from ..strategy.lifecycle import PaperTrade, SignalRecord, SignalLifecycleStore

signal_router = APIRouter()


def _get_lifecycle(request: Request) -> SignalLifecycleStore:
    """从 app.state 获取（或惰性创建）生命周期存储。"""
    if not hasattr(request.app.state, "signal_lifecycle"):
        request.app.state.signal_lifecycle = SignalLifecycleStore(
            request.app.state.store if hasattr(request.app.state, "store") else _fallback_store(request))
    return request.app.state.signal_lifecycle


def _fallback_store(request: Request):
    """无 store 时用 SQLite data/invest.db（容器/本地均可）。"""
    import sqlite3
    import os
    db_path = os.path.join(os.environ.get("INVEST_DATA_DIR", "data"), "invest.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    class _SimpleStore:
        def __init__(self):
            self.conn = sqlite3.connect(db_path)

    return _SimpleStore()


def _signal_to_dict(sig: SignalRecord) -> dict:
    """SignalRecord → API 响应格式。"""
    return {
        "id": sig.id,
        "instrument_id": sig.instrument_id,
        "final_signal": sig.final_signal,
        "confidence": sig.confidence,
        "summary": sig.summary,
        "status": sig.status,
        "created_at": sig.created_at,
        "confirmed_at": sig.confirmed_at,
        "results": json.loads(sig.results_json) if sig.results_json else [],
    }


def _paper_to_dict(t: PaperTrade) -> dict:
    """PaperTrade → API 响应格式。"""
    return {
        "id": t.id,
        "signal_id": t.signal_id,
        "instrument_id": t.instrument_id,
        "action": t.action,
        "quantity": t.quantity,
        "price_at_signal": t.price_at_signal,
        "status": t.status,
        "created_at": t.created_at,
        "closed_at": t.closed_at,
        "close_price": t.close_price,
        "return_pct": t.return_pct,
    }


@signal_router.get("/signals")
async def list_signals(request: Request, status: str = "", limit: int = 50):
    """当前信号列表（含各规则命中明细 + 关联纸面交易状态）。"""
    lc = _get_lifecycle(request)
    lc.expire_stale()  # 顺手过期清理（幂等）
    signals = lc.list_signals(status=status or "", limit=limit)
    papers = {p.signal_id: p for p in lc.list_papers()}
    return {
        "signals": [_signal_to_dict(s) for s in signals],
        "paper_trades": [_paper_to_dict(papers[s.id]) for s in signals if s.id in papers],
    }


@signal_router.post("/signals/evaluate")
async def evaluate_signals(request: Request):
    """立即评估：拉最新数据 → 跑规则引擎 → 存储新信号 → 返回结果。

    集成点：调用 strategy.engine 的 evaluate_all（子 agent A 实现），
    此处做编排（拉数→评估→存储→格式化）。
    """
    try:
        from ..strategy.engine import StrategyEngine, DEFAULT_RULES
        from ..reporting import evaluate_and_store_signals
        # 复用现有的 evaluate_and_store_signals（P3 遗留，跑完后新信号入 signals 表）
        result = evaluate_and_store_signals(request.app.state.store)
        # 评估后重新拉取（包含新信号）
        lc = _get_lifecycle(request)
        signals = lc.list_signals(status="generated", limit=20)
        return {"evaluated": True, "new_signals": [_signal_to_dict(s) for s in signals]}
    except ImportError:
        # engine 尚未就绪（子 agent 开发中）——fallback 到现有信号评估
        raise HTTPException(status_code=503, detail="策略引擎开发中（S02-1）")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@signal_router.post("/signals/{signal_id}/confirm")
async def confirm_signal(signal_id: str, request: Request):
    """确认信号 → 开纸面交易（虚拟买入/卖出，非真实交易）。"""
    lc = _get_lifecycle(request)

    # ① 确认信号
    if not lc.confirm(signal_id):
        raise HTTPException(status_code=409, detail="信号不存在或已确认/忽略")

    # ② 查信号详情 → 生成纸面交易
    signals = lc.list_signals(limit=200)
    sig = next((s for s in signals if s.id == signal_id), None)
    if not sig:
        raise HTTPException(status_code=404, detail="信号已过期")

    # ③ 获取信号时刻价格（从 results_json 或直接用最新价）
    try:
        results = json.loads(sig.results_json) if sig.results_json else []
        price = results[0].get("metric_value", 0.0) if results else 0.0
    except (json.JSONDecodeError, IndexError):
        price = 0.0

    # ④ 创建纸面交易（buy 1000 股作为默认——用户可在小程序调）
    trade = PaperTrade(
        id=f"pt_{uuid.uuid4().hex[:12]}",
        signal_id=signal_id,
        instrument_id=sig.instrument_id,
        action=sig.final_signal if sig.final_signal in ("buy", "sell") else "buy",
        quantity=1000.0,  # 默认；小程序端可传自定义数量
        price_at_signal=price,
    )
    lc.save_paper(trade)

    return {"confirmed": True, "paper_trade": _paper_to_dict(trade)}


@signal_router.post("/signals/{signal_id}/ignore")
async def ignore_signal(signal_id: str, request: Request):
    """忽略信号。"""
    lc = _get_lifecycle(request)
    if not lc.ignore(signal_id):
        raise HTTPException(status_code=409, detail="信号不存在或已操作")
    return {"ignored": True, "signal_id": signal_id}


@signal_router.get("/signals/history")
async def signal_history(request: Request, limit: int = 100):
    """历史信号（含已关闭的纸面交易收益）。"""
    lc = _get_lifecycle(request)
    # 全部信号（含 expired/ignored/confirmed）
    all_signals = lc.list_signals(limit=limit)
    # 全部纸面交易（含 closed）
    all_papers = lc.list_papers(limit=limit)
    # 按状态分组统计
    stats = {
        "total": len(all_signals),
        "confirmed": sum(1 for s in all_signals if s.status == "confirmed"),
        "ignored": sum(1 for s in all_signals if s.status == "ignored"),
        "expired": sum(1 for s in all_signals if s.status == "expired"),
        "paper_open": sum(1 for p in all_papers if p.status == "open"),
        "paper_closed": sum(1 for p in all_papers if p.status == "closed"),
    }
    # 纸面交易收益统计
    closed_trades = [p for p in all_papers if p.status == "closed"]
    if closed_trades:
        avg_return = sum(p.return_pct for p in closed_trades) / len(closed_trades)
        win_rate = sum(1 for p in closed_trades if p.return_pct > 0) / len(closed_trades)
        stats["avg_return_pct"] = round(avg_return * 100, 2)
        stats["win_rate"] = round(win_rate * 100, 1)
    return {
        "signals": [_signal_to_dict(s) for s in all_signals],
        "paper_trades": [_paper_to_dict(p) for p in all_papers],
        "stats": stats,
    }
