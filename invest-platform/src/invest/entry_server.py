"""手动录入服务：python -m invest entry → http://127.0.0.1:8765

为本机单用户设计的流水录入页（场外基金/养老金账户无API，流水靠手工）：
- 表单录入 buy/sell/dividend_cash，支持"按金额×当日净值"自动折算份额
- 即时汇总：持仓/平均成本/市值/浮动盈亏/年度缴存进度（复用账本层逻辑）
- 数据仍落 data/trades.csv（唯一事实源，gitignore 不出本机）

安全：仅绑定 127.0.0.1；校验 Host 头防 DNS 重绑定；无任何外部监听。
"""
from __future__ import annotations

import csv
import json
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as cfg
from .data.mysql_store import default_store

# 写入/校验逻辑已迁入 ledger.trades（锁+原子写）；此处 re-export 保持旧导入兼容
from .ledger.trades import (  # noqa: F401
    append_trade,
    delete_trade,
    validate_trade,
)


# ---------- 状态汇总（复用账本层） ----------

def state_payload(conf, store) -> dict:
    """deprecated 薄层：实际逻辑在 reporting.build_entry_state。"""
    from .ledger.trades import load_trades
    from .reporting import build_entry_state

    return build_entry_state(conf, store, load_trades(cfg.DATA_DIR / "trades.csv"))


# ---------- HTTP ----------

class EntryHandler(BaseHTTPRequestHandler):
    server_version = "invest-entry/0.1"

    def log_message(self, fmt, *args):  # 安静模式
        pass

    def _check_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if not self._check_host():
            return self._json({"error": "host not allowed"}, 403)
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/state":
            conf = cfg.load_config()
            store = default_store(cfg.DATA_DIR)
            return self._json(state_payload(conf, store))
        self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        if not self._check_host():
            return self._json({"error": "host not allowed"}, 403)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "请求体不是合法JSON"}, 400)

        conf = cfg.load_config()
        trades_path = cfg.DATA_DIR / "trades.csv"
        from .ledger.trades import load_trades

        if self.path == "/api/trades":
            trade, err = validate_trade(payload, conf, load_trades(trades_path))
            if err:
                return self._json({"error": err}, 422)
            append_trade(trades_path, trade)
            store = default_store(cfg.DATA_DIR)
            return self._json({"ok": True, "state": state_payload(conf, store)})
        if self.path == "/api/trades/delete":
            row = payload.get("row") or {}
            if not delete_trade(trades_path, row):
                return self._json({"error": "未找到该行（列表可能已变化），请刷新"}, 409)
            store = default_store(cfg.DATA_DIR)
            return self._json({"ok": True, "state": state_payload(conf, store)})
        self._json({"error": "not found"}, 404)


def run_server(port: int = 8765, open_browser: bool = True) -> None:
    url = f"http://127.0.0.1:{port}"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), EntryHandler)
    print(f"录入服务已启动: {url}（仅本机可访问，Ctrl+C 停止）")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>流水录入 · 个人投资平台</title>
<style>
  :root { color-scheme: light; }
  .ui-root {
    --page: #f9f9f7; --surface-1: #fcfcfb;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --s1: #2a78d6; --s1-wash: rgba(42,120,214,0.12);
    --danger: #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    .ui-root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --page: #0d0d0d; --surface-1: #1a1a19;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      --s1: #3987e5; --s1-wash: rgba(57,135,229,0.18);
      --danger: #e66767;
    }
  }
  * { box-sizing: border-box; }
  body.ui-root { margin: 0; padding: 24px; background: var(--page);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--text-primary); }
  .wrap { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: var(--text-secondary); font-size: 13px; margin-bottom: 16px; }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .card h2 { font-size: 14px; margin: 0 0 12px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  @media (max-width: 620px) { .grid { grid-template-columns: repeat(2, 1fr); } }
  .tile { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
  .tile .label { font-size: 12px; color: var(--text-secondary); }
  .tile .value { font-size: 19px; font-weight: 600; margin-top: 2px; }
  .tile .sub { font-size: 11px; margin: 2px 0 0; }
  .meter { height: 6px; border-radius: 3px; margin-top: 8px; background: var(--s1-wash); position: relative; overflow: hidden; }
  .meter .fill { position: absolute; inset: 0 auto 0 0; background: var(--s1); border-radius: 3px; }
  form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  @media (max-width: 620px) { form { grid-template-columns: 1fr; } }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 12px; color: var(--text-secondary); }
  .field input, .field select { background: var(--page); color: var(--text-primary);
    border: 1px solid var(--baseline); border-radius: 8px; padding: 8px 10px; font-size: 14px; font-family: inherit; }
  .field input:focus, .field select:focus { outline: 2px solid var(--s1); outline-offset: 1px; }
  .field.wide { grid-column: 1 / -1; }
  .radios { display: flex; gap: 14px; font-size: 13px; color: var(--text-secondary); align-items: center; height: 36px; }
  .hint { font-size: 11.5px; color: var(--muted); }
  button.primary { background: var(--s1); color: #fff; border: 0; border-radius: 8px;
    padding: 10px 18px; font-size: 14px; cursor: pointer; grid-column: 1 / -1; justify-self: start; }
  button.primary:disabled { opacity: 0.5; cursor: wait; }
  #msg { font-size: 13px; margin-left: 12px; }
  #msg.err { color: var(--danger); }
  #msg.ok { color: var(--text-secondary); }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--baseline); }
  td { padding: 6px 8px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  td.del { text-align: right; }
  button.del { background: none; border: 0; color: var(--muted); cursor: pointer; font-size: 12px; padding: 2px 6px; border-radius: 6px; }
  button.del:hover { color: var(--danger); background: var(--s1-wash); }
  footer { font-size: 11.5px; color: var(--muted); line-height: 1.7; }
</style>
</head>
<body class="ui-root">
<div class="wrap">
  <h1>流水录入 · 场外基金</h1>
  <p class="sub">数据写入本机 data/trades.csv（账本唯一事实源）；仅监听 127.0.0.1，不出本机</p>

  <div class="card">
    <h2 id="sum-title">—</h2>
    <div class="grid" id="summary"></div>
  </div>

  <div class="card">
    <h2>新增流水</h2>
    <form id="form">
      <div class="field">
        <label for="f-ins">标的</label>
        <select id="f-ins" required></select>
      </div>
      <div class="field">
        <label for="f-action">动作</label>
        <select id="f-action">
          <option value="buy">申购（缴存/买入）</option>
          <option value="sell">赎回（卖出）</option>
          <option value="dividend_cash">现金分红</option>
          <option value="dividend_reinvest">红利再投资</option>
          <option value="adjust">份额校准（对账差异，可负）</option>
        </select>
      </div>
      <div class="field">
        <label for="f-date">日期</label>
        <input id="f-date" type="date" required>
      </div>
      <div class="field" id="f-mode-box">
        <label for="f-mode">录入方式</label>
        <div class="radios">
          <label><input type="radio" name="mode" value="amount" checked> 按金额</label>
          <label><input type="radio" name="mode" value="qty"> 按份额</label>
        </div>
      </div>
      <div class="field" id="f-amount-box">
        <label for="f-amount">金额（元）</label>
        <input id="f-amount" type="number" step="0.01" min="0" placeholder="12000">
      </div>
      <div class="field" id="f-qty-box">
        <label for="f-qty" id="f-qty-label">份额</label>
        <input id="f-qty" type="number" step="0.01" min="0" placeholder="10000">
      </div>
      <div class="field">
        <label for="f-price" id="f-price-label">成交净值</label>
        <input id="f-price" type="number" step="0.0001" min="0" required placeholder="1.0215">
        <span class="hint" id="price-hint"></span>
      </div>
      <div class="field">
        <label for="f-fee">费用（可空）</label>
        <input id="f-fee" type="number" step="0.01" min="0" placeholder="0">
      </div>
      <div class="field wide">
        <label for="f-note">备注（可空）</label>
        <input id="f-note" type="text" placeholder="如：养老金年度缴存">
      </div>
      <button class="primary" id="submit" type="submit">保存流水</button>
    </form>
    <span id="msg"></span>
  </div>

  <div class="card">
    <h2>历史流水</h2>
    <div style="overflow-x:auto"><table id="trades-table"></table></div>
  </div>

  <footer>
    提示：录入后运行 invest snapshot / report / dashboard 即可看到账本与信号更新。
    本页面为个人决策支持工具的一部分，不构成投资建议。
  </footer>
</div>
<script>
"use strict";
const $ = id => document.getElementById(id);
let STATE = null;

const fmt = (v, d = 2) => v === null || v === undefined ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = s => s; // 全部通过 textContent 注入，无需转义

function tile(label, value, sub, meterPct) {
  const el = document.createElement("div"); el.className = "tile";
  const l = document.createElement("div"); l.className = "label"; l.textContent = label;
  const v = document.createElement("div"); v.className = "value"; v.textContent = value;
  el.append(l, v);
  if (sub) { const s = document.createElement("div"); s.className = "sub"; s.textContent = sub; el.appendChild(s); }
  if (meterPct !== undefined) {
    const m = document.createElement("div"); m.className = "meter";
    const fill = document.createElement("div"); fill.className = "fill";
    fill.style.width = Math.min(100, Math.max(0, meterPct)) + "%";
    m.appendChild(fill); el.appendChild(m);
  }
  return el;
}

function render() {
  const insSel = $("f-ins");
  const selected = insSel.value;
  insSel.textContent = "";
  STATE.instruments.forEach(i => {
    const o = document.createElement("option");
    o.value = i.id; o.textContent = i.name;
    insSel.appendChild(o);
  });
  if (selected) insSel.value = selected;

  renderSummary();
  renderTrades();
  syncFields();
}

function currentIns() { return STATE.instruments.find(i => i.id === $("f-ins").value); }

function renderSummary() {
  const ins = currentIns();
  if (!ins) return;
  $("sum-title").textContent = `${ins.name} · 当前状态`;
  const s = $("summary"); s.textContent = "";
  s.appendChild(tile("持仓份额", fmt(ins.quantity), ins.avg_cost ? `平均成本 ${fmt(ins.avg_cost, 4)}` : ""));
  s.appendChild(tile(ins.price_label, ins.price === null ? "—" : fmt(ins.price, 4), ins.price_date || "未配置代码"));
  s.appendChild(tile("市值", ins.market_value === null ? "—" : fmt(ins.market_value), ins.unrealized === null ? "" : `浮动盈亏 ${fmt(ins.unrealized)}`));
  if (ins.is_pension) {
    const pct = ins.annual_cap ? ins.year_contribution / ins.annual_cap * 100 : 0;
    s.appendChild(tile(`${STATE.year}年缴存进度`, fmt(ins.year_contribution, 0) + " / " + fmt(ins.annual_cap, 0), pct >= 100 ? "已缴满" : "未缴满", pct));
  } else {
    s.appendChild(tile("累计现金分红", fmt(ins.cash_dividend), ""));
  }
}

function renderTrades() {
  const tbl = $("trades-table"); tbl.textContent = "";
  const head = document.createElement("tr");
  ["日期", "标的", "动作", "份额", "单价/净值", "费用", "备注", ""].forEach(h => {
    const th = document.createElement("th"); th.textContent = h; head.appendChild(th);
  });
  tbl.appendChild(head);
  const nameOf = Object.fromEntries(STATE.instruments.map(i => [i.id, i.name]));
  const rows = STATE.trades.slice(-40).reverse();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td"); td.colSpan = 8; td.textContent = "暂无流水，从上方表单开始录入";
    tr.appendChild(td); tbl.appendChild(tr); return;
  }
  rows.forEach(t => {
    const tr = document.createElement("tr");
    [t.date, nameOf[t.instrument_id] || t.instrument_id, t.action_label, fmt(t.quantity), fmt(t.price, 4), t.fee ? fmt(t.fee) : "—", t.note || ""].forEach(v => {
      const td = document.createElement("td"); td.textContent = String(v); tr.appendChild(td);
    });
    const td = document.createElement("td"); td.className = "del";
    const btn = document.createElement("button"); btn.className = "del"; btn.type = "button"; btn.textContent = "删除";
    btn.addEventListener("click", async () => {
      if (!confirm(`删除 ${t.date} ${t.action_label} ${t.quantity} 份？`)) return;
      const resp = await fetch("/api/trades/delete", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ row: { date: t.date, instrument_id: t.instrument_id, action: t.action,
          quantity: t.quantity.toFixed(2), price: t.price.toFixed(4), fee: t.fee ? t.fee.toFixed(2) : "", note: t.note || "" } }) });
      const data = await resp.json();
      if (!resp.ok) { showMsg(data.error || "删除失败", true); return; }
      STATE = data.state; render(); showMsg("已删除", false);
    });
    td.appendChild(btn); tr.appendChild(td); tbl.appendChild(tr);
  });
}

function showMsg(text, isErr) {
  const m = $("msg"); m.textContent = text || ""; m.className = isErr ? "err" : "ok";
}

function syncFields() {
  const action = $("f-action").value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const isBuy = action === "buy";
  $("f-mode-box").style.display = isBuy ? "" : "none";
  $("f-amount-box").style.display = isBuy && mode === "amount" ? "" : "none";
  $("f-qty-box").style.display = (isBuy && mode === "qty") || !isBuy ? "" : "none";
  $("f-qty").required = !isBuy || mode === "qty";
  $("f-amount").required = isBuy && mode === "amount";
  $("f-qty").min = action === "adjust" ? "-99999999" : "0";
  $("f-price-label").textContent = action === "dividend_cash" ? "每份分红（元）"
    : (action === "adjust" ? "参考净值（留痕）" : (isBuy ? "成交净值" : "成交价/净值"));
  $("f-qty-label").textContent = action === "dividend_cash" ? "登记日持有份额"
    : (action === "adjust" ? "校准份额（正/负）" : "份额");
  const ins = currentIns();
  $("price-hint").textContent = ins && ins.price !== null ? `最新${ins.price_label} ${fmt(ins.price, 4)}（${ins.price_date}）` : "";
}

$("f-ins").addEventListener("change", renderSummary);
$("f-ins").addEventListener("change", syncFields);
$("f-action").addEventListener("change", syncFields);
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", syncFields));

$("form").addEventListener("submit", async ev => {
  ev.preventDefault();
  showMsg("", false);
  const action = $("f-action").value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const price = parseFloat($("f-price").value);
  let quantity = parseFloat($("f-qty").value);
  let note = $("f-note").value.trim();
  if (action === "buy" && mode === "amount") {
    const amount = parseFloat($("f-amount").value);
    if (!(amount > 0) || !(price > 0)) return showMsg("请填写金额与净值", true);
    quantity = amount / price;
    if (!note) note = `按金额 ${amount} 元折算`;
  }
  if (!(quantity > 0)) return showMsg("请填写份额（或金额+净值）", true);
  const btn = $("submit"); btn.disabled = true;
  try {
    const resp = await fetch("/api/trades", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instrument_id: $("f-ins").value, action, date: $("f-date").value,
        quantity, price, fee: $("f-fee").value || 0, note,
      }) });
    const data = await resp.json();
    if (!resp.ok) return showMsg(data.error || "保存失败", true);
    STATE = data.state; render();
    $("f-amount").value = ""; $("f-qty").value = ""; $("f-note").value = "";
    showMsg("已保存 ✓", false);
  } catch (e) {
    showMsg("网络错误: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
});

(async function init() {
  $("f-date").value = new Date().toISOString().slice(0, 10);
  const resp = await fetch("/api/state");
  STATE = await resp.json();
  render();
})();
</script>
</body>
</html>
"""
