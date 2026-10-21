/* invest-charts.js — 自包含 SVG 折线图（无外部依赖，dataviz 规范：2px线/端点标记带表面环/发丝网格/十字线tooltip）。
   契约：
     lineChart(host, series, opts)
       host   容器元素（建议 .viz-scope .chart-box：固定高度、contain 隔离）
       series [{name, color, points:[[utc毫秒, 数值], ...]}]  color 可为 CSS 变量名("--s1")或色值
       opts   {fmt, endLabel(默认true), events:[{ts,label,kind}], tooltip(默认true)}
     monthlyTable(host, series, fmt)  月度数据表（无障碍的数据视图）
   图表按容器实际像素尺寸绘制（viewBox=容器宽高，零缩放零letterbox），
   窗口尺寸变化自动按新宽度重绘；tooltip 自建自管。 */
"use strict";

(function () {
  function scopeOf(host) {
    return host.closest(".viz-scope") || document.documentElement;
  }
  function cssVar(host, name) {
    return getComputedStyle(scopeOf(host)).getPropertyValue(name).trim();
  }
  function resolveColor(host, c) {
    if (typeof c === "string" && c.startsWith("--")) {
      return cssVar(host, c) || "#2a78d6";
    }
    return c;
  }
  const svgNS = "http://www.w3.org/2000/svg";
  // 交易事件语义色（浅暗两模式对比度已验证；颜色+形状+浮窗三重编码）
  const ACTION_COLORS = { buy: "#d03b3b", sell: "#0ca30c", div: "#fab219" };
  const actionColor = (kind) => ACTION_COLORS[kind === "buy" || kind === "sell" ? kind : "div"];

  function drawChart(host, series, opts) {
    const fmtV = opts.fmt || ((v) => v.toFixed(2));
    // 按容器实际像素绘制：无缩放、无letterbox，绘图区顶到容器两侧
    const W = Math.max(420, Math.round(host.clientWidth) || 640);
    const H = Math.max(160, Math.round(host.clientHeight) || 230);
    const L = 46, R = 8, T = 14, B = 26;
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const all = series.flatMap((s) => s.points);
    if (!all.length) return null;
    const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = (y1 - y0) * 0.06 || 1;
    y0 -= pad; y1 += pad;
    const X = (v) => L + ((v - x0) / (x1 - x0 || 1)) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
    const fmtDate = (ts) => new Date(ts).toISOString().slice(0, 10);
    const gridC = cssVar(host, "--grid") || "#e1e0d9";
    const baseC = cssVar(host, "--baseline") || "#c3c2b7";
    const surfC = cssVar(host, "--surface-1") || "#fcfcfb";

    const step = (y1 - y0) / 4, dec = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
    for (let i = 0; i <= 4; i++) {
      const v = y0 + step * i, y = Y(v);
      const g = document.createElementNS(svgNS, "line");
      g.setAttribute("x1", L); g.setAttribute("x2", W - R);
      g.setAttribute("y1", y); g.setAttribute("y2", y);
      g.setAttribute("stroke", gridC); g.setAttribute("stroke-width", "1");
      svg.appendChild(g);
      const t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", L - 8); t.setAttribute("y", y + 4); t.setAttribute("text-anchor", "end");
      t.setAttribute("class", "axis-t"); t.textContent = v.toFixed(dec);
      svg.appendChild(t);
    }
    const nX = Math.max(4, Math.min(8, Math.floor(W / 180))); // 宽图多几个刻度
    for (let i = 0; i <= nX; i++) {
      const ts = x0 + ((x1 - x0) * i) / nX, x = X(ts);
      const t = document.createElementNS(svgNS, "text");
      t.setAttribute("x", x); t.setAttribute("y", H - 8); t.setAttribute("text-anchor", "middle");
      t.setAttribute("class", "axis-t"); t.textContent = fmtDate(ts).slice(0, 7);
      svg.appendChild(t);
    }

    const colors = series.map((s) => resolveColor(host, s.color));
    series.forEach((s, i) => {
      const p = document.createElementNS(svgNS, "path");
      p.setAttribute(
        "d",
        s.points.map((pt, j) => `${j ? "L" : "M"}${X(pt[0]).toFixed(1)},${Y(pt[1]).toFixed(1)}`).join("")
      );
      p.setAttribute("fill", "none"); p.setAttribute("stroke", colors[i]);
      p.setAttribute("stroke-width", "2");
      p.setAttribute("stroke-linejoin", "round"); p.setAttribute("stroke-linecap", "round");
      svg.appendChild(p);
    });

    const ends = series.map((s, i) => ({ i, pt: s.points[s.points.length - 1] })).sort((a, b) => b.pt[1] - a.pt[1]);
    ends.forEach((e, i) => {
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("cx", X(e.pt[0])); c.setAttribute("cy", Y(e.pt[1]));
      c.setAttribute("r", "4.5"); c.setAttribute("fill", colors[e.i]);
      c.setAttribute("stroke", surfC); c.setAttribute("stroke-width", "2");
      svg.appendChild(c);
      if (opts.endLabel !== false && series.length > 1) {
        const t = document.createElementNS(svgNS, "text");
        t.setAttribute("x", X(e.pt[0]) - 10); t.setAttribute("text-anchor", "end");
        t.setAttribute("y", Y(e.pt[1]) + (ends.length > 1 ? (i === 0 ? -8 : 14) : 4));
        t.setAttribute("class", "end-label"); t.textContent = fmtV(e.pt[1]);
        svg.appendChild(t);
      }
    });

    // 交易事件标记（红▲申购 绿▼赎回 金◆分红）
    if (opts.events && opts.events.length && series.length) {
      const pts = series[0].points;
      opts.events.forEach((ev) => {
        let best = pts[0], bd = Infinity;
        for (const p of pts) { const d = Math.abs(p[0] - ev.ts); if (d < bd) { bd = d; best = p; } }
        if (bd > 45 * 24 * 3600 * 1000) return;
        const x = X(best[0]), y = Y(best[1]);
        const m = document.createElementNS(svgNS, "path");
        let d;
        if (ev.kind === "sell") d = `M${x},${y - 5} L${x - 5},${y - 14} L${x + 5},${y - 14} Z`;
        else if (ev.kind === "buy") d = `M${x},${y + 5} L${x - 5},${y + 14} L${x + 5},${y + 14} Z`;
        else d = `M${x},${y - 7} L${x + 6},${y} L${x},${y + 7} L${x - 6},${y} Z`;
        m.setAttribute("d", d);
        m.setAttribute("fill", actionColor(ev.kind));
        m.setAttribute("stroke", surfC);
        m.setAttribute("stroke-width", "1.5");
        svg.appendChild(m);
      });
    }

    host.appendChild(svg);

    if (opts.tooltip === false) return null;

    // ---- tooltip 自建自管 ----
    const tip = document.createElement("div");
    tip.className = "viz-tooltip";
    document.body.appendChild(tip);
    const cross = document.createElementNS(svgNS, "line");
    cross.setAttribute("y1", T); cross.setAttribute("y2", H - B);
    cross.setAttribute("stroke", baseC); cross.setAttribute("stroke-width", "1");
    cross.style.display = "none";
    svg.appendChild(cross);
    const dots = series.map(() => {
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("r", "3.5"); c.style.display = "none";
      svg.appendChild(c);
      return c;
    });
    svg.addEventListener("pointermove", (ev) => {
      // getScreenCTM 逆变换：任意缩放/留边下鼠标坐标都换算正确
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const p = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(ctm.inverse());
      const px = p.x;
      const ts = x0 + ((px - L) / (W - L - R || 1)) * (x1 - x0);
      let best = all[0], bd = Infinity;
      for (const q of all) { const d = Math.abs(q[0] - ts); if (d < bd) { bd = d; best = q; } }
      cross.style.display = "";
      cross.setAttribute("x1", X(best[0])); cross.setAttribute("x2", X(best[0]));
      tip.textContent = "";
      const d = document.createElement("div"); d.className = "t-date"; d.textContent = fmtDate(best[0]); tip.appendChild(d);
      series.forEach((s, i) => {
        let sb = s.points[0], sbd = Infinity;
        for (const q of s.points) { const dd = Math.abs(q[0] - best[0]); if (dd < sbd) { sbd = dd; sb = q; } }
        dots[i].style.display = "";
        dots[i].setAttribute("cx", X(sb[0])); dots[i].setAttribute("cy", Y(sb[1]));
        dots[i].setAttribute("fill", colors[i]); dots[i].setAttribute("stroke", surfC);
        const row = document.createElement("div"); row.className = "row";
        const k = document.createElement("span"); k.className = "key"; k.style.background = colors[i];
        const nm = document.createElement("span"); nm.textContent = s.name;
        const v = document.createElement("span"); v.className = "val"; v.textContent = fmtV(sb[1]);
        row.append(k, nm, v);
        tip.appendChild(row);
      });
      if (opts.events) {
        opts.events.forEach((ev) => {
          if (Math.abs(ev.ts - best[0]) <= 3 * 24 * 3600 * 1000) {
            const row = document.createElement("div"); row.className = "row";
            const glyph = ev.kind === "buy" ? "▲" : ev.kind === "sell" ? "▼" : "◆";
            const g = document.createElement("span"); g.textContent = glyph; g.style.color = actionColor(ev.kind);
            const nm = document.createElement("span"); nm.textContent = ev.label;
            row.append(g, nm);
            tip.appendChild(row);
          }
        });
      }
      tip.style.display = "block";
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 170) + "px";
      tip.style.top = ev.clientY + 14 + "px";
    });
    svg.addEventListener("pointerleave", () => {
      tip.style.display = "none";
      cross.style.display = "none";
      dots.forEach((c) => (c.style.display = "none"));
    });
    return tip;
  }

  // ---- 容器尺寸变化时按新宽度重绘（防抖） ----
  const registry = [];
  let resizeBound = false;
  function bindResize() {
    if (resizeBound) return;
    resizeBound = true;
    let t = null;
    window.addEventListener("resize", () => {
      clearTimeout(t);
      t = setTimeout(() => registry.forEach((e) => e.render()), 200);
    });
  }

  function lineChart(host, series, opts = {}) {
    let tipEl = null;
    function render() {
      if (tipEl) { tipEl.remove(); tipEl = null; }
      host.textContent = "";
      tipEl = drawChart(host, series, opts);
    }
    render();
    const existing = registry.find((e) => e.host === host);
    if (existing) existing.render = render;
    else registry.push({ host, render });
    bindResize();
  }

  function monthlyTable(host, series, fmt) {
    const tbl = document.createElement("table");
    tbl.className = "table table-sm table-vcenter";
    const months = new Map();
    series.forEach((s) =>
      s.points.forEach((p) => {
        const m = new Date(p[0]).toISOString().slice(0, 7);
        if (!months.has(m)) months.set(m, {});
        months.get(m)[s.name] = p[1];
      })
    );
    const names = series.map((s) => s.name);
    const head = document.createElement("tr");
    ["月份", ...names].forEach((h) => {
      const th = document.createElement("th"); th.textContent = h; head.appendChild(th);
    });
    const thead = document.createElement("thead"); thead.appendChild(head); tbl.appendChild(thead);
    const tbody = document.createElement("tbody"); tbl.appendChild(tbody);
    [...months.entries()].slice(-24).reverse().forEach(([m, row]) => {
      const tr = document.createElement("tr");
      [m, ...names.map((n) => (row[n] !== undefined ? fmt(row[n]) : "—"))].forEach((v) => {
        const td = document.createElement("td"); td.textContent = v; tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    host.appendChild(tbl);
  }

  // SVG 内文字样式（一次性注入 <style>）
  if (!document.getElementById("invest-charts-style")) {
    const st = document.createElement("style");
    st.id = "invest-charts-style";
    st.textContent = ".viz-scope svg .axis-t{font-size:11px;fill:var(--muted,#898781);font-variant-numeric:tabular-nums}"
      + ".viz-scope svg .end-label{font-size:12px;font-weight:600;fill:var(--text-primary,#0b0b0b)}";
    document.head.appendChild(st);
  }

  window.investCharts = { lineChart, monthlyTable };
})();
