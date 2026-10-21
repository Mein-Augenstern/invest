"""R5 投资日记：upsert/删除/列表/单条。"""
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.data.local import LocalStore
from invest.webapp import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


def test_diary_crud_roundtrip(client, tmp_path):
    store = LocalStore(tmp_path / "invest.db")
    assert client.get("/api/invest/diary").json()["entries"] == []
    # 写
    r = client.post("/api/invest/diary", json={"date": "2026-10-18", "content": "红利高位，忍住没加仓", "mood": "坚定"})
    assert r.status_code == 200
    # 同日重写 = 覆盖
    client.post("/api/invest/diary", json={"date": "2026-10-18", "content": "改主意，小幅加仓", "mood": "犹豫"})
    entries = client.get("/api/invest/diary").json()["entries"]
    assert len(entries) == 1 and entries[0]["content"] == "改主意，小幅加仓"
    # 单条回填
    one = client.get("/api/invest/diary", params={"date": "2026-10-18"}).json()["diary"]
    assert one["mood"] == "犹豫"
    # 删除
    assert client.post("/api/invest/diary/delete", json={"date": "2026-10-18"}).status_code == 200
    assert client.post("/api/invest/diary/delete", json={"date": "2026-10-18"}).status_code == 404


def test_diary_validation(client):
    assert client.post("/api/invest/diary", json={"date": "2026/10/18", "content": "x"}).status_code == 422
    assert client.post("/api/invest/diary", json={"date": "2026-10-18", "content": "  "}).status_code == 422
    assert client.post("/api/invest/diary", json={"date": "2026-10-18", "content": "x", "mood": "兴奋"}).status_code == 422
