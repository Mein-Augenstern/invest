"""S05 外部 API 韧性测试——akshare 超时 / 缓存降级 / 多源兜底 / 详情页 stale 标记。"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.data.akshare_provider import FALLBACK_TIMEOUT, _with_timeout
from invest.data.local import LocalStore
from invest.data.resilient_provider import STALE_THRESHOLD, ResilientProvider, is_stale
from invest.webapp import create_app


# ---------- 1. akshare 调用超时保护 ----------

class TestWithTimeout:
    def test_timeout_returns_none_and_does_not_hang(self):
        """挂死的调用在 timeout 后立即返回 None，不阻塞主线程。"""
        def hang() -> str:
            time.sleep(1.0)
            return "too-late"

        t0 = time.monotonic()
        assert _with_timeout(hang, timeout=0.1) is None
        # 若实现误用 with 块（shutdown 等线程跑完），耗时会 ≥1.0s
        assert time.monotonic() - t0 < 0.8

    def test_exception_returns_none(self):
        """akshare 内部抛错同样降级为 None，不向调用方传播。"""
        def boom() -> None:
            raise ConnectionError("网络抖动")

        assert _with_timeout(boom) is None

    def test_normal_call_returns_value_with_args(self):
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert _with_timeout(add, 1, b=2) == 3

    def test_default_timeout_is_10s(self):
        assert FALLBACK_TIMEOUT == 10


# ---------- 2. ResilientProvider：primary → 缓存 → fallback ----------

class FakeProvider:
    """fetch_series 假实现：可注入返回数据或异常，并记录调用供断言。"""

    def __init__(self, data: dict | None = None, error: Exception | None = None):
        self.data, self.error = data, error
        self.calls: list[tuple[str, str]] = []

    def fetch_series(self, instrument_id: str, kind: str, **kwargs) -> dict | None:
        self.calls.append((instrument_id, kind))
        if self.error:
            raise self.error
        return dict(self.data) if self.data else None


class TestResilientProvider:
    def test_primary_ok_not_stale(self):
        """正常路径：主源命中返回数据，stale=False，不碰备用源。"""
        primary = FakeProvider(data={"rows": [1, 2]})
        fallback = FakeProvider()
        rp = ResilientProvider(primary, fallback=fallback)
        out = rp.fetch_series("510300", "etf_daily")
        assert out == {"rows": [1, 2], "stale": False}
        assert fallback.calls == []

    def test_primary_fail_fallback_used(self):
        """主源失败 → fallback 兜底命中，标 stale=True + source=fallback。"""
        primary = FakeProvider(error=TimeoutError("主源超时"))
        fallback = FakeProvider(data={"rows": [1]})
        rp = ResilientProvider(primary, fallback=fallback)
        out = rp.fetch_series("510300", "etf_daily")
        assert out is not None
        assert out["rows"] == [1]
        assert out["stale"] is True
        assert out["source"] == "fallback"
        assert fallback.calls == [("510300", "etf_daily")]

    def test_cache_precedes_fallback(self):
        """主源失败 → 本地缓存优先于 fallback（旧数据可用总比没数据强）。"""
        primary = FakeProvider(error=RuntimeError("挂死"))
        cache = FakeProvider(data={"rows": "旧数据"})
        fallback = FakeProvider(data={"rows": "新数据"})
        rp = ResilientProvider(primary, fallback=fallback, cache=cache)
        out = rp.fetch_series("510300", "etf_daily")
        assert out["source"] == "cache"
        assert out["stale"] is True
        assert fallback.calls == []  # 缓存命中后不再下探

    def test_all_fail_returns_none_no_raise(self):
        """主源/缓存/备用源全挂：返回 None，绝不向上抛异常。"""
        rp = ResilientProvider(
            FakeProvider(error=RuntimeError("主源挂")),
            fallback=FakeProvider(error=ConnectionError("备用也挂")),
            cache=FakeProvider(error=sqlite3.OperationalError("缓存读失败")),
        )
        assert rp.fetch_series("510300", "etf_daily") is None

    def test_protocol_methods_delegate_to_primary(self):
        """DataProvider 协议方法（etf_daily 等）透明转发，可直接替换 run_pull 的 provider。"""
        primary = SimpleNamespace(etf_daily=lambda code, start="2015-01-01": f"df:{code}")
        rp = ResilientProvider(primary)
        assert rp.etf_daily("510300") == "df:510300"


# ---------- 3. stale 阈值判定 ----------

class TestIsStale:
    def test_fresh_not_stale(self):
        assert is_stale(datetime.now().isoformat()) is False

    def test_older_than_threshold_is_stale(self):
        old = datetime.now() - STALE_THRESHOLD - timedelta(minutes=1)
        assert is_stale(old.isoformat()) is True

    def test_missing_or_garbage_is_stale(self):
        """时间戳缺失/损坏按 stale 处理（宁可误标，不可漏标）。"""
        assert is_stale(None) is True
        assert is_stale("") is True
        assert is_stale("not-a-timestamp") is True


# ---------- 4. 标的详情端点 stale 标记（降级路径明示） ----------

def _make_client(tmp_path) -> TestClient:
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


def _seed_nav(tmp_path, updated_at: str | None = None) -> LocalStore:
    """写一条 fund_nav 序列（example 配置 code 为空 → 序列键回退 instrument id）。

    updated_at 传入则直接改库回写该时间，模拟"上次拉取很久以前"的旧缓存。
    """
    store = LocalStore(tmp_path / "invest.db")
    store.upsert_series(
        "csi_dividend_pension", "fund_nav",
        pd.DataFrame({"date": ["2026-10-16"], "close": [1.5]}), source="test",
    )
    if updated_at:
        with sqlite3.connect(tmp_path / "invest.db") as conn:
            conn.execute(
                "UPDATE series SET updated_at=? WHERE instrument=? AND kind=?",
                (updated_at, "csi_dividend_pension", "fund_nav"),
            )
    return store


class TestInstrumentDetailStale:
    def test_fresh_cache_not_stale(self, tmp_path):
        """缓存刚刷新（<6h）→ stale=False。"""
        _seed_nav(tmp_path)  # upsert_series 落 updated_at=now
        c = _make_client(tmp_path)
        r = c.get("/api/invest/instrument/csi_dividend_pension")
        assert r.status_code == 200
        assert r.json()["stale"] is False

    def test_old_cache_marked_stale(self, tmp_path):
        """缓存 2 天没刷新（拉数失败只能吃旧数据）→ stale=True。"""
        _seed_nav(tmp_path, updated_at=(datetime.now() - timedelta(days=2)).isoformat(timespec="seconds"))
        c = _make_client(tmp_path)
        r = c.get("/api/invest/instrument/csi_dividend_pension")
        assert r.status_code == 200
        assert r.json()["stale"] is True
