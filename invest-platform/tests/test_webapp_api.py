"""webapp API：流水增删往返、校验拒绝、状态读取（全部 tmp 目录，不碰真实数据）。"""
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.webapp import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


BUY = {
    "instrument_id": "csi_dividend_pension",
    "action": "buy",
    "date": "2026-01-05",
    "quantity": 1000,
    "price": 1.0,
    "fee": 0,
    "note": "test",
}


def test_trades_add_state_delete_roundtrip(client):
    r = client.post("/api/trades", json=BUY)
    assert r.status_code == 200
    state = r.json()["state"]
    assert state["trades"][-1]["quantity"] == 1000
    ins = next(i for i in state["instruments"] if i["id"] == "csi_dividend_pension")
    assert ins["quantity"] == 1000
    assert ins["year_contribution"] == 0.0  # buy不占缴存额度

    # 缴存(contribute)单独跟踪年度进度
    r = client.post("/api/trades", json={**BUY, "action": "contribute", "quantity": 5000, "price": 1})
    assert r.status_code == 200
    ins = next(i for i in r.json()["state"]["instruments"] if i["id"] == "csi_dividend_pension")
    assert ins["year_contribution"] == 5000.0 and ins["contribution_entered"] is True
    client.post("/api/trades/delete", json={"row": {
        "date": "2026-01-05", "instrument_id": "csi_dividend_pension", "action": "contribute",
        "quantity": "5000.00", "price": "1.0000", "fee": "", "note": "test",
    }})

    assert len(client.get("/api/state").json()["trades"]) == 1

    # 超卖拒绝（422，且不落盘）
    r = client.post("/api/trades", json={**BUY, "action": "sell", "quantity": 9999})
    assert r.status_code == 422
    assert "赎回超过持仓" in r.json()["error"]
    assert len(client.get("/api/state").json()["trades"]) == 1

    # 删除
    row = {
        "date": "2026-01-05", "instrument_id": "csi_dividend_pension", "action": "buy",
        "quantity": "1000.00", "price": "1.0000", "fee": "", "note": "test",
    }
    r = client.post("/api/trades/delete", json={"row": row})
    assert r.status_code == 200
    assert client.get("/api/state").json()["trades"] == []

    # 再删 → 409
    r = client.post("/api/trades/delete", json={"row": row})
    assert r.status_code == 409


def test_trades_add_rejects_unknown_instrument(client):
    r = client.post("/api/trades", json={**BUY, "instrument_id": "nope"})
    assert r.status_code == 422
    assert r.json()["error"] == "未知标的"


def test_trades_add_rejects_bad_date(client):
    r = client.post("/api/trades", json={**BUY, "date": "2026/01/05"})
    assert r.status_code == 422
    assert "日期格式" in r.json()["error"]


def test_signals_evaluate_and_status_flow(client, tmp_path):
    from invest.data.local import LocalStore

    r = client.post("/api/signals/evaluate")
    assert r.status_code == 200 and r.json()["ok"] is True
    store = LocalStore(tmp_path / "invest.db")
    rows = store.recent_signals(limit=5)
    assert rows, "评估应至少产生养老金缴存信号"
    sid = rows[0][0]
    r = client.post(f"/api/signals/{sid}/status", json={"status": "已确认"})
    assert r.status_code == 200 and r.json()["status"] == "已确认"
    r = client.post(f"/api/signals/{sid}/status", json={"status": "乱来"})
    assert r.status_code == 422
    r = client.post("/api/signals/99999/status", json={"status": "已忽略"})
    assert r.status_code == 404
    # 信号页渲染
    page = client.get("/signals")
    assert page.status_code == 200 and "立即评估" in page.text


def test_reports_generate_and_view(client, tmp_path):
    r = client.post("/api/reports/generate", json={"ai": False})
    assert r.status_code == 200
    fname = r.json()["file"]
    assert fname.startswith("weekly-") and fname.endswith(".md")
    page = client.get(f"/reports/view/{fname}")
    assert page.status_code == 200 and "投资周报" in page.text
    # 列表页
    lst = client.get("/reports")
    assert lst.status_code == 200 and fname in lst.text
    # 路径穿越与非法名拒绝
    assert client.get("/reports/view/evil.md").status_code == 404
    assert client.get("/reports/view/weekly-x.md").status_code == 404


def test_settings_page_and_pull_job(client, monkeypatch):
    import time as _time

    page = client.get("/settings")
    assert page.status_code == 200
    assert "策略参数" in page.text and "手动拉数" in page.text

    # 拉数后台任务：monkeypatch 管线避免真实网络
    import invest.pipeline as pipeline

    def fake_run_pull(conf, store, provider, log=print, start="2015-01-01"):
        log("[OK] 模拟拉数完成")

    monkeypatch.setattr(pipeline, "run_pull", fake_run_pull)
    r = client.post("/api/pull")
    assert r.status_code == 200
    for _ in range(50):
        s = client.get("/api/pull/status").json()
        if s["status"] != "running":
            break
        _time.sleep(0.1)
    assert s["status"] == "done"
    assert any("模拟拉数完成" in line for line in s["log"])


def test_backtest_api_with_seeded_data(client, tmp_path):
    import pandas as pd
    from invest.data.local import LocalStore

    store = LocalStore(tmp_path / "invest.db")
    months = pd.date_range("2023-01-01", periods=15, freq="MS").strftime("%Y-%m-%d")
    tr = pd.DataFrame({"date": months, "close": [100 * (1.01 ** i) for i in range(15)]})
    px = pd.DataFrame({"date": months, "close": [98 * (1.008 ** i) for i in range(15)]})
    store.upsert_series("H00922", "tr_close", tr, source="t")
    store.upsert_series("999999", "index_close", px, source="t")
    store.upsert_series("999999", "pe_ttm_hist", pd.DataFrame({"date": months, "close": [9.0] * 15}), source="t")
    store.upsert_series("CN10Y", "bond_yield", pd.DataFrame({"date": months, "close": [3.0] * 15}), source="t")
    store.upsert_catalog(pd.DataFrame([{"index_code": "999999", "name": "中证红利", "full_name": "中证红利指数"}]))

    r = client.post("/api/backtest", json={"start": "2023-01-01", "monthly": 1000, "codes": ["dca", "div_spread"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] and len(data["results"]) == 2
    dca = next(x for x in data["results"] if x["code"] == "dca")
    assert dca["metrics"]["投入笔数"] == 15
    assert len(dca["curve"]) > 10  # 曲线点已给前端

    # 未拉数时友好报错
    r2 = client.post("/api/backtest", json={"start": "2013-01-01"})
    assert r2.status_code in (200, 422)
