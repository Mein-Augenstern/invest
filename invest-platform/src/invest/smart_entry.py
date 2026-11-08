"""智能录入 v1：一句话 → 流水草稿（规则解析，确定性可测；LLM 增强后续叠加）。

输入示例：
    今天买入消费50 1000元
    昨天定投红利 500 手续费1.5
    11月3日 卖出中证红利 2000份 净值1.23
    缴存养老金 3000

解析维度：日期 / 动作 / 标的（模糊匹配，歧义返回候选）/ 金额或份额 / 费用。
设计约束：只产草稿不落库；不确定的字段进 missing 由用户补，绝不猜金额。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

#: 动作词 → 标准动作（顺序即优先级：长词在前防误吞）
_ACTION_PATTERNS: list[tuple[str, str]] = [
    ("红利再投", "dividend_reinvest"), ("再投资", "dividend_reinvest"),
    ("现金分红", "dividend_cash"), ("分红", "dividend_cash"),
    ("份额校准", "adjust"), ("校准", "adjust"),
    ("缴存", "contribute"), ("存入", "contribute"),
    ("申购", "buy"), ("定投", "buy"), ("买入", "buy"), ("买", "buy"),
    ("赎回", "sell"), ("卖出", "sell"), ("卖", "sell"),
]


def parse_date(text: str) -> tuple[str, str]:
    """提取日期，返回 (日期, 去掉日期词后的文本)。缺省今天。"""
    today = date.today()
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.isoformat(), text[: m.start()] + text[m.end():]
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            return d.isoformat(), text[: m.start()] + text[m.end():]
        except ValueError:
            pass
    for word, delta in (("前天", 2), ("昨天", 1), ("今天", 0)):
        if word in text:
            d = today - timedelta(days=delta)
            return d.isoformat(), text.replace(word, "", 1)
    return today.isoformat(), text


def parse_action(text: str) -> tuple[str | None, str]:
    for pat, action in _ACTION_PATTERNS:
        if pat in text:
            return action, text.replace(pat, " ", 1)
    return None, text


def _match_instrument(text: str, instruments: list) -> tuple[object | None, list]:
    """标的名匹配：id 精确 > 名称包含于文本 > 文本片段包含于名称（最长命中优先）。
    双向匹配支撑简称（如「红利」命中「中证红利基金(…)」）。歧义返回候选。"""
    hits: list[tuple[int, object]] = []
    for ins in instruments:
        name = getattr(ins, "name", "") or ""
        iid = getattr(ins, "id", "") or ""
        if iid and re.search(rf"\b{re.escape(iid)}\b", text):
            return ins, []
        stem = re.sub(r"[()（(].*$", "", name).strip() or name
        best_len = 0
        for cand in {name, stem}:
            if len(cand) >= 2 and cand in text:
                best_len = max(best_len, len(cand))
        if not best_len:
            # 反向：文本里的中文片段（≥2 字）出现在名称中，取最长
            for frag in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text):
                if frag in name or frag in stem:
                    best_len = max(best_len, len(frag))
        if best_len >= 2:
            hits.append((best_len, ins))
    if not hits:
        return None, []
    hits.sort(key=lambda x: -x[0])
    best = hits[0][1]
    same_len = [ins for n, ins in hits if n == hits[0][0] and ins is not best]
    return best, same_len


def parse_trade_text(text: str, instruments: list, latest_price_of=None) -> dict:
    """一句话 → 草稿。latest_price_of(instrument_id) -> float|None 提供最新价
    （金额→份额换算用）。返回 {draft, instrument, candidates, missing, explanation}。
    """
    text = (text or "").strip()
    if not text:
        return {"draft": None, "instrument": None, "candidates": [], "missing": ["text"], "explanation": "请输入内容"}

    rest = text
    d, rest = parse_date(rest)
    action, rest = parse_action(rest)
    ins, candidates = _match_instrument(rest, instruments)

    fee = None
    m = re.search(r"(?:手续费|费用|费)\s*([\d.]+)\s*元?", rest)
    if m:
        fee = float(m.group(1))
        rest = rest[: m.start()] + rest[m.end():]

    amount = None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*[元块]", rest)
    if m:
        amount = float(m.group(1).replace(",", ""))
        rest = rest[: m.start()] + rest[m.end():]

    qty = None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*份", rest)
    if m:
        qty = float(m.group(1).replace(",", ""))
        rest = rest[: m.start()] + rest[m.end():]

    price = None
    m = re.search(r"(?:净值|价格|价)\s*([\d.]+)", rest)
    if m:
        price = float(m.group(1))
        rest = rest[: m.start()] + rest[m.end():]

    # 裸数字兜底：无单位时视为金额（如「缴存养老金 3000」「定投红利 500」）
    if amount is None and qty is None and price is None:
        m = re.search(r"(\d{2,}(?:\.\d+)?)", rest)
        if m:
            amount = float(m.group(1))

    missing: list[str] = []
    if action is None:
        missing.append("action")
        action = "buy"  # 缺省买入，用户可改
    if ins is None:
        missing.append("instrument_id")
    # 金额→份额换算（有标的且有最新价时；缴存无需价格恒为1）
    if qty is None and amount is not None and ins is not None:
        if action == "contribute":
            qty, price = amount, 1.0
            amount = None
        elif price is None and latest_price_of is not None:
            px = latest_price_of(getattr(ins, "id"))
            if px:
                price = px
    if qty is None and amount is not None and price:
        qty = round(amount / price, 2)
    if qty is None:
        missing.append("quantity")  # 金额未能折算份额（无净值）也算缺——绝不猜数

    draft = {
        "date": d,
        "instrument_id": getattr(ins, "id", "") or "",
        "action": action,
        "quantity": qty if qty is not None else (amount if action == "contribute" else None),
        "price": price if price is not None else (1.0 if action == "contribute" else None),
        "fee": fee or 0,
        "note": text,
    }
    why = [f"日期={d}", f"动作={action}"]
    if ins is not None:
        why.append(f"标的={getattr(ins, 'name', ins)}")
    if amount is not None:
        why.append(f"金额={amount:g}" + (f"→份额{qty:g}" if qty is not None else ""))
    elif qty is not None:
        why.append(f"份额={qty:g}")
    return {
        "draft": draft,
        "instrument": {"id": getattr(ins, "id", ""), "name": getattr(ins, "name", "")} if ins else None,
        "candidates": [{"id": getattr(c, "id", ""), "name": getattr(c, "name", "")} for c in candidates],
        "missing": missing,
        "explanation": "；".join(why) + ("；待补字段：" + ",".join(missing) if missing else ""),
    }
