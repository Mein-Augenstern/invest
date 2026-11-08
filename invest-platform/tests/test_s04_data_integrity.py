"""S04 数据完整性测试——文件校验/并发写入/备份导出。"""
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def bench_app(tmp_path):
    """带真实文件的测试 app（data/ + config/）。"""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    config_dir.mkdir()
    # 写入正常 trades.csv
    trades_file = data_dir / "trades.csv"
    with open(trades_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "instrument_id", "action", "quantity", "price", "fee", "note"])
        w.writerow(["2026-11-01", "consumer50_etf", "buy", "1000", "0.50", "", ""])
        w.writerow(["2026-11-01", "consumer50_etf", "buy", "10000", "0.50", "", ""])

    # 写入 portfolio.local.yaml
    (config_dir / "portfolio.local.yaml").write_text("instruments: []\n")

    # S11：权威账本在库内（CSV 仅为导入源/导出格式）——同步种入默认会员
    from invest.data.local import LocalStore

    LocalStore(data_dir / "invest.db").append_trades(
        1,
        [
            {"date": "2026-11-01", "instrument_id": "consumer50_etf", "action": "buy", "quantity": 1000, "price": 0.50},
            {"date": "2026-11-01", "instrument_id": "consumer50_etf", "action": "buy", "quantity": 10000, "price": 0.50},
        ],
    )

    app = FastAPI()
    app.state.data_dir = str(data_dir)
    from invest.webapp.routes_backup import router
    app.include_router(router, prefix="/api/invest")
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, data_dir, config_dir, trades_file


class TestLoadTradesRobustness:
    def test_normal_csv(self, tmp_path):
        from invest.ledger.trades import load_trades
        p = tmp_path / "trades.csv"
        p.write_text("date,instrument_id,action,quantity,price,fee,note\n2026-11-01,test,buy,100,1.0,,\n")
        trades = load_trades(p)
        assert len(trades) == 1
        assert trades[0].instrument_id == "test"

    def test_corrupted_row_skipped(self, tmp_path):
        from invest.ledger.trades import load_trades
        p = tmp_path / "trades.csv"
        p.write_text(
            "date,instrument_id,action,quantity,price,fee,note\n"
            "2026-11-01,test,buy,100,1.0,,\n"
            "2026-11-01,test,buy,NOT_A_NUMBER,1.0,,\n"
            "2026-11-02,test,sell,50,1.2,,\n"
        )
        trades = load_trades(p)
        assert len(trades) == 2  # 损坏行跳过，正常行返回

    def test_missing_columns_row(self, tmp_path):
        from invest.ledger.trades import load_trades
        p = tmp_path / "trades.csv"
        p.write_text(
            "date,instrument_id,action,quantity,price,fee,note\n"
            "2026-11-01,test,buy,100,1.0,,\n"
            ",,,,,,\n"
        )
        trades = load_trades(p)
        assert len(trades) >= 1  # 空行不崩溃

    def test_empty_file(self, tmp_path):
        from invest.ledger.trades import load_trades
        p = tmp_path / "trades.csv"
        p.write_text("date,instrument_id,action,quantity,price,fee,note\n")
        trades = load_trades(p)
        assert len(trades) == 0

    def test_nonexistent_file(self, tmp_path):
        from invest.ledger.trades import load_trades
        trades = load_trades(tmp_path / "nonexistent.csv")
        assert trades == []


class TestBackupAPI:
    def test_backup_export(self, bench_app):
        app, client, data_dir, config_dir, trades_file = bench_app
        resp = client.get("/api/invest/backup/export")
        assert resp.status_code == 200
        assert "application/zip" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_backup_info(self, bench_app):
        app, client, data_dir, config_dir, trades_file = bench_app
        resp = client.get("/api/invest/backup/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades_count"] == 2
        assert data["exportable"] is True

    def test_data_health_report(self, bench_app):
        app, client, data_dir, config_dir, trades_file = bench_app
        resp = client.get("/api/invest/health/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True
        # S11：权威行数来自库（CSV 时代已退役为导出格式）
        assert data["files"]["trades"]["valid_rows"] == 2
        assert data["files"]["trades"]["corrupted_rows"] == 0

    def test_data_health_store_immune_to_csv_junk(self, bench_app):
        """S11 语义：库内权威行数不受 data 目录杂散 CSV 影响（写入即校验）。"""
        app, client, data_dir, config_dir, trades_file = bench_app
        with open(trades_file, "a", newline="") as f:
            f.write("2026-11-01,test,buy,BROKEN,1.0,,\n")
        resp = client.get("/api/invest/health/data")
        data = resp.json()
        assert data["files"]["trades"]["valid_rows"] == 2
        assert data["healthy"] is True


class TestSellValidation:
    def test_sell_exceeds_holding_rejected(self, bench_app):
        """S04-AC3：卖出不超持仓——由 validate_trade 在 routes 层校验（集成测试）。"""
        from invest.ledger.trades import validate_trade, Trade
        from invest.config import Instrument
        from types import SimpleNamespace as NS
        conf = NS(instruments=[Instrument(id="consumer50_etf", type="etf", name="消费50", code="159928")])
        existing = [
            Trade(date="2026-11-01", instrument_id="consumer50_etf", action="buy", quantity=1000, price=0.5, fee=0, note=""),
        ]
        trade, err = validate_trade(
            {"date": "2026-11-01", "instrument_id": "consumer50_etf", "action": "sell", "quantity": 1500, "price": 0.5},
            conf,
            existing,
        )
        assert trade is None
        assert err is not None
        assert "超过持仓" in err or "持仓" in err
