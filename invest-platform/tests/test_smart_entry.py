"""智能录入 v1：一句话解析规则的单测（确定性，无网络/无 LLM）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from invest.smart_entry import parse_trade_text  # noqa: E402


class _Ins:
    def __init__(self, id, name, code=""):
        self.id, self.name, self.code = id, name, code


INSTRUMENTS = [
    _Ins("consumer50_etf", "消费50ETF"),
    _Ins("csi_dividend_pension", "中证红利基金(个人养老金Y份额)"),
]


def test_basic_buy_by_amount():
    r = parse_trade_text("今天买入消费50 1000元", INSTRUMENTS, lambda _: 0.5)
    d = r["draft"]
    assert d["instrument_id"] == "consumer50_etf"
    assert d["action"] == "buy"
    assert d["quantity"] == 2000.0  # 1000元 ÷ 最新净值0.5
    assert d["price"] == 0.5
    assert r["missing"] == []


def test_yesterday_dingtou_with_fee():
    r = parse_trade_text("昨天定投红利 500 手续费1.5", INSTRUMENTS, lambda _: None)
    d = r["draft"]
    assert d["action"] == "buy"
    assert d["instrument_id"] == "csi_dividend_pension"  # 名称主干包含匹配
    assert d["fee"] == 1.5
    assert "quantity" in r["missing"]  # 无净值无法折份额——交用户补，绝不猜


def test_sell_by_shares_with_nav():
    r = parse_trade_text("11月3日 卖出中证红利 2000份 净值1.23", INSTRUMENTS)
    d = r["draft"]
    assert d["action"] == "sell"
    assert d["quantity"] == 2000
    assert d["price"] == 1.23
    assert d["date"].endswith("-11-03")


def test_contribute_needs_no_price():
    r = parse_trade_text("缴存养老金 3000", INSTRUMENTS)
    d = r["draft"]
    assert d["action"] == "contribute"
    assert d["quantity"] == 3000 and d["price"] == 1.0


def test_unknown_instrument_returns_missing_not_guess():
    r = parse_trade_text("买入不存在的标的 100元", INSTRUMENTS)
    assert "instrument_id" in r["missing"]
    assert r["instrument"] is None
