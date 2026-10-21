"""流水写入层：并发安全与原子性。"""
import threading

from invest import config as cfg
from invest.ledger.trades import (
    append_trade,
    delete_trade,
    load_trades,
    save_validated_trade,
)


def _row(i=1):
    return {
        "date": "2026-01-05", "instrument_id": "fund_a", "action": "buy",
        "quantity": "100.00", "price": "1.0000", "fee": "", "note": f"n{i}",
    }


def test_concurrent_append_no_loss_or_interleave(tmp_path):
    path = tmp_path / "trades.csv"

    def worker(wid):
        for j in range(25):
            row = _row(wid * 100 + j)
            row["quantity"] = f"{wid * 100 + j}.00"
            append_trade(path, row)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    trades = load_trades(path)
    assert len(trades) == 100  # 无丢失
    assert len({t.quantity for t in trades}) == 100  # 无交错覆盖


def test_delete_is_atomic_and_idempotent(tmp_path):
    path = tmp_path / "trades.csv"
    append_trade(path, _row(1))
    append_trade(path, _row(2))
    assert delete_trade(path, _row(1)) is True
    assert delete_trade(path, _row(1)) is False  # 重复删返回 False
    assert len(load_trades(path)) == 1
    assert not (tmp_path / "trades.tmp").exists()  # 无临时文件残留


def _conf():
    return cfg.Portfolio(
        source="test.yaml",
        instruments=[cfg.Instrument(id="fund_a", type="open_end_fund", name="F", account="pension")],
        accounts={"pension": cfg.Account(id="pension", name="养老金")},
        strategy=cfg.StrategyConfig(),
    )


def test_save_validated_trade_rejects_and_appends(tmp_path):
    path = tmp_path / "trades.csv"
    conf = _conf()
    ok, err = save_validated_trade(
        path, {"instrument_id": "fund_a", "action": "buy", "date": "2026-01-05",
               "quantity": 1000, "price": 1.0, "fee": 0, "note": ""}, conf, [],
    )
    assert err == "" and ok is not None
    # 超卖被拒且不落盘
    bad, err = save_validated_trade(
        path, {"instrument_id": "fund_a", "action": "sell", "date": "2026-02-01",
               "quantity": 2000, "price": 1.1, "fee": 0, "note": ""}, conf, load_trades(path),
    )
    assert bad is None and "赎回超过持仓" in err
    assert len(load_trades(path)) == 1
