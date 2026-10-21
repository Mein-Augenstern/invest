/* 流水页交互：渲染状态、表单（按金额折算）、增删流水。
   数据来自服务端注入 STATE0，变更后以 /api 返回的最新 state 重渲染。 */
"use strict";

let STATE = window.STATE0;
const $ = (id) => document.getElementById(id);

const fmt = (v, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: d, minimumFractionDigits: d });

function tile(label, value, sub, meterPct) {
  const el = document.createElement("div");
  el.className = "tile";
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

function currentIns() { return STATE.instruments.find((i) => i.id === $("f-ins").value); }

function renderSummary() {
  const ins = currentIns();
  if (!ins) return;
  $("sum-title").textContent = `${ins.name} · 当前状态`;
  const s = $("summary"); s.textContent = "";
  s.appendChild(tile("持仓份额", fmt(ins.quantity), ins.avg_cost ? `平均成本 ${fmt(ins.avg_cost, 4)}` : ""));
  s.appendChild(tile(ins.price_label, ins.price === null ? "—" : fmt(ins.price, 4), ins.price_date || "未配置代码"));
  s.appendChild(tile("市值", ins.market_value === null ? "—" : fmt(ins.market_value), ins.unrealized === null ? "" : `浮动盈亏 ${fmt(ins.unrealized)}`));
  if (ins.is_pension) {
    if (ins.contribution_entered === false) {
      s.appendChild(tile(`${STATE.year}年缴存进度`, "未录入", "录入「缴存」后精确跟踪（与申购区分）"));
    } else {
      const pct = ins.annual_cap ? (ins.year_contribution / ins.annual_cap) * 100 : 0;
      s.appendChild(tile(`${STATE.year}年缴存进度`, fmt(ins.year_contribution, 0) + " / " + fmt(ins.annual_cap, 0), pct >= 100 ? "已缴满" : "未缴满", pct));
    }
  } else {
    s.appendChild(tile("累计现金分红", fmt(ins.cash_dividend), ""));
  }
}

function renderTrades() {
  const tbl = $("trades-table"); tbl.textContent = "";
  const head = document.createElement("tr");
  ["日期", "标的", "动作", "份额", "单价/净值", "费用", "备注", ""].forEach((h) => {
    const th = document.createElement("th"); th.textContent = h; head.appendChild(th);
  });
  const thead = document.createElement("thead"); thead.appendChild(head); tbl.appendChild(thead);
  const tbody = document.createElement("tbody"); tbl.appendChild(tbody);
  const nameOf = Object.fromEntries(STATE.instruments.map((i) => [i.id, i.name]));
  const rows = STATE.trades.slice(-40).reverse();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td"); td.colSpan = 8; td.textContent = "暂无流水，从上方表单开始录入";
    tr.appendChild(td); tbody.appendChild(tr); return;
  }
  rows.forEach((t) => {
    const tr = document.createElement("tr");
    [t.date, nameOf[t.instrument_id] || t.instrument_id, t.action_label, fmt(t.quantity), fmt(t.price, 4), t.fee ? fmt(t.fee) : "—", t.note || ""].forEach((v) => {
      const td = document.createElement("td"); td.textContent = String(v); if (typeof v === "number") td.className = "num"; tr.appendChild(td);
    });
    const td = document.createElement("td");
    const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn btn-sm btn-ghost-danger"; btn.textContent = "删除";
    btn.addEventListener("click", async () => {
      if (!confirm(`删除 ${t.date} ${t.action_label} ${t.quantity} 份？`)) return;
      const resp = await fetch("/api/trades/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ row: { date: t.date, instrument_id: t.instrument_id, action: t.action,
          quantity: t.quantity.toFixed(2), price: t.price.toFixed(4), fee: t.fee ? t.fee.toFixed(2) : "", note: t.note || "" } }),
      });
      const data = await resp.json();
      if (!resp.ok) { showMsg(data.error || "删除失败", true); return; }
      STATE = data.state; render(); showMsg("已删除", false);
    });
    td.appendChild(btn); tr.appendChild(td); tbody.appendChild(tr);
  });
}

function showMsg(text, isErr) {
  const m = $("msg"); m.textContent = text || "";
  m.className = isErr ? "text-danger ms-2" : "text-secondary ms-2";
}

function syncFields() {
  const action = $("f-action").value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const isBuy = action === "buy";
  const isContribute = action === "contribute";
  $("f-mode-box").style.display = isBuy ? "" : "none";
  $("f-amount-box").style.display = (isBuy && mode === "amount") || isContribute ? "" : "none";
  $("f-qty-box").style.display = (isBuy && mode === "qty") || (!isBuy && !isContribute) ? "" : "none";
  $("f-qty").required = (!isBuy || mode === "qty") && !isContribute;
  $("f-amount").required = (isBuy && mode === "amount") || isContribute;
  $("f-price").required = !isContribute;
  $("f-qty").min = action === "adjust" ? "-99999999" : "0";
  const amountLabel = $("f-amount").previousElementSibling;
  if (amountLabel) amountLabel.textContent = isContribute ? "缴存金额（元）" : "金额（元）";
  $("f-price-label").textContent = action === "dividend_cash" ? "每份分红（元）"
    : action === "adjust" ? "参考净值（留痕）" : isBuy ? "成交净值" : "成交价/净值";
  const priceCol = $("f-price").closest(".col-md-4");
  if (priceCol) priceCol.style.display = isContribute ? "none" : "";
  $("f-qty-label").textContent = action === "dividend_cash" ? "登记日持有份额"
    : action === "adjust" ? "校准份额（正/负）" : "份额";
  const ins = currentIns();
  $("price-hint").textContent = ins && ins.price !== null ? `最新${ins.price_label} ${fmt(ins.price, 4)}（${ins.price_date}）` : "";
}

function render() {
  const insSel = $("f-ins");
  const selected = insSel.value;
  insSel.textContent = "";
  STATE.instruments.forEach((i) => {
    const o = document.createElement("option");
    o.value = i.id; o.textContent = i.name;
    insSel.appendChild(o);
  });
  if (selected) insSel.value = selected;
  renderSummary();
  renderTrades();
  syncFields();
}

$("f-ins").addEventListener("change", () => { renderSummary(); syncFields(); });
$("f-action").addEventListener("change", syncFields);
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", syncFields));

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  showMsg("", false);
  const action = $("f-action").value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const price = parseFloat($("f-price").value);
  let quantity = parseFloat($("f-qty").value);
  let note = $("f-note").value.trim();
  if (action === "contribute") {
    const amount = parseFloat($("f-amount").value);
    if (!(amount > 0)) return showMsg("请填写缴存金额", true);
    if (!note) note = "养老金缴存";
    quantity = amount; price = 1.0;
  } else if (action === "buy" && mode === "amount") {
    const amount = parseFloat($("f-amount").value);
    if (!(amount > 0) || !(price > 0)) return showMsg("请填写金额与净值", true);
    quantity = amount / price;
    if (!note) note = `按金额 ${amount} 元折算`;
  }
  if (!(quantity > 0) && action !== "adjust") return showMsg("请填写份额（或金额+净值）", true);
  if (action === "adjust" && !quantity) return showMsg("请填写校准份额（非0）", true);
  const btn = $("submit"); btn.disabled = true;
  try {
    const resp = await fetch("/api/trades", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instrument_id: $("f-ins").value, action, date: $("f-date").value,
        quantity, price, fee: $("f-fee").value || 0, note,
      }),
    });
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

$("f-date").value = new Date().toISOString().slice(0, 10);
render();
