"""S2 标的管理：db/yaml 合并、CRUD 校验、删除保护、GLM Key 持久化。"""
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.data.local import LocalStore
from invest.portfolio import load_portfolio
from invest.webapp import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


def test_instrument_crud_and_merge(client, tmp_path):
    # 新增（手机式）
    r = client.post("/api/invest/instruments", json={
        "id": "my_stock", "type": "stock", "name": "测试股票", "code": "600519", "account": "a_stock",
    })
    assert r.status_code == 200
    # 列表：db 标的追加进合并视图
    lst = client.get("/api/invest/instruments").json()["instruments"]
    ids = {i["id"] for i in lst}
    assert "my_stock" in ids and "csi_dividend_pension" in ids  # db 新增 + yaml 种子共存
    mine = next(i for i in lst if i["id"] == "my_stock")
    assert mine["from_db"] is True and mine["type"] == "stock"
    # 合并配置生效（流水页标的元数据可见新标的）
    state = client.get("/api/invest/trades").json()
    assert any(i["id"] == "my_stock" for i in state["instruments"])
    # 编辑（改名）
    client.post("/api/invest/instruments", json={
        "id": "my_stock", "type": "stock", "name": "测试股票2", "code": "600519", "account": "a_stock",
    })
    store = LocalStore(tmp_path / "invest.db")
    conf = load_portfolio(store)
    assert next(i for i in conf.instruments if i.id == "my_stock").name == "测试股票2"
    # 删除（无持仓 → 成功；yaml 种子 → 404）
    assert client.post("/api/invest/instruments/delete", json={"id": "my_stock"}).status_code == 200
    assert client.post("/api/invest/instruments/delete", json={"id": "csi_dividend_pension"}).status_code == 404


def test_instrument_validation(client):
    r = client.post("/api/invest/instruments", json={"id": "Bad ID", "type": "stock", "name": "x"})
    assert r.status_code == 422
    r = client.post("/api/invest/instruments", json={"id": "ok_id", "type": "crypto", "name": "x"})
    assert r.status_code == 422
    r = client.post("/api/invest/instruments", json={"id": "ok_id", "type": "bond", "name": "x", "code": "019547"})
    assert r.status_code == 422  # 债券缺市场前缀


def test_instrument_delete_guard_with_position(client):
    client.post("/api/invest/instruments", json={"id": "my_fund", "type": "wealth", "name": "测试理财"})
    client.post("/api/invest/trades", json={
        "instrument_id": "my_fund", "action": "buy", "date": "2026-01-05",
        "quantity": 1000, "price": 1.0, "fee": 0, "note": "",
    })
    r = client.post("/api/invest/instruments/delete", json={"id": "my_fund"})
    assert r.status_code == 409


def test_glm_key_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    assert client.get("/api/invest/settings/glm-key").json() == {"configured": False}
    r = client.post("/api/invest/settings/glm-key", json={"key": "test-key-123"})
    assert r.status_code == 200 and r.json()["configured"] is True
    import os

    assert os.environ["INVEST_GLM_API_KEY"] == "test-key-123"  # 即时生效
    assert (tmp_path.parent / "config" / "glm.local.env").exists()  # 落 gitignore 文件
    # 清除
    client.post("/api/invest/settings/glm-key", json={"key": ""})
    assert client.get("/api/invest/settings/glm-key").json() == {"configured": False}
