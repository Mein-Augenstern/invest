"""webapp 冒烟：工厂可建、页面/静态资源可达、Host 白名单与缓存头生效。"""
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.webapp import create_app


@pytest.fixture()
def client(tmp_path):
    # 注入 example 配置 + tmp 数据目录：测试不触碰真实持仓数据
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


def test_shell_pages_render(client):
    for path, marker in [
        ("/", "总览"),
        ("/positions", "持仓"),
        ("/trades", "流水"),
        ("/signals", "信号"),
        ("/reports", "报告"),
        ("/settings", "设置"),
    ]:
        resp = client.get(path, headers={"Host": "testserver"})
        assert resp.status_code == 200, path
        assert marker in resp.text
        assert resp.headers["cache-control"] == "no-store"


def test_index_renders_sections_and_empty_state(client):
    resp = client.get("/")
    assert "持仓明细" in resp.text
    assert "基准指数估值" in resp.text
    assert "策略信号" in resp.text
    assert "组合市值" in resp.text


def test_trades_page_has_form_and_state(client):
    resp = client.get("/trades")
    assert "新增流水" in resp.text
    assert "STATE0" in resp.text  # 服务端注入初始状态
    assert "csi_dividend_pension" in resp.text


def test_static_vendor_served_with_immutable(client):
    resp = client.get("/static/vendor/tabler/tabler.min.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=604800, immutable"


def test_static_no_cache(client):
    resp = client.get("/static/css/app.css")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


def test_host_whitelist_blocks_unknown_host(client):
    resp = client.get("/", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403


def test_ping_api(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200 and resp.json()["ok"] is True


def test_strategy_page_renders_cards(client):
    resp = client.get("/strategy")
    assert resp.status_code == 200
    assert "从零读懂你的策略" in resp.text
    assert "配置与纪律" in resp.text  # 养老金策略卡
    assert "估值分位定投" in resp.text  # ETF策略卡
    assert "缴满" in resp.text


def test_position_detail_pages(client):
    r = client.get("/positions/csi_dividend_pension")
    assert r.status_code == 200
    assert "中证红利基金" in r.text  # 示例配置的标的名单独成页
    r = client.get("/positions/consumer50_etf")
    assert r.status_code == 200 and "消费50ETF" in r.text
    assert client.get("/positions/nope").status_code == 404
    # 枢纽页有详情入口
    hub = client.get("/positions")
    assert "详情 →" in hub.text and "/positions/csi_dividend_pension" in hub.text


def test_glossary_page_renders_entries(client, tmp_path):
    (tmp_path / "glossary").mkdir()
    (tmp_path / "glossary" / "xirr.md").write_text(
        "# XIRR测试概念\n\n> 记录于 2026-09-06\n\n**一句话**：年化收益率，考虑每笔钱的投入时长。", encoding="utf-8"
    )
    resp = client.get("/glossary")
    assert resp.status_code == 200
    assert "XIRR测试概念" in resp.text
    assert "<strong>一句话</strong>" in resp.text  # markdown 已渲染
    assert "搜索概念" in resp.text
