"""小程序 API（/api/invest/*）：Token 鉴权、概览分组、流水增删、信号流（全部 tmp 目录）。"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.data.local import LocalStore
from invest.webapp import create_app


def _make_client(tmp_path, token=None):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
        mp_token=token,
    )
    return TestClient(app)


def _seed_nav(tmp_path, key="csi_dividend_pension", kind="fund_nav", date="2026-10-16", close=1.5):
    """example 配置里 code 为空（TODO 占位），序列键回退 instrument id。"""
    store = LocalStore(tmp_path / "invest.db")
    store.upsert_series(key, kind, pd.DataFrame({"date": [date], "close": [close]}), source="test")


BUY = {
    "instrument_id": "csi_dividend_pension",
    "action": "buy",
    "date": "2026-01-05",
    "quantity": 1000,
    "price": 1.0,
    "fee": 0,
    "note": "mp-test",
}


def test_mp_ping_open_without_token(tmp_path):
    c = _make_client(tmp_path, token="s3cret")
    assert c.get("/api/invest/ping").status_code == 200
    assert c.get("/api/ping").status_code == 200


def test_mp_token_gates_everything_else(tmp_path):
    c = _make_client(tmp_path, token="s3cret")
    # 无 token
    assert c.get("/api/invest/overview").status_code == 401
    assert c.get("/api/state").status_code == 401
    assert c.get("/").status_code == 401
    # 错 token
    assert c.get("/api/invest/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # 对 token（Header 与 ?token= 两种形态）
    assert c.get("/api/invest/overview", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/api/invest/overview?token=s3cret").status_code == 200


def test_mp_token_disabled_in_local_mode(tmp_path):
    """本机模式（无 token）不鉴权——保持既有行为。"""
    c = _make_client(tmp_path)
    assert c.get("/api/invest/overview").status_code == 200


def test_mp_overview_groups_and_totals(tmp_path):
    _seed_nav(tmp_path)
    c = _make_client(tmp_path)
    c.post("/api/invest/trades", json=BUY)
    r = c.get("/api/invest/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["totals"]["market_value"] == 1500.0  # 1000份 × 1.5
    assert data["totals"]["unrealized"] == 500.0
    groups = {g["type"]: g for g in data["groups"]}
    assert set(groups) >= {"open_end_fund", "etf", "stock", "bond", "wealth"}  # example 配置五品类齐
    assert groups["open_end_fund"]["positions"][0]["xirr"] is not None
    # 分组顺序：理财 → 债券 → 基金 → ETF → 股票（风险从低到高）
    order = [g["type"] for g in data["groups"]]
    assert order.index("wealth") < order.index("open_end_fund") < order.index("stock")


def test_mp_trades_list_labels_and_roundtrip(tmp_path):
    _seed_nav(tmp_path)
    c = _make_client(tmp_path)
    c.post("/api/invest/trades", json=BUY)
    c.post("/api/invest/trades", json={**BUY, "instrument_id": "sample_stock", "price": 1400})

    r = c.get("/api/invest/trades").json()
    labels = {t["instrument_id"]: t["action_label"] for t in r["trades"]}
    assert labels["csi_dividend_pension"] == "申购"
    assert labels["sample_stock"] == "买入"
    assert any(i["type"] == "stock" for i in r["instruments"])

    # 按标的过滤
    only = c.get("/api/invest/trades", params={"instrument_id": "sample_stock"}).json()["trades"]
    assert len(only) == 1

    # 删除（row 形态与 Web API 一致；note 保留原值参与匹配）
    row = dict(r["trades"][0])
    row.update(quantity=f"{row['quantity']:.2f}", price=f"{row['price']:.4f}", fee="")
    assert c.post("/api/invest/trades/delete", json={"row": row}).status_code == 200
    assert len(c.get("/api/invest/trades").json()["trades"]) == 1


def test_mp_trades_rejects_unknown_instrument(tmp_path):
    c = _make_client(tmp_path)
    r = c.post("/api/invest/trades", json={**BUY, "instrument_id": "nope"})
    assert r.status_code == 422


def test_mp_signals_flow(tmp_path):
    c = _make_client(tmp_path)
    c.post("/api/signals/evaluate")
    r = c.get("/api/invest/signals").json()
    assert isinstance(r["signals"], list)
    if r["signals"]:
        sid = r["signals"][0]["id"]
        assert c.post(f"/api/invest/signals/{sid}/status", json={"status": "已忽略"}).json()["ok"]


def test_mp_pull_status_shape(tmp_path):
    c = _make_client(tmp_path)
    assert "status" in c.get("/api/invest/pull/status").json()


def test_mp_instrument_detail(tmp_path):
    _seed_nav(tmp_path)
    c = _make_client(tmp_path)
    c.post("/api/invest/trades", json=BUY)
    r = c.get("/api/invest/instrument/csi_dividend_pension")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] and data["row"]["market_value"] == 1500.0
    assert data["nav_series"] and len(data["nav_series"][0]) == 2  # [ts, value]
    assert data["events"] and data["events"][0]["kind"] == "buy"
    assert data["account_name"]
    # 不存在的标的 404
    assert c.get("/api/invest/instrument/nope").status_code == 404


def test_mp_nav_roundtrip(tmp_path):
    """小程序录理财净值：幂等 upsert，校验拒绝坏值。"""
    _seed_nav(tmp_path, key="bank_wealth_1", kind="manual_nav", close=1.0)
    c = _make_client(tmp_path)
    r = c.post("/api/invest/nav", json={"instrument_id": "bank_wealth_1", "date": "2026-10-18", "value": 1.0234})
    assert r.status_code == 200 and r.json()["ok"] is True
    # 同日重录覆盖（幂等）：序列只有 2 条（种子 1 条 + 新 1 条）
    c.post("/api/invest/nav", json={"instrument_id": "bank_wealth_1", "date": "2026-10-18", "value": 1.0300})
    detail = c.get("/api/invest/instrument/bank_wealth_1").json()
    vals = [p[1] for p in detail["nav_series"]]
    assert len(vals) == 2 and 1.03 in vals
    # 校验
    assert c.post("/api/invest/nav", json={"instrument_id": "nope", "value": 1}).status_code == 404
    assert c.post("/api/invest/nav", json={"instrument_id": "bank_wealth_1", "value": "abc"}).status_code == 422
    assert c.post("/api/invest/nav", json={"instrument_id": "bank_wealth_1", "value": -1}).status_code == 422
    assert c.post("/api/invest/nav", json={"instrument_id": "bank_wealth_1", "date": "2026/10/18", "value": 1}).status_code == 422


def test_mp_report_latest(tmp_path):
    c = _make_client(tmp_path)
    # 无周报 → null
    assert c.get("/api/invest/report/latest").json() == {"report": None}
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "weekly-20261017-180000.md").write_text("# 周报\n内容", encoding="utf-8")
    data = c.get("/api/invest/report/latest").json()
    assert data["file"] == "weekly-20261017-180000.md"
    assert "周报" in data["markdown"]


def test_mp_report_latest_picks_by_mtime_not_lexical(tmp_path):
    """回归：CLI 命名 weekly-YYYYMMDD.md 字典序 > 任务命名 weekly-YYYYMMDD-HHMMSS.md，
    按 mtime 取最新才正确（P12 修复）。"""
    import os
    import time as _time

    c = _make_client(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    old = reports / "weekly-20261018.md"          # CLI 版：字典序反而大
    new = reports / "weekly-20261018-110419.md"   # 任务版：真正更新
    old.write_text("# 旧", encoding="utf-8")
    new.write_text("# 新", encoding="utf-8")
    _time.sleep(0.02)
    os.utime(old, (1, 1))  # 旧文件 mtime 压到最早
    assert c.get("/api/invest/report/latest").json()["file"] == new.name


def test_mp_overview_pension_progress(tmp_path):
    """缴存进度卡数据：contribute 动作按自然年累计，cap 来自策略配置。"""
    _seed_nav(tmp_path)
    c = _make_client(tmp_path)
    c.post("/api/invest/trades", json={**BUY, "action": "contribute", "quantity": 5000, "price": 1})
    data = c.get("/api/invest/overview").json()
    pp = data["pension_progress"]
    assert pp["contributed"] == 5000.0
    assert pp["cap"] == 12000.0
    assert "红利" in pp["name"]


def test_mp_report_generate_job(tmp_path, monkeypatch):
    """后台周报生成：触发→轮询→done 且产物可被 /report/latest 读到。"""
    import invest.reporting as rep

    c = _make_client(tmp_path)
    monkeypatch.setattr(
        rep, "build_weekly_report_md",
        lambda *a, **k: "# 投资周报 fake\n\n- 生成于后台任务",
    )
    r = c.post("/api/invest/reports/generate", json={"ai": False})
    assert r.status_code == 200
    # 轮询至 done（后台线程毫秒级完成）
    import time

    status = {}
    for _ in range(50):
        status = c.get("/api/invest/reports/status").json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert status["status"] == "done", status
    assert status["file"].startswith("weekly-")
    # 产物可见
    latest = c.get("/api/invest/report/latest").json()
    assert "fake" in latest["markdown"]
    # 生成中重复触发 → 409（用慢任务验证）
    import threading

    ev = threading.Event()
    monkeypatch.setattr(rep, "build_weekly_report_md", lambda *a, **k: (ev.wait(3), "# slow")[1])
    assert c.post("/api/invest/reports/generate", json={}).status_code == 200
    for _ in range(50):
        if c.get("/api/invest/reports/status").json()["status"] == "running":
            break
        time.sleep(0.02)
    assert c.post("/api/invest/reports/generate", json={}).status_code == 409
    ev.set()
