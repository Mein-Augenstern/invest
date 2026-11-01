"""S02 API 端点测试——策略引擎生命周期（纸面交易+信号确认/忽略/过期）。"""
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_store(tmp_path):
    """创建带 SQLite store 的测试 app。"""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    store = SimpleNamespace()
    store.conn = conn
    app = FastAPI()
    app.state.store = store
    from invest.strategy.api_routes import signal_router
    app.include_router(signal_router, prefix="/api/invest")
    client = TestClient(app)
    # warm-up：触发 _get_lifecycle → 建表 + fixture 直接建（双保险）
    from invest.strategy.lifecycle import SignalLifecycleStore
    _ = SignalLifecycleStore(store)
    return app, client, conn


def _insert_signal(conn, sid, signal_type="buy", status="generated", created=None):
    """插入测试信号（9 列对齐 lifecycle DDL，含 confirmed_at=None）。"""
    conn.execute(
        "INSERT INTO signal_records (id,instrument_id,final_signal,confidence,summary,status,created_at,confirmed_at,results_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, "consumer50_etf", signal_type, 0.85, "测试信号", status,
         created or datetime.now().isoformat(), None,
         json.dumps([{"metric_value": 0.52}])))


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
        _insert_signal(conn, "sig_test", "buy")
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
        _insert_signal(conn, "sig_ign", "hold")
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
        _insert_signal(conn, "sig_old", "buy", created=old_date)
        conn.commit()

        resp = client.get("/api/invest/signals")
        assert resp.status_code == 200

        resp2 = client.get("/api/invest/signals?status=generated")
        ids = [s["id"] for s in resp2.json()["signals"]]
        assert "sig_old" not in ids
