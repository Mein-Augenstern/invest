"""小程序/微服务 API（/api/invest/*）。

设计约束（docs/tech/backend/api-contract.md）：
- 路由前缀对齐 star 网关规范 /api/<域>/**，网关 invest-route 转发到本服务；
- 只做 JSON，视图数据来自 reporting/领域层，本文件不碰 pandas；
- 鉴权模型（S11 升级）：TokenAuthMiddleware 统一执行（star JWT），并把会员身份
  写入 request.state.member_id；用户数据（trades/diary/instruments/signals/reports）
  全部 member 维度隔离——跨会员读写由 store 层 WHERE member_id 拒绝；
  admin 端点经 require_admin 守卫（INVEST_ADMIN_MEMBER_IDS）；
- 概览按品类分组返回，动词口径跟随品类（申购/赎回 vs 买入/卖出）。
"""
from __future__ import annotations

import re
import sys

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from ..config import TYPE_LABELS
from ..reporting import action_label, build_entry_state, build_portfolio_view
from .deps import audit, get_conf, get_data_dir, get_member_id, get_store, get_trades, require_admin

router = APIRouter(prefix="/api/invest")

#: S09-AC4 自动补拉的进程级限频状态（30 分钟内最多一次；{"last_at": monotonic 秒}）
_AUTO_PULL_STATE = {"last_at": 0.0}


def _any_series_stale(conf, store) -> bool:
    """任一标的序列超过 STALE_THRESHOLD(6h) 未刷新 → 数据过期（S05 同口径）。"""
    from ..config import series_kind
    from ..data.resilient_provider import is_stale

    return any(
        ins.code
        and (u := store.series_updated_at(ins.code, series_kind(ins.type)))
        and is_stale(u)
        for ins in conf.instruments
    )


def _maybe_autopull_on_stale(conf, store, request) -> bool:
    """S09-AC4：数据过期时后台自动补拉（fire-and-forget，不阻塞本次响应）。

    门控：部署形态（INVEST_DB_URL=mysql://）默认开，本地默认关（避免本机意外
    打 akshare），可用 INVEST_AUTOPULL_ON_STALE=1/0 显式覆盖；同进程 30 分钟内
    最多触发一次；已有任务在跑时 start_pull 自然拒绝。
    """
    import os
    import time

    default = "1" if os.environ.get("INVEST_DB_URL", "").startswith("mysql://") else "0"
    if os.environ.get("INVEST_AUTOPULL_ON_STALE", default) != "1":
        return False
    # 限频用 wall clock：monotonic 起点不定，fresh 进程 last_at=0.0 会被
    # 误判限频 30 分钟——2026-11-07 CI Linux runner 实证，mac 长跑进程掩盖
    if time.time() - _AUTO_PULL_STATE["last_at"] < 1800:
        return False
    if not _any_series_stale(conf, store):
        return False
    from . import pulljob

    ok, _ = pulljob.start_pull(request.app.state.data_dir, request.app.state.config_path)
    if ok:
        _AUTO_PULL_STATE["last_at"] = time.time()
    return ok


def _r2(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def _holding_to_dict(row) -> dict:
    return {
        "id": row.instrument_id,
        "name": row.name,
        "account": row.account_name,
        "type": row.type,
        "type_label": row.type_label,
        "state": row.state,
        "quantity": round(row.quantity, 4),
        "price": row.price,
        "price_date": row.price_date,
        "avg_cost": row.avg_cost,
        "market_value": _r2(row.market_value),
        "unrealized": _r2(row.unrealized),
        "unrealized_pct": (
            round(row.unrealized / (row.market_value - row.unrealized), 4)
            if row.unrealized is not None and row.market_value and row.market_value != row.unrealized
            else None
        ),
        "realized_pnl": _r2(row.realized_pnl),
        "cash_dividend": _r2(row.cash_dividend),
        "xirr": round(row.xirr, 4) if row.xirr is not None else None,
        "xirr_error": row.xirr_error,
    }


@router.get("/ping")
def mp_ping() -> dict:
    return {"ok": True, "service": "invest-mp"}


def _maybe_autopull_on_stale(conf, store, request) -> bool:
    """S09-AC4：数据过期时后台自动补拉（fire-and-forget，不阻塞本次响应）。

    门控：部署形态（INVEST_DB_URL=mysql://）默认开，本地默认关（避免本机意外
    打 akshare），可用 INVEST_AUTOPULL_ON_STALE=1/0 显式覆盖；同进程 30 分钟内
    最多触发一次；已有任务在跑时 start_pull 自然拒绝。
    """
    import os
    import time

    default = "1" if os.environ.get("INVEST_DB_URL", "").startswith("mysql://") else "0"
    if os.environ.get("INVEST_AUTOPULL_ON_STALE", default) != "1":
        return False
    # 限频用 wall clock：monotonic 起点不定，fresh 进程 last_at=0.0 会被
    # 误判限频 30 分钟——2026-11-07 CI Linux runner 实证，mac 长跑进程掩盖
    if time.time() - _AUTO_PULL_STATE["last_at"] < 1800:
        return False
    if not _any_series_stale(conf, store):
        return False
    from . import pulljob

    ok, _ = pulljob.start_pull(request.app.state.data_dir, request.app.state.config_path)
    if ok:
        _AUTO_PULL_STATE["last_at"] = time.time()
    return ok


@router.get("/overview")
def overview(request: Request, conf=Depends(get_conf), store=Depends(get_store),
             trades=Depends(get_trades), member_id=Depends(get_member_id)) -> dict:
    """总览：组合汇总 + 按品类分组持仓 + 基准估值 + 近期信号（会员隔离）。"""
    view = build_portfolio_view(conf, store, trades)
    # S09-AC4：数据过期时后台自动补拉（不阻塞渲染；门控/限频见函数 docstring）
    _maybe_autopull_on_stale(conf, store, request)
    name_of = {i.id: i.name for i in conf.instruments}

    groups: dict[str, dict] = {}
    for row in view.rows:
        g = groups.setdefault(row.type, {"type": row.type, "label": row.type_label or row.type, "positions": []})
        g["positions"].append(_holding_to_dict(row))
    for g in groups.values():
        values = [p["market_value"] for p in g["positions"] if p["market_value"] is not None]
        g["market_value"] = _r2(sum(values)) if values else None
    # 展示顺序：理财/固收 → 债券 → 基金 → 股票（风险从低到高）
    order = ["wealth", "bond", "open_end_fund", "etf", "stock"]

    def _sig(s: tuple) -> dict:
        return {
            "id": s[0], "date": s[1], "instrument": name_of.get(s[2], s[2]),
            "rule": s[3], "metric": s[4], "value": s[5], "action": s[6], "status": s[7],
        }

    signals = [_sig(s) for s in store.recent_signals(member_id, limit=5, status="建议")] or [
        _sig(s) for s in store.recent_signals(member_id, limit=3)
    ]
    # 养老金缴存进度（P12）：与 build_entry_state 同口径（contribute 动作、自然年）
    year = view.date[:4]
    pension_progress = None
    for ins in conf.instruments:
        if ins.account != "pension":
            continue
        contributed = sum(
            t.quantity * t.price
            for t in trades
            if t.instrument_id == ins.id and t.action == "contribute" and t.date.startswith(year)
        )
        pension_progress = {
            "instrument_id": ins.id,
            "name": ins.name,
            "year": year,
            "contributed": round(contributed, 2),
            "cap": conf.strategy.pension_annual_cap,
        }
        break  # 养老金账户当前只管理一只基金
    return {
        "date": view.date,
        "config_source": view.config_source,
        "is_example": view.is_example_config,
        "data_stale": _any_series_stale(conf, store),  # S09-AC4：前端"数据延迟"角标
        "totals": {
            "market_value": _r2(view.total_market_value),
            "unrealized": _r2(view.total_unrealized),
            "xirr": round(view.total_xirr, 4) if view.total_xirr is not None else None,
        },
        "pension_progress": pension_progress,
        "groups": sorted(groups.values(), key=lambda g: order.index(g["type"]) if g["type"] in order else 99),
        "benchmarks": [
            {
                "name": b.name, "code": b.code, "close": b.close, "pe_ttm": b.pe_ttm,
                "pct_5y": b.pct_5y, "pct_all": b.pct_all, "dyield": b.dyield, "drawdown_5y": b.drawdown_5y,
            }
            for b in view.benchmarks
        ],
        "signals": signals,
    }


@router.get("/trades")
def trades_list(
    instrument_id: str = "",
    limit: int = 100,
    conf=Depends(get_conf),
    store=Depends(get_store),
    member_id=Depends(get_member_id),
) -> dict:
    """流水列表（新→旧，会员隔离）+ 录入表单所需的标的元数据。含行 id（新删除口径）。"""
    rows_raw = store.list_trades(member_id, instrument_id or None)
    state = build_entry_state(conf, store, _trades_of(store, member_id))
    rows = [
        {
            "id": r["id"], "date": r["date"], "instrument_id": r["instrument_id"],
            "action": r["action"], "quantity": r["quantity"], "price": r["price"],
            "fee": r["fee"] or 0, "note": r["note"] or "",
        }
        for r in reversed(rows_raw)
    ]
    itype_of = {i.id: i.type for i in conf.instruments}
    for r in rows:
        r["action_label"] = action_label(r["action"], itype_of.get(r["instrument_id"], ""))
    return {
        "trades": rows[: max(1, min(limit, 500))],
        "instruments": [
            {k: i[k] for k in ("id", "name", "type", "price", "price_label")}
            for i in state["instruments"]
        ],
        "actions": ["buy", "sell", "dividend_cash", "dividend_reinvest", "adjust", "contribute"],
    }


def _trades_of(store, member_id: int) -> list:
    """会员流水的 Trade 对象形态（供 build_entry_state 等引擎函数）。"""
    from ..ledger.trades import Trade

    return [
        Trade(date=r["date"], instrument_id=r["instrument_id"], action=r["action"],
              quantity=float(r["quantity"]), price=float(r["price"]),
              fee=float(r.get("fee") or 0), note=r.get("note") or "")
        for r in store.list_trades(member_id)
    ]


@router.post("/trades")
def mp_add_trade(
    request: Request,
    payload: dict = Body(...),
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
    member_id=Depends(get_member_id),
) -> dict:
    """记一笔（会员隔离）：校验沿用 CSV 时代口径，落库到 trades 表。"""
    from ..ledger.trades import validate_trade

    trade, err = validate_trade(payload, conf, trades)
    if err:
        return JSONResponse({"error": err}, status_code=422)
    store.append_trades(member_id, [trade])
    audit(request, "trade.add", f"instrument={trade.get('instrument_id', '')} action={trade.get('action', '')}")
    return {"ok": True, "trade": trade}


@router.post("/trades/delete")
def mp_delete_trade(
    request: Request,
    payload: dict = Body(...),
    store=Depends(get_store),
    member_id=Depends(get_member_id),
):
    """删除流水：优先按 id（新客户端），回退整行匹配（旧客户端，数值容差同口径）。
    越权（id 属于他人）等价于不存在 → 409。"""
    row = payload.get("row") or {}
    trade_id = payload.get("id") or row.get("id")
    ok = store.delete_trade(member_id, int(trade_id)) if trade_id else store.delete_trade_row(member_id, row)
    if not ok:
        return JSONResponse({"error": "未找到该行（列表可能已变化），请刷新"}, status_code=409)
    audit(request, "trade.delete", f"id={trade_id}" if trade_id else "by_row")
    return {"ok": True}


@router.post("/signals/evaluate")
def mp_evaluate_signals(
    request: Request,
    conf=Depends(get_conf), store=Depends(get_store), trades=Depends(get_trades),
    member_id=Depends(get_member_id),
) -> dict:
    """S4 信号立即评估（手机端入口；拉数完成后亦自动触发）——会员维度留痕。"""
    from ..reporting import evaluate_and_store_signals

    new_ids = evaluate_and_store_signals(conf, store, trades, member_id=member_id)
    return {"ok": True, "new": new_ids}


@router.get("/signals")
def signals_list(conf=Depends(get_conf), store=Depends(get_store), member_id=Depends(get_member_id)) -> dict:
    name_of = {i.id: i.name for i in conf.instruments}
    return {
        "signals": [
            {
                "id": s[0], "date": s[1], "instrument": name_of.get(s[2], s[2]),
                "rule": s[3], "metric": s[4], "value": s[5], "action": s[6], "status": s[7],
            }
            for s in store.recent_signals(member_id, limit=30)
        ]
    }


@router.post("/backtest")
def mp_backtest(
    payload: dict = Body(default={}),
    conf=Depends(get_conf),
    store=Depends(get_store),
    data_dir=Depends(get_data_dir),
):
    """策略回测（L3）：复用 Web 端 run_all_backtests，返回六策略指标+曲线（降采样）。"""
    from datetime import datetime
    from pathlib import Path as _Path

    from ..backtest import run_all_backtests
    from ..reporting import _to_ms

    out = run_all_backtests(
        conf, store,
        start=str(payload.get("start", "2013-06-03")),
        monthly=float(payload.get("monthly", 1000)),
        drag=float(payload.get("drag", 0) or 0),
    )
    if out.get("missing"):
        return JSONResponse({"error": out["missing"]}, status_code=422)

    results = []
    for r in out["results"]:
        eq = r.equity.copy()
        eq["ratio"] = (eq["value"] / eq["invested"]).where(eq["invested"] > 0)
        eq = eq.dropna(subset=["ratio"])
        step = max(1, len(eq) // 200)  # 移动端曲线更粗粒度
        eq = eq.iloc[::step].copy()
        results.append(
            {
                "code": getattr(r, "code", ""),
                "name": r.name,
                "params": r.params,
                "metrics": r.metrics,
                "curve": [[_to_ms(d), round(v, 3)] for d, v in zip(eq["date"], eq["ratio"])],
            }
        )
    # 归档 Markdown（与 Web 端一致留痕）
    from ..backtest import render_backtest_markdown

    md = render_backtest_markdown(out["results"], out["cfg"], out["span"])
    reports = _Path(data_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"backtest-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(md, encoding="utf-8")
    return {"ok": True, "span": out["span"], "results": results}


@router.get("/daily-pnl")
def daily_pnl(
    month: str,
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
) -> dict:
    """单月逐日收益（R4 收益日历）。month=YYYY-MM。"""
    from ..reporting_summary import build_daily_pnl

    if not (len(month) == 7 and month[4] == "-" and month[:4].isdigit() and month[5:].isdigit()):
        return JSONResponse({"error": "month 应为 YYYY-MM"}, status_code=422)
    return build_daily_pnl(conf, store, trades, month)


@router.get("/asset-curve")
def asset_curve(
    days: int = 365,
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
) -> dict:
    """组合总资产历史曲线（R3）：逐日市值（与月度统计同源口径），降采样输出。"""
    from datetime import datetime, timedelta

    from ..reporting import _to_ms
    from ..reporting_summary import build_daily_mv_series

    mv = build_daily_mv_series(conf, store, trades)
    if not mv:
        return {"curve": [], "start": "", "end": ""}
    cutoff = (datetime.now() - timedelta(days=max(30, min(days, 3650)))).strftime("%Y-%m-%d")
    pts = [(d, v) for d, v in sorted(mv.items()) if d >= cutoff]
    step = max(1, len(pts) // 200)
    pts = pts[::step]
    if pts and pts[-1] != sorted(mv.items())[-1]:
        pts.append(sorted(mv.items())[-1])
    return {
        "curve": [[_to_ms(d), round(v, 2)] for d, v in pts],
        "start": pts[0][0] if pts else "",
        "end": pts[-1][0] if pts else "",
    }


@router.get("/annual-report")
def annual_report(
    year: str,
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
) -> dict:
    """年度复盘（R7，年度账单式）。year=YYYY。"""
    from ..reporting_summary import build_annual_report

    if not (len(year) == 4 and year.isdigit()):
        return JSONResponse({"error": "year 应为 YYYY"}, status_code=422)
    return build_annual_report(conf, store, trades, year)


@router.get("/diary")
def diary_list(store=Depends(get_store), member_id=Depends(get_member_id), date: str = "") -> dict:
    """投资日记列表（R5，会员隔离）；带 date 参数时返回单条（编辑回填）。"""
    if date:
        row = store.get_diary(date, member_id)
        return {"diary": {"date": row[0], "content": row[1], "mood": row[2]} if row else None}
    rows = store.list_diary(member_id)
    return {"entries": [{"date": r[0], "content": r[1], "mood": r[2]} for r in rows]}


class _UploadError(Exception):
    """上传图片校验失败（message 即返回给端的 error 文案）。"""


async def _read_upload_image(request: Request) -> bytes:
    """读取并校验上传图片（png/jpg ≤5MB），返回字节内容；失败抛 _UploadError。

    图片只在调用方写入系统临时目录即用即删，不落数据目录。"""
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" not in content_type:
        raise _UploadError("请用 multipart/form-data 上传图片字段 file")
    form = await request.form()
    up = form.get("file")
    if up is None or not hasattr(up, "read"):
        raise _UploadError("缺少图片字段 file")
    data = await up.read()
    if not data:
        raise _UploadError("空文件")
    if len(data) > 5 * 1024 * 1024:
        raise _UploadError("图片超过 5MB")
    name = str(getattr(up, "filename", "") or "").lower()
    if not name.endswith((".png", ".jpg", ".jpeg")):
        raise _UploadError("仅支持 png/jpg")
    return data


def _ocr_upload(data: bytes, suffix: str) -> str:
    """字节落临时文件跑本地 Vision OCR，用完即删；失败抛 _UploadError。"""
    import os
    import tempfile
    from pathlib import Path

    from ..ocr import ocr_image

    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    try:
        tmp.write_bytes(data)
        return ocr_image(tmp)
    except Exception:  # noqa: BLE001 - Vision 崩溃细节不外泄
        raise _UploadError(f"OCR 失败: {sys.exc_info()[0].__name__}") from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@router.post("/ocr")
async def mp_ocr(
    request: Request,
    conf=Depends(get_conf),
    store=Depends(get_store),
    member_id=Depends(get_member_id),
):
    """图片识别录入（S1）：上传截图 → 本地 Vision OCR → GLM 结构化流水草稿。

    图片只在系统临时目录即用即删；无 GLM Key 时返回 OCR 原文（预览页手动整理）。
    """
    from ..ocr import parse_trades_by_llm

    try:
        data = await _read_upload_image(request)
        text = _ocr_upload(data, ".png")
    except _UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=422)

    state = build_entry_state(conf, store, _trades_of(store, member_id))
    instruments = [{"id": i["id"], "name": i["name"], "type": i["type"]} for i in state["instruments"]]
    trades = parse_trades_by_llm(text, instruments)
    return {"text": text, "trades": trades, "ai_parsed": trades is not None}


@router.post("/instruments/parse-image")
async def instrument_parse_image(
    request: Request,
    conf=Depends(get_conf),
    store=Depends(get_store),
):
    """标的识别录入（S2）：标的详情页截图 → Vision OCR → GLM 结构化新标的草稿。

    返回 instrument 与 POST /instruments 载荷字段对齐（type 非法/id 撞车时清空交用户补），
    无 GLM Key 时 ai_parsed=false 只回 OCR 原文（用户对照手动填表）。
    existing_ids 取会员视角（S11：id 唯一性按会员校验）。
    """
    from ..ocr import parse_instrument_by_llm

    try:
        data = await _read_upload_image(request)
        text = _ocr_upload(data, ".png")
    except _UploadError as e:
        return JSONResponse({"error": str(e)}, status_code=422)

    existing_ids = [i.id for i in conf.instruments]
    draft = parse_instrument_by_llm(text, existing_ids)
    return {"text": text, "instrument": draft, "ai_parsed": draft is not None}


@router.get("/instruments")
def instruments_list(store=Depends(get_store), conf=Depends(get_conf), member_id=Depends(get_member_id)) -> dict:
    """标的管理列表（S2，会员隔离）：yaml 种子（共享只读）+ 本会员 db 标的，
    带持仓数量（删除保护用，按本会员流水计）。"""
    positions: dict[str, float] = {}
    for t in _trades_of(store, member_id):
        if t.instrument_id not in positions:
            positions[t.instrument_id] = 0.0
        positions[t.instrument_id] += t.quantity if t.action in ("buy", "dividend_reinvest", "adjust") else -t.quantity
    own_ids = {r[0] for r in store.list_instruments(member_id)}
    return {
        "instruments": [
            {
                "id": i.id, "name": i.name, "type": i.type, "code": i.code,
                "benchmark_index": i.benchmark_index, "account": i.account,
                "held_qty": round(positions.get(i.id, 0.0), 2),
                "from_db": i.id in own_ids,
            }
            for i in conf.instruments
        ]
    }


@router.post("/instruments")
def instruments_save(request: Request, payload: dict = Body(...), store=Depends(get_store),
                     member_id=Depends(get_member_id)) -> dict:
    """新增/编辑标的（S2，落本会员 instruments 行；type/account 枚举校验）。"""
    from ..config import INSTRUMENT_TYPES

    ins_id = str(payload.get("id", "")).strip()
    itype = str(payload.get("type", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not ins_id or not re.match(r"^[a-z0-9_]{2,32}$", ins_id):
        return JSONResponse({"error": "id 需为 2-32 位小写字母/数字/下划线"}, status_code=422)
    if itype not in INSTRUMENT_TYPES:
        return JSONResponse({"error": f"type 非法（合法值: {sorted(INSTRUMENT_TYPES)}）"}, status_code=422)
    if not name:
        return JSONResponse({"error": "名称不能为空"}, status_code=422)
    code = str(payload.get("code", "")).strip()
    if code and itype == "bond" and not code.startswith(("sh", "sz")):
        return JSONResponse({"error": "债券代码需带市场前缀（如 sh019547）"}, status_code=422)
    store.upsert_instrument({
        "id": ins_id, "type": itype, "name": name, "code": code,
        "benchmark_index": str(payload.get("benchmark_index", "")).strip(),
        "benchmark_tr_code": str(payload.get("benchmark_tr_code", "")).strip(),
        "account": str(payload.get("account", "")).strip(),
    }, member_id)
    audit(request, "instrument.save", f"id={ins_id}")
    return {"ok": True, "id": ins_id}


@router.post("/instruments/delete")
def instruments_delete(request: Request, payload: dict = Body(...), store=Depends(get_store),
                       member_id=Depends(get_member_id)) -> dict:
    ins_id = str(payload.get("id", ""))
    held = sum(
        t.quantity if t.action in ("buy", "dividend_reinvest", "adjust") else -t.quantity
        for t in _trades_of(store, member_id) if t.instrument_id == ins_id
    )
    if abs(held) > 1e-6:
        return JSONResponse({"error": "该标的有持仓流水，不能删除（可清仓后删）"}, status_code=409)
    if not store.delete_instrument(ins_id, member_id):
        return JSONResponse({"error": "仅本会员新增的标的可删（yaml 种子请编辑本机配置）"}, status_code=404)
    audit(request, "instrument.delete", f"id={ins_id}")
    return {"ok": True}


@router.get("/settings/glm-key")
def glm_key_status(data_dir=Depends(get_data_dir)) -> dict:
    """GLM Key 持久化（S2）：本机 gitignore 文件（路径规则见 deps.glm_key_file）；只回是否已配不回值。"""
    from .deps import glm_key_file

    f = glm_key_file(data_dir)
    return {"configured": f.exists() and bool(f.read_text(encoding="utf-8").strip())}


@router.post("/settings/glm-key")
def glm_key_save(payload: dict = Body(...), data_dir=Depends(get_data_dir)) -> dict:
    import os

    from .deps import glm_key_file

    key = str(payload.get("key", "")).strip()
    f = glm_key_file(data_dir)
    if key:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"INVEST_GLM_API_KEY={key}\n", encoding="utf-8")
        os.environ["INVEST_GLM_API_KEY"] = key  # 免重启即时生效
    else:
        f.unlink(missing_ok=True)
        os.environ.pop("INVEST_GLM_API_KEY", None)
    return {"ok": True, "configured": bool(key)}


@router.post("/diary")
def diary_save(request: Request, payload: dict = Body(...), store=Depends(get_store),
               member_id=Depends(get_member_id)) -> dict:
    """写/改日记（按会员按日 upsert）。{date, content, mood?}"""
    from datetime import datetime

    date = str(payload.get("date", ""))
    content = str(payload.get("content", "")).strip()
    mood = str(payload.get("mood", "")).strip()
    if mood and mood not in ("平静", "贪婪", "恐惧", "犹豫", "坚定"):
        return JSONResponse({"error": "心情取值：平静/贪婪/恐惧/犹豫/坚定"}, status_code=422)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "日期格式应为 YYYY-MM-DD"}, status_code=422)
    if not content:
        return JSONResponse({"error": "内容不能为空"}, status_code=422)
    store.upsert_diary(date, content, mood, member_id)
    audit(request, "diary.save", f"date={date}")
    return {"ok": True}


@router.post("/diary/delete")
def diary_delete(request: Request, payload: dict = Body(...), store=Depends(get_store),
                 member_id=Depends(get_member_id)) -> dict:
    if not store.delete_diary(str(payload.get("date", "")), member_id):
        return JSONResponse({"error": "未找到该日日记"}, status_code=404)
    audit(request, "diary.delete", f"date={payload.get('date', '')}")
    return {"ok": True}


@router.get("/valuation")
def valuation_table(store=Depends(get_store)) -> dict:
    """指数估值表 + 市场温度（R1/R2，蛋卷式看板：主流中证指数 PE 分位）。"""
    from ..valuation import build_valuation_table, market_temperature

    return {"indexes": build_valuation_table(store), "temperature": market_temperature(store)}


@router.get("/summary")
def monthly_summary(
    months: int = 12,
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
) -> dict:
    """月度/年度收益统计（L2）：净投入精确来自流水，浮盈变化=Δ市值−净投入。"""
    from ..reporting_summary import build_monthly_summary

    return build_monthly_summary(conf, store, trades, months=max(1, min(months, 60)))


@router.get("/instrument/{instrument_id}")
def instrument_detail(
    instrument_id: str,
    conf=Depends(get_conf),
    store=Depends(get_store),
    trades=Depends(get_trades),
):
    """单标的详情：指标行 + 净值序列(降采样) + 交易事件 + 信号 + 基金透视。

    S05 韧性：序列缓存超过 STALE_THRESHOLD(6h) 未刷新视为降级数据（拉数失败
    只能吃旧缓存），返回 stale=True 供前端明示"非最新"；无序列数据不算 stale（走空态）。
    """
    from ..config import series_kind
    from ..data.resilient_provider import is_stale
    from ..reporting import build_instrument_view

    data = build_instrument_view(conf, store, trades, instrument_id)
    if data is None:
        return JSONResponse({"error": "未找到该标的"}, status_code=404)
    row = data.pop("row")
    data["row"] = _holding_to_dict(row)
    account = data.pop("account")
    data["account_name"] = account.name if account else ""
    b = data.get("benchmark")
    if b is not None:
        data["benchmark"] = {
            "name": b.name, "code": b.code, "close": b.close, "pe_ttm": b.pe_ttm,
            "pct_5y": b.pct_5y, "pct_all": b.pct_all, "dyield": b.dyield, "drawdown_5y": b.drawdown_5y,
        }
    # S05: 本地缓存超过阈值未刷新 → 数据来自降级路径，打 stale 标记
    ins = next((i for i in conf.instruments if i.id == instrument_id), None)
    data["stale"] = False
    if ins is not None:
        updated_at = store.series_updated_at(ins.code or ins.id, series_kind(ins.type))
        data["stale"] = bool(updated_at) and is_stale(updated_at)
    return data


@router.post("/nav")
def mp_add_nav(
    request: Request,
    payload: dict = Body(...),
    conf=Depends(get_conf),
    store=Depends(get_store),
) -> dict:
    """手工净值录入（理财/固收等无公开行情品种；与 CLI `invest nav` 同一落点，幂等）。"""
    from datetime import datetime

    import pandas as pd

    instrument_id = str(payload.get("instrument_id", ""))
    ins = next((i for i in conf.instruments if i.id == instrument_id), None)
    if not ins:
        return JSONResponse({"error": "未找到该标的"}, status_code=404)
    date = str(payload.get("date") or datetime.now().strftime("%Y-%m-%d"))
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "日期格式应为 YYYY-MM-DD"}, status_code=422)
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "净值需为数字"}, status_code=422)
    if value <= 0:
        return JSONResponse({"error": "净值需为正数"}, status_code=422)
    df = pd.DataFrame({"date": [date], "close": [value]})
    store.upsert_series(ins.code or ins.id, "manual_nav", df, source="manual")
    audit(request, "nav.add", f"instrument={instrument_id} date={date}")
    return {"ok": True, "instrument": ins.name, "date": date, "value": value}


@router.get("/report/latest")
def report_latest(data_dir=Depends(get_data_dir), member_id=Depends(get_member_id)) -> dict:
    """最新周报（Markdown 原文，小程序端轻量渲染；S11 会员目录）。无周报时返回 null 前端引导生成。

    按 mtime 取最新而非文件名字典序：CLI 版命名 weekly-YYYYMMDD.md 与任务版
    weekly-YYYYMMDD-HHMMSS.md 混排时字典序会选错（'-' < '.'）。
    """
    from pathlib import Path

    reports = Path(data_dir) / "reports" / str(member_id)
    weeklies = sorted(reports.glob("weekly-*.md"), key=lambda p: p.stat().st_mtime) if reports.exists() else []
    if not weeklies:
        return {"report": None}
    f = weeklies[-1]
    return {"file": f.name, "markdown": f.read_text(encoding="utf-8")}


@router.post("/reports/generate")
def mp_generate_report(
    request: Request,
    payload: dict = Body(default={}),
    data_dir=Depends(get_data_dir),
    member_id=Depends(get_member_id),
) -> dict:
    """触发后台周报生成（AI 解读可选、无 Key 自动降级）；前端轮询 /reports/status。"""
    from . import reportjob

    ok, err = reportjob.start_report(
        data_dir, request.app.state.config_path, with_ai=bool(payload.get("ai")), member_id=member_id
    )
    if not ok:
        return JSONResponse({"error": err}, status_code=409)
    audit(request, "report.generate", f"ai={bool(payload.get('ai'))}")
    return {"ok": True}


@router.get("/reports/status")
def mp_report_status() -> dict:
    from . import reportjob

    return reportjob.status()


@router.post("/signals/{sid}/status")
def mp_signal_status(request: Request, sid: int, payload: dict = Body(...), store=Depends(get_store),
                     member_id=Depends(get_member_id)):
    status = str(payload.get("status", ""))
    if status not in ("已确认", "已忽略", "建议"):
        return JSONResponse({"error": "非法状态"}, status_code=422)
    if not store.update_signal_status(sid, status, member_id):
        return JSONResponse({"error": "信号不存在"}, status_code=404)
    audit(request, "signal.status", f"id={sid} status={status}")
    return {"ok": True, "id": sid, "status": status}


# ---- 运营端点（S11 AC-5：admin 守卫） ----


@router.get("/admin/members")
def admin_members(store=Depends(get_store), admin=Depends(require_admin)) -> dict:
    """会员概览：流水/日记计数（不含账本明细——读明细另行审计）。"""
    members: dict[int, dict] = {}
    for mid in store.member_ids_with_trades():
        members[mid] = {"member_id": mid, "trade_count": store.trade_count(mid)}
    from ..data.local import LocalStore  # noqa: F401（类型提示用）

    for r in store.list_audit(limit=500):
        m = members.setdefault(r[1], {"member_id": r[1], "trade_count": 0})
        m["last_action"] = r[2]
        m["last_action_at"] = r[5]
    return {"members": sorted(members.values(), key=lambda m: -m["member_id"])}


@router.get("/admin/audit")
def admin_audit(limit: int = 100, store=Depends(get_store), admin=Depends(require_admin)) -> dict:
    """审计日志（S11 AC-6）：who/what/when/traceId。"""
    rows = store.list_audit(limit=max(1, min(limit, 500)))
    return {"audit": [
        {"id": r[0], "member_id": r[1], "action": r[2], "detail": r[3], "trace_id": r[4], "created_at": r[5]}
        for r in rows
    ]}


@router.post("/pull")
def mp_start_pull(request: Request, data_dir=Depends(get_data_dir)) -> dict:
    """触发后台拉数（分钟级网络任务，小程序轮询 /api/invest/pull/status）。"""
    from . import pulljob

    ok, err = pulljob.start_pull(data_dir, request.app.state.config_path)
    if not ok:
        return JSONResponse({"error": err}, status_code=409)
    return {"ok": True}


@router.get("/pull/status")
def mp_pull_status() -> dict:
    from . import pulljob

    return pulljob.status()
