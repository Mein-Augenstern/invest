"""invest CLI：python -m invest <selfcheck|pull-data|snapshot>"""
from __future__ import annotations

import argparse
from datetime import datetime

from . import config as cfg
from .portfolio import load_portfolio


def _tail(df) -> str:
    if df is None or getattr(df, "empty", True):
        return "EMPTY"
    last = df.iloc[-1]
    return f"rows={len(df)}, last={last['date']} close={last['close']}"


# ---------- selfcheck：数据源连通性 ----------

def cmd_selfcheck(args: argparse.Namespace) -> int:
    from .data.akshare_provider import AkshareProvider

    p = AkshareProvider()
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            results.append((name, True, fn()))
        except Exception as e:  # noqa: BLE001 - 自检就是要吞掉异常报告状态
            results.append((name, False, f"{type(e).__name__}: {e}"))

    check(
        "ETF日行情（东财→新浪兜底）",
        lambda: _tail(p.etf_daily(args.smoke_etf, start="2026-07-01")),
    )
    check(
        "场外基金净值 fund_open_fund_info_em",
        lambda: _tail(p.fund_nav(args.smoke_fund)),
    )
    check(
        "A股个股行情（东财→新浪兜底）",
        lambda: _tail(p.stock_daily(args.smoke_stock, start="2026-07-01")),
    )
    check(
        "场内债券行情（东财/新浪可转债/新浪交易所债 三源兜底）",
        lambda: _tail(p.bond_daily(args.smoke_bond, start="2026-07-01")),
    )
    check(
        "中证指数目录 index_csindex_all",
        lambda: f"rows={len(p.refresh_catalog())}",
    )
    check(
        "中证官网指数估值 931139(消费50)",
        lambda: "; ".join(f"{k}:{_tail(v)}" for k, v in p.index_valuation("931139").items()),
    )

    ok = True
    for name, passed, msg in results:
        ok &= passed
        print(f"[{'OK  ' if passed else 'FAIL'}] {name}: {msg}")
    return 0 if ok else 1


# ---------- pull-data：拉数入SQLite（管线在 pipeline.run_pull，与Web设置页共用） ----------

def cmd_pull_data(args: argparse.Namespace) -> int:
    from .data.akshare_provider import AkshareProvider
    from .data.mysql_store import default_store
    from .pipeline import run_pull

    run_pull(cfg.load_config(), default_store(cfg.DATA_DIR), AkshareProvider(), log=print, start=args.start)
    return 0


# ---------- snapshot / report：报告构建 ----------

def cmd_snapshot(args: argparse.Namespace) -> int:
    from .data.mysql_store import default_store
    from .ledger.trades import load_trades
    from .reporting import build_portfolio_view, render_snapshot_markdown

    store = default_store(cfg.DATA_DIR)
    conf = load_portfolio(store)
    report = render_snapshot_markdown(
        build_portfolio_view(conf, store, load_trades(cfg.DATA_DIR / "trades.csv"))
    )
    print(report)
    out = cfg.DATA_DIR / "reports" / f"snapshot-{datetime.now().strftime('%Y%m%d')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"(已保存 {out})")
    return 0


# ---------- report：周报（快照+信号+可选AI解读，构建在 reporting.build_weekly_report_md） ----------

def cmd_report(args: argparse.Namespace) -> int:
    from .data.mysql_store import default_store
    from .ledger.trades import load_trades
    from .reporting import build_weekly_report_md

    store = default_store(cfg.DATA_DIR)
    conf = load_portfolio(store)
    report = build_weekly_report_md(conf, store, load_trades(cfg.DATA_DIR / "trades.csv"), with_ai=args.ai)

    print(report)
    out = cfg.DATA_DIR / "reports" / f"weekly-{datetime.now().strftime('%Y%m%d')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"(已保存 {out})")
    return 0


# ---------- signals：策略信号评估与留痕 ----------

def cmd_signals(args: argparse.Namespace) -> int:
    from .data.mysql_store import default_store
    from .ledger.trades import load_trades
    from .strategy import evaluate_all

    store = default_store(cfg.DATA_DIR)

    if args.confirm or args.ignore:
        sid, status = (args.confirm, "已确认") if args.confirm else (args.ignore, "已忽略")
        ok = store.update_signal_status(int(sid), status)
        print(f"信号 #{sid} → {status}" if ok else f"未找到信号 #{sid}")
        return 0 if ok else 1

    conf = load_portfolio(store)
    trades = load_trades(cfg.DATA_DIR / "trades.csv")
    signals = evaluate_all(conf, store, trades)
    new_ids = store.add_signals(signals)

    print(f"# 策略信号 {datetime.now().strftime('%Y-%m-%d')}（新增 {len(new_ids)} 条）\n")
    print("| # | 标的 | 规则 | 依据 | 取值 | 建议动作 | 状态 |")
    print("|---|---|---|---|---|---|---|")
    name_of = {i.id: i.name for i in conf.instruments}
    for s in reversed(store.recent_signals(limit=12)):
        print(f"| {s[0]} | {name_of.get(s[2], s[2])} | {s[3]} | {s[4]} | {s[5]} | {s[6]} | {s[7]} |")
    print("\n确认/忽略: uv run python -m invest signals --confirm <#> / --ignore <#>")
    return 0


# ---------- entry：本机网页录入流水 ----------

def cmd_entry(args: argparse.Namespace) -> int:
    from .entry_server import run_server

    run_server(port=args.port, open_browser=not args.no_browser)
    return 0


# ---------- nav：理财/固收手工净值录入（wealth 品类无公开行情） ----------

def cmd_nav(args: argparse.Namespace) -> int:
    import pandas as pd

    from .data.mysql_store import default_store

    store = default_store(cfg.DATA_DIR)
    conf = load_portfolio(store)
    ins = next((i for i in conf.instruments if i.id == args.instrument_id), None)
    if not ins:
        print(f"未找到标的 {args.instrument_id}（可用: {', '.join(i.id for i in conf.instruments)}）")
        return 1
    series_key = ins.code or ins.id

    if args.list:
        df = store.read_series(series_key, "manual_nav")
        if df.empty:
            print(f"{ins.name}: 暂无净值记录")
            return 0
        print(f"{ins.name}（{series_key}）手工净值:")
        print(df.tail(args.list).to_string(index=False))
        return 0

    if args.value is None:
        print("请提供 --value <净值>（或用 --list 查看历史）")
        return 1

    date = args.date or datetime.now().strftime("%Y-%m-%d")
    df = pd.DataFrame({"date": [date], "close": [float(args.value)]})
    store.upsert_series(series_key, "manual_nav", df, source="manual")
    print(f"[OK] {ins.name} {date} 净值={args.value}（幂等，同日重录覆盖）")
    return 0


# ---------- serve：Web 管理平台 ----------

def _lan_ips() -> set[str]:
    """本机局域网 IPv4（UDP connect 套路，不实际发包）。"""
    import socket

    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return {ip for ip in ips if not ip.startswith("127.")}


def cmd_serve(args: argparse.Namespace) -> int:
    import os
    import secrets
    import threading
    import webbrowser

    import uvicorn

    if args.lan:
        ips = _lan_ips()
        if not ips:
            print("未探测到局域网 IPv4（检查 Wi-Fi/网线），--lan 需要局域网可用")
            return 1
        token = args.token or secrets.token_urlsafe(8)
        # main.py 经环境变量接收（uvicorn import-string 子进程继承环境）
        os.environ["INVEST_AUTH_MODE"] = "token"
        os.environ["INVEST_MP_TOKEN"] = token
        os.environ["INVEST_HOSTS_EXTRA"] = ",".join(ips)
        args.host = "0.0.0.0"
        args.no_browser = True
        lan_ip = sorted(ips)[0]
        print(f"LAN 模式：局域网设备经 http://{lan_ip}:{args.port} 访问")
        print(f"访问令牌：{token}（除连通性 ping 外，所有页面与接口都需要）")
        print("小程序端：设置页填入上述地址与令牌；本机浏览器仍可 http://127.0.0.1:%d 免令牌" % args.port)
    elif args.auth == "star":
        # star 微服务形态：挂在 star 网关后做纵深防御，绑本机即可（容器内由 compose 接管）
        import os

        os.environ["INVEST_AUTH_MODE"] = "star"
        if args.token:
            os.environ["INVEST_JWT_SECRET"] = args.token
        args.no_browser = True
        if not os.environ.get("INVEST_JWT_SECRET"):
            print("star 鉴权模式：未配置密钥（INVEST_JWT_SECRET 或 --token）——除 ping 外将全部 401")
        else:
            print("star 鉴权模式：校验 star 平台 JWT（密钥已注入）")
    elif args.token:
        import os

        os.environ["INVEST_AUTH_MODE"] = "token"
        os.environ["INVEST_MP_TOKEN"] = args.token

    url = f"http://{args.host}:{args.port}"
    print(f"Web 管理平台启动中: {url}（Ctrl+C 停止）")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",)).start()
    # 传 import string 而非 app 对象，--reload 才生效
    uvicorn.run("invest.webapp.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


# ---------- export-static：导出自包含静态页面（file://直开，无代理无缓存） ----------

def cmd_export_static(args: argparse.Namespace) -> int:
    from .webapp.static_export import export_static

    out_dir = cfg.DATA_DIR / "reports" / "static"
    files = export_static(out_dir)
    print(f"已导出 {len(files)} 个自包含页面（CSS/JS全内联，双击即看，不经过网络）：")
    for f in files:
        print(f"  file://{f}")
    if not args.no_browser:
        import webbrowser

        webbrowser.open(f"file://{files[0]}")
    return 0


# ---------- backtest：中证红利策略回测（跑批在 backtest.run_all_backtests，与Web共用） ----------

def cmd_backtest(args: argparse.Namespace) -> int:
    from .backtest import render_backtest_markdown, run_all_backtests
    from .data.mysql_store import default_store

    conf = cfg.load_config()
    out = run_all_backtests(conf, default_store(cfg.DATA_DIR),
                            args.start, args.monthly, args.drag)
    if out.get("missing"):
        print(out["missing"]); return 1
    results, bt_cfg, span = out["results"], out["cfg"], out["span"]
    if out["div_yield_now"] is not None:
        print(f"(推算滚动股息率最新值: {out['div_yield_now']:.2f}%——与官网口径交叉验证)")
    report = render_backtest_markdown(results, bt_cfg, span)
    print(report)
    from datetime import datetime as _dt

    outf = cfg.DATA_DIR / "reports" / f"backtest-{_dt.now().strftime('%Y%m%d-%H%M')}.md"
    outf.parent.mkdir(parents=True, exist_ok=True)
    outf.write_text(report, encoding="utf-8")
    print(f"(已保存 {outf})")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="invest", description="个人投研与决策支持平台（决策支持，非自动交易）")
    sub = parser.add_subparsers(dest="command", required=True)

    sc = sub.add_parser("selfcheck", help="数据源连通性检查")
    sc.add_argument("--smoke-etf", default="159928", help="冒烟用ETF代码")
    sc.add_argument("--smoke-fund", default="110022", help="冒烟用场外基金代码")
    sc.add_argument("--smoke-stock", default="600519", help="冒烟用A股代码")
    sc.add_argument("--smoke-bond", default="sh019547", help="冒烟用债券代码（带市场前缀）")
    sc.set_defaults(func=cmd_selfcheck)

    pl = sub.add_parser("pull-data", help="拉取行情/净值/指数估值入本地SQLite")
    pl.add_argument("--start", default="2015-01-01", help="起始日期 YYYY-MM-DD")
    pl.set_defaults(func=cmd_pull_data)

    sn = sub.add_parser("snapshot", help="输出持仓与收益快照(Markdown)")
    sn.set_defaults(func=cmd_snapshot)

    sg = sub.add_parser("signals", help="评估策略规则并输出/留痕信号")
    sg.add_argument("--confirm", metavar="ID", help="将指定信号标记为已确认")
    sg.add_argument("--ignore", metavar="ID", help="将指定信号标记为已忽略")
    sg.set_defaults(func=cmd_signals)

    rp = sub.add_parser("report", help="生成周报（快照+信号，--ai 附加GLM解读）")
    rp.add_argument("--ai", action="store_true", help="调用GLM生成AI解读（需 INVEST_GLM_API_KEY）")
    rp.set_defaults(func=cmd_report)

    en = sub.add_parser("entry", help="[deprecated] 旧录入页，请改用 invest serve")
    en.add_argument("--port", type=int, default=8765)
    en.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    en.set_defaults(func=cmd_entry)

    nv = sub.add_parser("nav", help="录入/查看手工净值（理财等无公开行情品种）")
    nv.add_argument("instrument_id", help="标的 id（portfolio.local.yaml 中配置）")
    nv.add_argument("--value", help="净值/万份收益（理财通常按1.0000起购 confirm 口径见 docs/03）")
    nv.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")
    nv.add_argument("--list", type=int, metavar="N", help="查看最近 N 条净值（默认10）")
    nv.set_defaults(func=cmd_nav)

    sv = sub.add_parser("serve", help="启动 Web 管理平台（默认仅本机；--lan 供小程序/局域网）")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8790)
    sv.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    sv.add_argument("--reload", action="store_true", help="开发模式热重载")
    sv.add_argument("--lan", action="store_true", help="局域网模式：0.0.0.0 + 令牌鉴权（小程序用）")
    sv.add_argument("--auth", choices=["star"], help="star 微服务形态：校验 star 平台 JWT")
    sv.add_argument("--token", help="token 模式令牌 / star 模式下为 JWT_SECRET")
    sv.set_defaults(func=cmd_serve)

    bt = sub.add_parser("backtest", help="中证红利策略回测（四策略对照）")
    bt.add_argument("--start", default="2013-06-03", help="回测起始日 YYYY-MM-DD")
    bt.add_argument("--monthly", type=float, default=1000.0, help="每月投入金额")
    bt.add_argument("--drag", type=float, default=0.0, help="年化跟踪损耗假设(0-0.02)")
    bt.set_defaults(func=cmd_backtest)

    ex = sub.add_parser("export-static", help="导出自包含静态页面（file://直开，无代理无缓存）")
    ex.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ex.set_defaults(func=cmd_export_static)

    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))
