"""S02 API 端点测试——策略引擎生命周期（纸面交易+信号确认/忽略/过期）。"""
import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_store(tmp_path):
    """创建带 SQLite store 的测试 app。"""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    store = MagicMock()
    store.conn = conn
    app = FastAPI()
    app.state.store = store
    from invest.strategy.api_routes import signal_router
    app.include_router(signal_router, prefix="/api/invest")
    return app, TestClient(app), conn


class TestSignalList:
    def test_empty_signals(self, app_with_store):
        app, client, conn = app_with_store
        resp = client.get("/api/invest/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "signals" in data
        assert "paper_trades" in data

    def test_with_status_filter(self, app_with_store):
        app, client, conn = app_with_store
        resp = client.get("/api/invest/signals?status=generated")
        assert resp.status_code == 200


class TestSignalConfirm:
    def test_confirm_nonexistent(self, app_with_store):
        app, client, conn = app_with_store
        resp = client.post("/api/invest/signals/nonexistent/confirm")
        assert resp.status_code == 409

    def test_confirm_then_paper_trade(self, app_with_store):
        app, client, conn = app_with_store
        conn.execute(
            "INSERT INTO signals (id,instrument_id,final_signal,confidence,summary,status,created_at,results_json) VALUES (?,?,?,?,?,?,?,?)",
            ("sig_test", "consumer50_etf", "buy", 0.85, "PE低估", "generated",
             datetime.now().isoformat(), json.dumps([{"metric_value": 0.52}])))
        conn.commit()

        resp = client.post("/api/invest/signals/sig_test/confirm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmed"] is True
        assert "paper_trade" in data
        assert data["paper_trade"]["status"] == "open"


class TestSignalIgnore:
    def test_ignore(self, app_with_store):
        app, client, conn = app_with_store
        conn.execute(
            "INSERT INTO signals (id,instrument_id,final_signal,confidence,summary,status,created_at,results_json) VALUES (?,?,?,?,?,?,?,?)",
            ("sig_ign", "consumer50_etf", "hold", 0.5, "维持", "generated",
             datetime.now().isoformat(), "[]"))
        conn.commit()

        resp = client.post("/api/invest/signals/sig_ign/ignore")
        assert resp.status_code == 200
        assert resp.json()["ignored"] is True


class TestSignalHistory:
    def test_history_with_stats(self, app_with_store):
        app, client, conn = app_with_store
        resp = client.get("/api/invest/signals/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "total" in data["stats"]
        assert "confirmed" in data["stats"]
        assert "ignored" in data["stats"]


class TestSignalExpiry:
    def test_stale_signal_expires(self, app_with_store):
        app, client, conn = app_with_store
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute(
            "INSERT INTO signals (id,instrument_id,final_signal,confidence,summary,status,created_at,results_json) VALUES (?,?,?,?,?,?,?,?)",
            ("sig_old", "consumer50_etf", "buy", 0.9, "旧信号", "generated", old_date, "[]"))
        conn.commit()

        resp = client.get("/api/invest/signals")
        assert resp.status_code == 200

        resp2 = client.get("/api/invest/signals?status=generated")
        ids = [s["id"] for s in resp2.json()["signals"]]
        assert "sig_old" not in ids
