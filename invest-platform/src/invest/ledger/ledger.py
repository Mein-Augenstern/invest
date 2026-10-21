"""持仓与成本：移动平均成本法。"""
from __future__ import annotations

from dataclasses import dataclass

from .trades import Trade


@dataclass
class Position:
    instrument_id: str
    quantity: float = 0.0
    cost: float = 0.0  # 未平仓部分总成本（含费用）
    realized_pnl: float = 0.0  # 累计已实现盈亏（含费用）
    cash_dividend: float = 0.0  # 累计现金分红
    contributed: float = 0.0  # 累计缴存（账户入金，非基金现金流）

    def apply(self, t: Trade) -> None:
        if t.action == "buy":
            self.quantity += t.quantity
            self.cost += t.quantity * t.price + t.fee
        elif t.action == "sell":
            if t.quantity > self.quantity + 1e-9:
                raise ValueError(
                    f"{t.instrument_id} 卖出超过持仓: 卖 {t.quantity} / 持 {self.quantity}（{t.date}）"
                )
            avg = self.cost / self.quantity if self.quantity else 0.0
            self.realized_pnl += t.quantity * (t.price - avg) - t.fee
            self.cost -= t.quantity * avg
            self.quantity -= t.quantity
        elif t.action == "dividend_cash":
            self.cash_dividend += t.quantity * t.price
        elif t.action == "contribute":
            self.contributed += t.quantity * t.price
        elif t.action in ("dividend_reinvest", "adjust"):
            # 份额变化、无现金流、不加成本：与基金App的"市值-现金投入"口径一致
            # dividend_reinvest: 红利再投资增加份额；adjust: 与App对账的份额校准(±)
            self.quantity += t.quantity


def build_positions(trades: list[Trade]) -> dict[str, Position]:
    positions: dict[str, Position] = {}
    for t in sorted(trades, key=lambda x: x.date):
        pos = positions.setdefault(t.instrument_id, Position(instrument_id=t.instrument_id))
        pos.apply(t)
    return positions


def avg_cost(pos: Position) -> float:
    return pos.cost / pos.quantity if pos.quantity else 0.0


def unrealized_pnl(pos: Position, price: float) -> float:
    return pos.quantity * price - pos.cost
