"""导出自包含静态页面：python -m invest export-static

动机：本机系统代理/缓存层可能喂旧静态资源；file:// 直开的单文件页面
不经过 HTTP 栈（无代理无缓存），用于"眼见为实"的布局核对与分享。

做法：TestClient 本地渲染页面 → 把 /static/* 的 <link>/<script src> 全部
内联为 <style>/<script> → 导航链接改指同级 .html 文件。
注意：静态快照仅用于查看——表单提交/信号按钮/拉数轮询等交互功能不工作。
"""
from __future__ import annotations

import re
from pathlib import Path

PAGES = [
    ("/", "index", "总览"),
    ("/positions", "positions", "持仓"),
    ("/trades", "trades", "流水"),
    ("/strategy", "strategy", "策略"),
    ("/signals", "signals", "信号"),
    ("/reports", "reports", "报告"),
    ("/settings", "settings", "设置"),
    ("/glossary", "glossary", "概念"),
    ("/backtest", "backtest", "回测"),
]


def export_static(out_dir: Path) -> list[Path]:
    from fastapi.testclient import TestClient

    from .. import config as cfg
    from . import create_app

    app = create_app(allowed_hosts={"testserver"})
    client = TestClient(app)
    static_root = Path(__file__).resolve().parent / "static"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 动态追加单标的详情页
    pages = list(PAGES) + [
        (f"/positions/{ins.id}", f"positions-{ins.id}", f"持仓·{ins.name}") for ins in cfg.load_config().instruments
    ]

    def read_asset(url: str) -> str:
        rel = url.split("/static/", 1)[1].split("?")[0]
        return (static_root / rel).read_text(encoding="utf-8")

    written: list[Path] = []
    for path, name, label in pages:
        resp = client.get(path, headers={"Host": "testserver"})
        resp.raise_for_status()
        html = resp.text
        # 内联样式表
        html = re.sub(
            r'<link rel="stylesheet" href="(/static/[^"]+)">',
            lambda m: "<style>\n" + read_asset(m.group(1)) + "\n</style>",
            html,
        )
        # 内联脚本
        html = re.sub(
            r'<script src="(/static/[^"]+)"></script>',
            lambda m: "<script>\n" + read_asset(m.group(1)) + "\n</script>",
            html,
        )
        # 导航与详情链接指向同级静态文件
        for p, n, _ in pages:
            html = html.replace(f'href="{p}"', f'href="{n}.html"')
        # 顶部页面切换下拉（用户建议）：固定在右上，随时换页
        options = "".join(
            f'<option value="{n}.html"{" selected" if n == name else ""}>{lab}</option>'
            for _, n, lab in pages
        )
        switcher = (
            '<select onchange="location.href=this.value" '
            'style="position:fixed;top:10px;right:14px;z-index:9999;padding:6px 10px;'
            'border-radius:8px;border:1px solid rgba(127,127,127,.4);font-size:14px;'
            "background:#fff;color:#111\">" + options + "</select>"
        )
        html = html.replace("</body>", switcher + "\n</body>")
        out = out_dir / f"{name}.html"
        out.write_text(html, encoding="utf-8")
        written.append(out)
    return written
