"""S11 会员数据隔离（AC-4/5/6）：双会员 star 模式越权回归。

铸两个会员的 star JWT（member 31=运营者/admin，member 99=普通会员），
验证：流水/总览/日记/标的/信号互不可见、按 id 越权删除等价 409、
旧版整行删除兼容、写操作落审计、admin 端点守卫。
"""
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.webapp import create_app

SECRET = "s11-isolation-secret-key-32-bytes-min!"
ADMIN = 31
MEMBER = 99
BUY = {"instrument_id": "csi_dividend_pension", "action": "buy",
       "date": "2026-01-05", "quantity": 1000, "price": 1.0, "fee": 0, "note": ""}


def _token(member_id: int) -> str:
    return pyjwt.encode({"sub": str(member_id), "username": f"m{member_id}"}, SECRET, algorithm="HS256")


@pytest.fixture()
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("INVEST_JWT_SECRET", SECRET)
    monkeypatch.setenv("INVEST_ADMIN_MEMBER_IDS", str(ADMIN))
    monkeypatch.delenv("INVEST_DEFAULT_MEMBER_ID", raising=False)
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
        auth_mode="star",
    )
    c = TestClient(app)
    return c, {"admin": {"Authorization": f"Bearer {_token(ADMIN)}"},
               "member": {"Authorization": f"Bearer {_token(MEMBER)}"}}


def _seed_nav(c, headers):
    """给标的种净值序列，使市值可算（隔离断言需非零数据）。

    example 配置 code 为空，序列键回退 instrument id；kind 用 fund_nav
    （与 test_mp_api._seed_nav 同口径）。行情序列是全会员共享缓存，
    直接落库即可，无需经 API。
    """
    import pandas as pd

    from invest.data.local import LocalStore

    store = LocalStore(c.app.state.data_dir / "invest.db")
    store.upsert_series("csi_dividend_pension", "fund_nav",
                        pd.DataFrame({"date": ["2026-10-16"], "close": [1.5]}), source="test")


class TestTradeIsolation:
    def test_member_cannot_see_others_trades(self, clients):
        c, h = clients
        _seed_nav(c, h["admin"])
        assert c.post("/api/invest/trades", json=BUY, headers=h["admin"]).status_code == 200

        admin_rows = c.get("/api/invest/trades", headers=h["admin"]).json()["trades"]
        member_rows = c.get("/api/invest/trades", headers=h["member"]).json()["trades"]
        assert len(admin_rows) == 1 and admin_rows[0]["instrument_id"] == BUY["instrument_id"]
        assert member_rows == []  # 会员看不到运营者的流水

    def test_overview_totals_isolated(self, clients):
        c, h = clients
        _seed_nav(c, h["admin"])
        c.post("/api/invest/trades", json=BUY, headers=h["admin"])

        admin_mv = c.get("/api/invest/overview", headers=h["admin"]).json()["totals"]["market_value"]
        member_mv = c.get("/api/invest/overview", headers=h["member"]).json()["totals"]["market_value"]
        assert admin_mv is not None and admin_mv > 0
        assert member_mv in (None, 0)  # 会员总览不含运营者持仓

    def test_delete_by_id_scoped(self, clients):
        """越权删除他人 id：等价不存在 → 409（store 层 WHERE member_id 拒绝）。"""
        c, h = clients
        r = c.post("/api/invest/trades", json=BUY, headers=h["admin"])
        trade_id = c.get("/api/invest/trades", headers=h["admin"]).json()["trades"][0]["id"]

        steal = c.post("/api/invest/trades/delete", json={"id": trade_id}, headers=h["member"])
        assert steal.status_code == 409
        assert len(c.get("/api/invest/trades", headers=h["admin"]).json()["trades"]) == 1  # 原行仍在

        own = c.post("/api/invest/trades/delete", json={"id": trade_id}, headers=h["admin"])
        assert own.status_code == 200

    def test_delete_by_row_legacy_still_works(self, clients):
        """旧客户端整行删除兼容（无 id 字段，数值容差同口径）。"""
        c, h = clients
        c.post("/api/invest/trades", json=BUY, headers=h["member"])
        row = c.get("/api/invest/trades", headers=h["member"]).json()["trades"][0]
        row.pop("id")
        row.pop("action_label", None)
        assert c.post("/api/invest/trades/delete", json={"row": row}, headers=h["member"]).status_code == 200
        assert c.get("/api/invest/trades", headers=h["member"]).json()["trades"] == []


class TestDiaryInstrumentIsolation:
    def test_diary_same_date_different_members(self, clients):
        c, h = clients
        for who, text in ((h["admin"], "运营者日记"), (h["member"], "会员日记")):
            r = c.post("/api/invest/diary", json={"date": "2026-11-08", "content": text, "mood": "平静"}, headers=who)
            assert r.status_code == 200
        assert c.get("/api/invest/diary", headers=h["admin"]).json()["entries"][0]["content"] == "运营者日记"
        assert c.get("/api/invest/diary", headers=h["member"]).json()["entries"][0]["content"] == "会员日记"

    def test_instrument_visible_only_to_owner(self, clients):
        c, h = clients
        payload = {"id": "member_fund", "type": "wealth", "name": "会员理财"}
        assert c.post("/api/invest/instruments", json=payload, headers=h["member"]).status_code == 200
        member_ids = [i["id"] for i in c.get("/api/invest/instruments", headers=h["member"]).json()["instruments"]]
        admin_ids = [i["id"] for i in c.get("/api/invest/instruments", headers=h["admin"]).json()["instruments"]]
        assert "member_fund" in member_ids
        assert "member_fund" not in admin_ids  # db 标的按会员隔离（yaml 种子共享）


class TestAuditAndAdmin:
    def test_write_ops_audited(self, clients):
        c, h = clients
        c.post("/api/invest/trades", json=BUY, headers=h["member"])
        rows = c.get("/api/invest/admin/audit", headers=h["admin"]).json()["audit"]
        assert any(r["member_id"] == MEMBER and r["action"] == "trade.add" for r in rows)

    def test_admin_endpoint_forbidden_to_member(self, clients):
        c, h = clients
        assert c.get("/api/invest/admin/audit", headers=h["member"]).status_code == 403
        assert c.get("/api/invest/admin/members", headers=h["member"]).status_code == 403
        assert c.get("/api/invest/admin/members", headers=h["admin"]).status_code == 200

    def test_audit_detail_has_no_amounts(self, clients):
        """章程级约束：审计不含金额明文（who/what/when/traceId 足矣）。"""
        c, h = clients
        c.post("/api/invest/trades", json=BUY, headers=h["member"])
        rows = c.get("/api/invest/admin/audit", headers=h["admin"]).json()["audit"]
        add_rows = [r for r in rows if r["action"] == "trade.add"]
        assert add_rows and "1000" not in add_rows[0]["detail"]
