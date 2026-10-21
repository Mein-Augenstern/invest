"""页面路由（同步 def——视图组装跑 pandas，交线程池执行）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from . import templates
from .deps import get_conf, get_data_dir, get_store
from .. import config as cfg

router = APIRouter()

NAV = [
    ("/", "总览", "M4 4h16v16H4z"),
    ("/positions", "持仓", "M4 19h16M7 16V9m5 7V5m5 11v-4"),
    ("/trades", "流水", "M4 7h16M4 12h10M4 17h6"),
    ("/strategy", "策略", "M12 3v18M3 8h18M3 16h18"),
    ("/signals", "信号", "M12 3v18M3 12h18"),
    ("/backtest", "回测", "M3 3v18h18M7 15l4-6 3 4 4-8"),
    ("/reports", "报告", "M7 3h7l4 4v14H7zM14 3v4h4"),
    ("/glossary", "概念", "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5z"),
    ("/settings", "设置", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.3 2.5a7 7 0 0 0-1.7 1l-2.4-1-2 3.5L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 1.7 1l.3 2.5h5l.3-2.5a7 7 0 0 0 1.7-1l2.4 1 2-3.5-2-1.5a7 7 0 0 0 .1-1z"),
]


def _ctx(request: Request, **kw):
    active = request.url.path
    return {
        "request": request,
        "nav": NAV,
        "active_path": active if any(active == p or active.startswith(p + "/") for p, _, _ in NAV) else "/",
        "app_version": request.app.state.app_version,
        **kw,
    }


@router.get("/")
def index(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store), data_dir=Depends(get_data_dir)):
    from .views import index_context

    return templates.TemplateResponse(request, "index.html", _ctx(request, **index_context(conf, store, data_dir)))


@router.get("/positions")
def positions(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store), data_dir=Depends(get_data_dir)):
    from .views import positions_context

    return templates.TemplateResponse(request, "positions.html", _ctx(request, **positions_context(conf, store, data_dir)))


@router.get("/trades")
def trades(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store), data_dir=Depends(get_data_dir)):
    from .views import trades_context

    return templates.TemplateResponse(request, "trades.html", _ctx(request, **trades_context(conf, store, data_dir)))


@router.get("/signals")
def signals(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store)):
    from .views import signals_context

    return templates.TemplateResponse(request, "signals.html", _ctx(request, **signals_context(conf, store)))


@router.get("/reports")
def reports(request: Request, data_dir=Depends(get_data_dir)):
    from .views import reports_context

    return templates.TemplateResponse(request, "reports.html", _ctx(request, **reports_context(data_dir)))


@router.get("/positions/{instrument_id}")
def position_detail(instrument_id: str, request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store), data_dir=Depends(get_data_dir)):
    from fastapi import HTTPException

    from .views import instrument_context

    ctx = instrument_context(conf, store, data_dir, instrument_id)
    if ctx is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "positions_detail.html", _ctx(request, **ctx))


@router.get("/strategy")
def strategy(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store), data_dir=Depends(get_data_dir)):
    from .views import strategy_context

    return templates.TemplateResponse(request, "strategy.html", _ctx(request, **strategy_context(conf, store, data_dir)))


@router.get("/glossary")
def glossary(request: Request, data_dir=Depends(get_data_dir)):
    from .glossary import load_glossary

    entries = load_glossary(data_dir)
    return templates.TemplateResponse(request, "glossary.html", _ctx(request, entries=entries))


@router.get("/backtest")
def backtest_page(request: Request, conf: cfg.Portfolio = Depends(get_conf), store=Depends(get_store)):
    from .views import backtest_context

    return templates.TemplateResponse(request, "backtest.html", _ctx(request, **backtest_context(conf, store)))


@router.get("/settings")
def settings(request: Request, conf: cfg.Portfolio = Depends(get_conf)):
    from .views import settings_context

    return templates.TemplateResponse(request, "settings.html", _ctx(request, **settings_context(conf)))


@router.get("/reports/view/{name}")
def report_view(name: str, request: Request, data_dir=Depends(get_data_dir)):
    import re

    from fastapi import HTTPException

    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.md", name):
        raise HTTPException(status_code=404)
    path = Path(data_dir) / "reports" / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "report_view.html", _ctx(request, name=name, content=path.read_text(encoding="utf-8"))
    )
