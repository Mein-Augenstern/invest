"""S10 配套修复回归：GLM key 路径可覆盖 + 启动加载；周报 store 随部署环境。

- glm_key_file 默认沿用本机布局 <data>/../config/glm.local.env（兼容既有测试断言）；
  INVEST_GLM_KEY_FILE 覆盖（容器 config 只读挂载 → 写数据卷）。
- load_glm_key_from_file：启动时把 key 文件载入 env；显式 env 优先不覆盖。
- reportjob 周报在 MySQL 部署下曾硬编码 LocalStore 读错库——本测试通过
  monkeypatch default_store 证明 _run 走 default_store 工厂（与 pulljob 同款修复）。
"""
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from invest.webapp import create_app
from invest.webapp.deps import glm_key_file, load_glm_key_from_file

CONFIG = Path(__file__).resolve().parent.parent / "config" / "portfolio.example.yaml"


def _client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=CONFIG,
        data_dir=tmp_path / "data",
        mp_token="t",
    )
    return tmp_path, TestClient(app)


def test_glm_key_default_path_unchanged(tmp_path):
    """缺省仍写 <data_dir>/../config/glm.local.env（本机布局，兼容既有行为）。"""
    data_dir = tmp_path / "data"
    assert glm_key_file(data_dir) == tmp_path / "config" / "glm.local.env"


def test_glm_key_env_override_roundtrip(tmp_path, monkeypatch):
    """容器部署：INVEST_GLM_KEY_FILE 指到可写数据卷，读写均落该文件。"""
    key_file = tmp_path / "glm.env"
    monkeypatch.setenv("INVEST_GLM_KEY_FILE", str(key_file))
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    base, client = _client(tmp_path)
    auth = {"Authorization": "Bearer t"}

    assert client.get("/api/invest/settings/glm-key", headers=auth).json() == {"configured": False}
    r = client.post(
        "/api/invest/settings/glm-key",
        json={"key": "k-override-1"},
        headers=auth,
    )
    assert r.status_code == 200 and r.json()["configured"] is True
    assert key_file.exists() and "k-override-1" in key_file.read_text(encoding="utf-8")
    assert os.environ["INVEST_GLM_API_KEY"] == "k-override-1"  # 即时生效

    client.post("/api/invest/settings/glm-key", json={"key": ""}, headers=auth)
    assert client.get("/api/invest/settings/glm-key", headers=auth).json() == {"configured": False}
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)


def test_glm_key_loaded_from_file_at_startup(tmp_path, monkeypatch):
    """容器重启场景：env 无 key 但持久化文件在 → 启动加载；显式 env 优先。"""
    key_file = tmp_path / "glm.env"
    key_file.write_text("INVEST_GLM_API_KEY=k-from-file\n", encoding="utf-8")

    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    load_glm_key_from_file(tmp_path / "data" / "x")  # 路径任意：INVEST_GLM_KEY_FILE 决定
    monkeypatch.setenv("INVEST_GLM_KEY_FILE", str(key_file))
    load_glm_key_from_file(tmp_path)
    assert os.environ["INVEST_GLM_API_KEY"] == "k-from-file"

    monkeypatch.setenv("INVEST_GLM_API_KEY", "k-explicit")
    load_glm_key_from_file(tmp_path)
    assert os.environ["INVEST_GLM_API_KEY"] == "k-explicit"  # 不覆盖
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)


def test_reportjob_uses_default_store_factory(tmp_path, monkeypatch):
    """周报后台任务经 default_store 构造 store（MySQL 部署读对库的回归锚点）。"""
    import invest.data.mysql_store as ms
    from invest.data.local import LocalStore
    from invest.webapp import reportjob

    calls: list[str] = []

    def spy_default_store(data_dir):
        calls.append(str(data_dir))
        return LocalStore(Path(data_dir) / "invest.db")

    monkeypatch.setattr(ms, "default_store", spy_default_store)
    monkeypatch.delenv("INVEST_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ok, err = reportjob.start_report(data_dir, CONFIG, with_ai=False)
    assert ok, err
    for _ in range(100):  # 后台线程完成或出错（空数据下也可能 error，均证明走了工厂）
        st = reportjob.status()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert calls, "reportjob._run 必须经 default_store 工厂构造 store"


def test_host_check_suffix_entry(tmp_path):
    """Host 白名单 `*.suffix` 条目：隧道随机子域放行，裸域/伪造后缀仍 403。"""
    app = create_app(
        allowed_hosts={"127.0.0.1", "*.trycloudflare.com"},
        config_path=CONFIG,
        data_dir=tmp_path,
        mp_token="t",
    )
    c = TestClient(app)
    assert c.get("/api/invest/ping", headers={"Host": "random-words-42.trycloudflare.com"}).status_code == 200
    assert c.get("/api/invest/ping", headers={"Host": "evil.example.org"}).status_code == 403
    assert c.get("/api/invest/ping", headers={"Host": "trycloudflare.com"}).status_code == 403  # 仅子域
    assert (
        c.get("/api/invest/ping", headers={"Host": "x-trycloudflare.com.attacker.org"}).status_code == 403
    )  # 后缀必须是完整标签


def test_cors_single_origin_opt_in(tmp_path, monkeypatch):
    """S10 过渡形态：INVEST_ALLOWED_ORIGINS 精确放行单一 origin（预检 + 实际响应带头）。"""
    monkeypatch.setenv("INVEST_ALLOWED_ORIGINS", "https://invest-demo.pages.dev")
    app = create_app(allowed_hosts={"testserver"}, config_path=CONFIG, data_dir=tmp_path, mp_token="t")
    c = TestClient(app)

    pre = c.options(
        "/api/invest/ping",
        headers={"Origin": "https://invest-demo.pages.dev", "Access-Control-Request-Method": "GET"},
    )
    assert pre.status_code == 200
    assert pre.headers.get("access-control-allow-origin") == "https://invest-demo.pages.dev"

    r = c.get("/api/invest/ping", headers={"Origin": "https://invest-demo.pages.dev"})
    assert r.headers.get("access-control-allow-origin") == "https://invest-demo.pages.dev"
    # 未登记 origin 不放行（浏览器侧表现为 CORS 拦截）
    r2 = c.get("/api/invest/ping", headers={"Origin": "https://evil.example.org"})
    assert r2.headers.get("access-control-allow-origin") != "https://evil.example.org"


def test_cors_off_by_default(tmp_path, monkeypatch):
    """未配置 env 时无 CORS 头——维持"无 CORS 即防御"的同源形态。"""
    monkeypatch.delenv("INVEST_ALLOWED_ORIGINS", raising=False)
    app = create_app(allowed_hosts={"testserver"}, config_path=CONFIG, data_dir=tmp_path, mp_token="t")
    r = TestClient(app).get("/api/invest/ping", headers={"Origin": "https://any.pages.dev"})
    assert "access-control-allow-origin" not in r.headers
