"""star 平台鉴权模式（P13）：/api/invest 前缀 + star JWT 纵深防御校验。"""
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.webapp import create_app
from invest.webapp.security import parse_star_member

SECRET = "test-secret-key-at-least-32-bytes-long!"


def _star_client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
        auth_mode="star",
    )
    return TestClient(app)


def _token(member_id=42, secret=SECRET, **extra):
    return pyjwt.encode(
        {"sub": str(member_id), "username": "tester", **extra}, secret, algorithm="HS256"
    )


@pytest.fixture()
def star_secret(monkeypatch):
    monkeypatch.setenv("INVEST_JWT_SECRET", SECRET)


def test_parse_star_member(tmp_path):
    assert parse_star_member(pyjwt, _token(42), SECRET) == 42
    assert parse_star_member(pyjwt, _token(7, secret="wrong-secret"), SECRET) is None
    assert parse_star_member(pyjwt, "not-a-jwt", SECRET) is None
    # 缺 sub / sub 非数字
    bad = pyjwt.encode({"username": "x"}, SECRET, algorithm="HS256")
    assert parse_star_member(pyjwt, bad, SECRET) is None
    # 过期
    import time

    expired = pyjwt.encode(
        {"sub": "1", "exp": int(time.time()) - 10}, SECRET, algorithm="HS256"
    )
    assert parse_star_member(pyjwt, expired, SECRET) is None


def test_star_mode_gates_and_accepts(tmp_path, star_secret):
    c = _star_client(tmp_path)
    ping = c.get("/api/invest/ping")
    assert ping.status_code == 200  # 白名单
    assert c.get("/api/invest/overview").status_code == 401
    assert c.get("/api/invest/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.get("/api/invest/overview", headers={"Authorization": f"Bearer {_token(42)}"})
    assert ok.status_code == 200
    # ?token= 形态同样放行（浏览器调试用）
    ok2 = c.get(f"/api/invest/overview?token={_token(42)}")
    assert ok2.status_code == 200


def test_star_mode_requires_env_secret(tmp_path, monkeypatch):
    """public 仓红线：无内置默认密钥——未配置 INVEST_JWT_SECRET 时 star 模式一律 401。"""
    monkeypatch.delenv("INVEST_JWT_SECRET", raising=False)
    c = _star_client(tmp_path)
    # 任何 token（包括用任意密钥签的）都不放行
    tok = pyjwt.encode({"sub": "9"}, "whatever-secret-value", algorithm="HS256")
    assert c.get("/api/invest/overview", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_token_mode_still_works(tmp_path):
    """静态令牌模式不受 star 模式改造影响（向后兼容）。"""
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
        mp_token="s3cret",
    )
    c = TestClient(app)
    assert c.get("/api/invest/overview").status_code == 401
    assert c.get("/api/invest/overview", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # star JWT 在 token 模式下不放行（两模式互斥）
    assert c.get("/api/invest/overview", headers={"Authorization": f"Bearer {_token(1)}"}).status_code == 401


def test_local_mode_open(tmp_path):
    """本机模式（无任何鉴权配置）保持开放。"""
    c = _make_local(tmp_path)
    assert c.get("/api/invest/overview").status_code == 200


def _make_local(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)
