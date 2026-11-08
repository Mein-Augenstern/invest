"""S11-AC8 账本迁移：trades.csv → store（trades 表，归属默认会员/运营者）。

幂等：库内已有与 CSV 逐行一致的数据时跳过；库内有数据但不一致则拒绝
（防重复追加）；迁移前自动备份 CSV。对账：行数 + 现金流合计（cash_flow 口径）。

用法（ECS 容器内，数据目录 /data）：
    docker exec invest-app uv run --no-dev python -m invest.migrate_trades
本地（缺省 data/）：
    cd invest-platform && uv run python -m invest.migrate_trades [data_dir]
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from .data.local import default_member_id
from .data.mysql_store import default_store
from .ledger.trades import load_trades


def _cash_total(trades) -> float:
    return round(sum(t.cash_flow for t in trades), 2)


def _db_cash_total(rows: list[dict]) -> float:
    total = 0.0
    for r in rows:
        amount = float(r["quantity"]) * float(r["price"])
        fee = float(r.get("fee") or 0)
        if r["action"] == "buy":
            total -= amount + fee
        elif r["action"] == "sell":
            total += amount - fee
        elif r["action"] == "dividend_cash":
            total += amount
    return round(total, 2)


def _rows_match(db_rows: list[dict], csv_trades: list) -> bool:
    if len(db_rows) != len(csv_trades):
        return False
    return all(
        r["date"] == t.date
        and r["instrument_id"] == t.instrument_id
        and r["action"] == t.action
        and abs(float(r["quantity"]) - t.quantity) < 1e-6
        and abs(float(r["price"]) - t.price) < 1e-6
        and abs(float(r.get("fee") or 0) - t.fee) < 1e-6
        for r, t in zip(db_rows, csv_trades)
    )


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    csv_path = data_dir / "trades.csv"
    member_id = default_member_id()
    store = default_store(data_dir)

    csv_trades = load_trades(csv_path) if csv_path.exists() else []
    db_rows = store.list_trades(member_id)
    print(f"会员 {member_id}：CSV {len(csv_trades)} 行 / 库 {len(db_rows)} 行")
    print(f"CSV 现金流合计: {_cash_total(csv_trades)}（负=净投入）")

    if _rows_match(db_rows, csv_trades):
        print("已迁移过（幂等跳过）")
        return 0
    if db_rows:
        print(f"库内已有 {len(db_rows)} 行且与 CSV 不一致——请人工核对后再迁移（避免重复追加）")
        return 1
    if not csv_trades:
        print("CSV 无数据，无需迁移")
        return 0

    bak = csv_path.with_name(f"trades.csv.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(csv_path, bak)
    print(f"已备份: {bak.name}")

    store.append_trades(member_id, [t.__dict__ for t in csv_trades])

    rows_after = store.list_trades(member_id)
    if len(rows_after) != len(csv_trades):
        print(f"行数不一致：{len(rows_after)} != {len(csv_trades)}（用备份核查）")
        return 2
    db_cash = _db_cash_total(rows_after)
    print(f"迁移完成：{len(rows_after)} 行；库现金流合计 {db_cash}（CSV {_cash_total(csv_trades)}）")
    if abs(db_cash - _cash_total(csv_trades)) > 0.01:
        print("现金流对账不一致！请用备份核查（库已写入，可按备份人工修正）")
        return 3
    print("对账一致（行数 + 现金流）；CSV 保留为原始凭证（业务读取已切库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
