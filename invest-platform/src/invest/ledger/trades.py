"""交易流水模型。

data/trades.csv 列: date, instrument_id, action, quantity, price, fee, note
action ∈ { buy, sell, dividend_cash }
  - buy/sell: quantity=份额, price=成交价
  - dividend_cash: quantity=当时持有份额, price=每份分红金额（现金分红）
养老金缴存按 buy 记录（钱→份额），不在账本层单独建"缴存"动作。
"""
from __future__ import annotations

import csv
import io
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ACTIONS = {"buy", "sell", "dividend_cash", "dividend_reinvest", "adjust", "contribute"}


@dataclass
class Trade:
    date: str  # YYYY-MM-DD
    instrument_id: str
    action: str
    quantity: float
    price: float
    fee: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"未知 action: {self.action!r}（合法值: {sorted(ACTIONS)}）")

    @property
    def cash_flow(self) -> float:
        """资金加权口径：负=净投入，正=净回收。红利再投资/份额校准无现金流（内部转化）。"""
        amount = self.quantity * self.price
        if self.action == "buy":
            return -(amount + self.fee)
        if self.action == "sell":
            return amount - self.fee
        if self.action in ("dividend_reinvest", "adjust", "contribute"):
            return 0.0  # 账户入金不是基金现金流；缴存进度单独统计
        return amount  # dividend_cash


def load_trades(path: Path) -> list[Trade]:
    p = Path(path)
    if not p.exists():
        return []
    trades: list[Trade] = []
    with open(p, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            trades.append(
                Trade(
                    date=row["date"].strip(),
                    instrument_id=row["instrument_id"].strip(),
                    action=row["action"].strip(),
                    quantity=float(row["quantity"]),
                    price=float(row["price"]),
                    fee=float(row.get("fee") or 0),
                    note=(row.get("note") or "").strip(),
                )
            )
    return trades


# ---------- 写入层（web表单/旧录入页共用；单进程内并发安全） ----------

COLUMNS = ["date", "instrument_id", "action", "quantity", "price", "fee", "note"]

# RLock：save_validated_trade 持锁调用 append_trade（重入）
_WRITE_LOCK = threading.RLock()


def validate_trade(payload: dict, conf, trades: list[Trade]) -> tuple[dict | None, str]:
    """服务端校验：字段合法 + 卖出不得超持仓。返回 (trade行, 错误信息)。"""
    try:
        instrument_id = str(payload.get("instrument_id", "")).strip()
        action = str(payload.get("action", "")).strip()
        date = str(payload.get("date", "")).strip()
        quantity = round(float(payload.get("quantity")), 2)
        price = float(payload.get("price"))
        fee = float(payload.get("fee") or 0)
    except (TypeError, ValueError):
        return None, "数值字段格式不正确"
    note = str(payload.get("note", "")).strip()

    if instrument_id not in {i.id for i in conf.instruments}:
        return None, "未知标的"
    if action not in ACTIONS:
        return None, "未知动作"
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, "日期格式应为 YYYY-MM-DD"
    if action == "contribute":
        # 缴存=个人养老金账户入金（从银行卡进账户，未买基金）：
        # quantity=金额(元)，price固定1.0；年度12,000上限管的是它
        if quantity <= 0:
            return None, "缴存金额必须为正数"
        price = 1.0
    elif action == "adjust":
        if quantity == 0:
            return None, "校准份额不能为0"
        if price < 0:
            return None, "参考净值必须为非负数"
    else:
        if quantity <= 0 or price < 0:
            return None, "份额/价格必须为正数"
        if action in ("dividend_cash", "dividend_reinvest") and price <= 0:
            return None, "分红/再投资必须填当日净值或每份分红"

    if action == "sell":
        from .ledger import build_positions

        pos = build_positions(trades).get(instrument_id)
        held = pos.quantity if pos else 0.0
        if quantity > held + 1e-6:
            return None, f"赎回超过持仓：当前持有 {held:,.2f} 份"

    return (
        {
            "date": date,
            "instrument_id": instrument_id,
            "action": action,
            "quantity": f"{quantity:.2f}",
            "price": f"{price:.4f}",
            "fee": f"{fee:.2f}" if fee else "",
            "note": note,
        },
        "",
    )


def _safe_csv_path(trades_path: Path) -> Path:
    """路径穿越防护：账本文件必须是数据目录内的相对路径（拒绝绝对路径与 ..）。"""
    p = Path(trades_path)
    if ".." in p.parts:
        raise ValueError(f"非法账本路径: {trades_path}")
    if p.is_absolute():
        # 绝对路径仅放行平台数据目录与系统临时目录（单测形态），其余拒绝
        import tempfile

        from .. import config as _cfg

        resolved = p.resolve()
        roots = {str(_cfg.DATA_DIR.resolve()), str(Path(tempfile.gettempdir()).resolve())}
        if not any(str(resolved) == r or str(resolved).startswith(r.rstrip("/") + "/") for r in roots):
            raise ValueError(f"非法账本路径: {trades_path}")
    return p


def append_trade(trades_path: Path, t: dict) -> None:
    """追加一行流水（持锁）。"""
    with _WRITE_LOCK:
        trades_path = _safe_csv_path(trades_path)
        trades_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not trades_path.exists()
        with open(trades_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                w.writeheader()
            w.writerow({k: t.get(k, "") for k in COLUMNS})


def delete_trade(trades_path: Path, row: dict) -> bool:
    """按整行内容匹配删除（临时文件+原子替换）；不匹配返回 False。"""
    with _WRITE_LOCK:
        trades_path = _safe_csv_path(trades_path)
        if not trades_path.exists():
            return False
        with open(trades_path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        keep = [r for r in rows if any((r.get(k) or "") != str(row.get(k, "")) for k in COLUMNS)]
        if len(keep) == len(rows):
            return False
        # 序列化在内存 StringIO 完成，落盘用 Path.write_text + os.replace
        # 原子替换：既有"写一半崩溃不丢原文件"的保障，也不出现裸 open()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(keep)
        tmp = _safe_csv_path(trades_path.with_suffix(".csv.tmp"))
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, trades_path)
        return True


def save_validated_trade(trades_path: Path, payload: dict, conf, trades: list[Trade]) -> tuple[dict | None, str]:
    """校验+追加在同一把锁内（校验要读持仓，锁外校验会因并发写失效）。"""
    with _WRITE_LOCK:
        trade, err = validate_trade(payload, conf, trades)
        if err:
            return None, err
        append_trade(trades_path, trade)
        return trade, ""
