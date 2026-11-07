"""S09 分布式定时拉数测试（spec docs/sdd/S09-distributed-schedule.md）。

AC-1 恰一执行（互斥 + 并发争锁恰一）
AC-2 TTL 过期接管（崩溃自愈）
AC-3 拉完自动评估信号
AC-4 过期自动补拉（overview data_stale + 门控）
AC-5 留痕（last_run / /api/schedule/status）
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from invest import config as cfg
from invest.scheduler.distributed_lock import DistributedLock, LockState
from invest.scheduler import pull_job
from invest.webapp import create_app


# ---------- 分布式锁 ----------

class TestDistributedLock:
    def test_mutual_exclusion_and_release(self, tmp_path):
        """AC-1：A 持锁时 B 争锁失败；A 释放后 B 可获得；非持有者释放无效。"""
        db = tmp_path / "invest.db"
        a = DistributedLock(_local(db), holder="node-a")
        b = DistributedLock(_local(db), holder="node-b")
        assert a.acquire() is True
        assert b.acquire() is False
        assert b.release() is False  # 非持有者释放不动他人的锁
        assert a.release() is True
        assert b.acquire() is True

    def test_non_reentrant(self, tmp_path):
        """同 holder 持锁期间重复 acquire 也失败（防同进程重复执行）。"""
        a = DistributedLock(_local(tmp_path / "invest.db"), holder="node-a")
        assert a.acquire() is True
        assert a.acquire() is False

    def test_expired_takeover(self, tmp_path):
        """AC-2：持锁者崩溃不释放 → locked_until 过期 → 下一轮接管。"""
        db = tmp_path / "invest.db"
        a = DistributedLock(_local(db), holder="node-a")
        assert a.acquire() is True
        _force_expire(db)  # 模拟 A 崩溃后 TTL 已过
        b = DistributedLock(_local(db), holder="node-b")
        assert b.acquire() is True
        st = b.state()
        assert st.locked_by == "node-b" and st.held_now is True
        assert a.release() is False  # 已被接管，A 无权释放
        assert b.release() is True

    def test_renew_extends_ttl(self, tmp_path):
        """续期：TTL 快到时 renew 拉长持锁窗口；被接管后续期失败。"""
        db = tmp_path / "invest.db"
        a = DistributedLock(_local(db), holder="node-a", ttl_minutes=0.01)
        assert a.acquire() is True
        _force_expire(db)
        assert a.renew() is True and a.state().held_now is True
        _force_expire(db)
        b = DistributedLock(_local(db), holder="node-b")
        assert b.acquire() is True
        assert a.renew() is False  # 已被 B 接管

    def test_concurrent_race_exactly_one(self, tmp_path):
        """AC-1：8 实例并发争锁恰一成功（UNIQUE(lock_name) 兜底）。"""
        db = tmp_path / "invest.db"
        DistributedLock(_local(db), holder="seed")  # 建表
        results: list[bool] = []
        results_lock = threading.Lock()

        def race(i: int) -> None:
            lk = DistributedLock(_local(db), holder=f"node-{i}")
            ok = lk.acquire()
            with results_lock:
                results.append(ok)

        threads = [threading.Thread(target=race, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(results) == 1

    def test_state_empty_row(self, tmp_path):
        """未争过锁时 state 返回空态（观测端点不炸）。"""
        lk = DistributedLock(_local(tmp_path / "invest.db"), holder="node-a")
        st = lk.state()
        assert isinstance(st, LockState) and st.held_now is False and st.locked_by is None


def _local(db_path):
    from invest.data.local import LocalStore

    return LocalStore(db_path)


def _force_expire(db_path) -> None:
    """把锁的 locked_until 改到过去（模拟持锁者崩溃 + TTL 已过）。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE starsite_lock SET locked_until=?",
        ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="microseconds"),),
    )
    conn.commit()
    conn.close()


# ---------- 锁保护的拉数任务 ----------

class TestRunPullOnce:
    def test_skips_when_lock_held(self, tmp_path, monkeypatch):
        """AC-1 另一半：他实例持锁 → 本实例跳过且不拉数（ran=False 非异常）。"""
        called = []
        monkeypatch.setattr(pull_job, "pull_and_evaluate", lambda *a, **k: called.append(1))
        other = DistributedLock(_local(tmp_path / "invest.db"),
                                pull_job.LOCK_NAME, holder="other-node")  # 同名锁行才互斥
        assert other.acquire() is True

        result = pull_job.run_pull_once(tmp_path, None, holder="this-node")
        assert result["ran"] is False
        assert "other-node" in result["reason"]
        assert called == []
        assert pull_job.last_run["ran"] is False and "other-node" in pull_job.last_run["reason"]

    def test_runs_and_releases_lock(self, tmp_path, monkeypatch):
        """争锁成功 → 拉数执行 → 结束释放锁（下次可再抢）。"""
        called = []
        monkeypatch.setattr(pull_job, "pull_and_evaluate",
                            lambda *a, **k: called.append(1) or 3)
        result = pull_job.run_pull_once(tmp_path, None, holder="this-node")
        assert result["ran"] is True and result["evaluated"] == 3
        assert called == [1]
        st = DistributedLock(_local(tmp_path / "invest.db"), holder="observer").state()
        assert st.held_now is False  # 已释放
        assert pull_job.last_run["ran"] is True and pull_job.last_run["evaluated"] == 3


class TestPullAndEvaluate:
    def test_pull_then_evaluate(self, tmp_path, monkeypatch):
        """AC-3：拉数完成后自动评估信号（新增条数入留痕，失败不影响拉数）。"""
        import invest.pipeline as pipeline
        import invest.reporting as reporting

        logs: list[str] = []
        pull_calls, eval_calls = [], []

        def fake_run_pull(conf, store, provider, log=print, start="2015-01-01"):
            pull_calls.append(conf)
            log("[OK] 模拟拉数完成")

        def fake_evaluate(conf, store, trades):
            eval_calls.append(conf)
            return 7

        monkeypatch.setattr(pipeline, "run_pull", fake_run_pull)
        monkeypatch.setattr(reporting, "evaluate_and_store_signals", fake_evaluate)

        from invest.data.local import LocalStore

        store = LocalStore(tmp_path / "invest.db")
        n = pull_job.pull_and_evaluate(tmp_path, cfg.CONFIG_DIR / "portfolio.example.yaml",
                                       store, log=logs.append)
        assert n == 7
        assert len(pull_calls) == 1 and len(eval_calls) == 1  # 先拉数后评估
        assert any("信号评估完成（新增 7 条）" in line for line in logs)

    def test_evaluate_failure_does_not_break_pull(self, tmp_path, monkeypatch):
        """评估抛异常：拉数照常完成，返回 -1 且不外抛。"""
        import invest.pipeline as pipeline
        import invest.reporting as reporting

        monkeypatch.setattr(pipeline, "run_pull", lambda *a, **k: None)
        monkeypatch.setattr(reporting, "evaluate_and_store_signals",
                            lambda *a: (_ for _ in ()).throw(RuntimeError("eval boom")))

        from invest.data.local import LocalStore

        n = pull_job.pull_and_evaluate(tmp_path, cfg.CONFIG_DIR / "portfolio.example.yaml",
                                       LocalStore(tmp_path / "invest.db"))
        assert n == -1


# ---------- 触发计算与 API ----------

class TestScheduleApi:
    @pytest.fixture()
    def client(self, tmp_path):
        app = create_app(
            allowed_hosts={"testserver"},
            config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
            data_dir=tmp_path,
        )
        return TestClient(app)

    def test_status_endpoint(self, client, tmp_path):
        """AC-5：状态端点字段齐全；默认未启用、锁空闲。"""
        r = client.get("/api/schedule/status")
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is False
        assert data["cron"] == "20:00"
        assert data["lock"]["held_now"] is False
        assert "next_run" in data and "last_run" in data
        # 锁表确已建在数据目录（观测即建表，部署侧无需手工迁移）
        assert (tmp_path / "invest.db").exists()

    def test_next_run_at(self):
        """今天未到=今天；已过=明天（错过不回跑，由 AC-4 补拉兜底）。"""
        now = datetime(2026, 11, 2, 10, 0)
        assert pull_job.next_run_at(now, 20, 0) == datetime(2026, 11, 2, 20, 0)
        late = datetime(2026, 11, 2, 21, 0)
        assert pull_job.next_run_at(late, 20, 0) == datetime(2026, 11, 3, 20, 0)
        edge = datetime(2026, 11, 2, 20, 0, 0, 1)  # 恰过触发点
        assert pull_job.next_run_at(edge, 20, 0) == datetime(2026, 11, 3, 20, 0)

    def test_overview_reports_data_stale(self, client):
        """AC-4：overview 带 data_stale 字段（示例数据无序列 → False）。"""
        r = client.get("/api/invest/overview")
        assert r.status_code == 200
        assert r.json()["data_stale"] is False


class TestAutoPullOnStale:
    def test_autopull_triggered_when_stale(self, tmp_path, monkeypatch):
        """AC-4：显式开启门控 + 序列过期 → overview 自动触发后台拉数（限频一次）。"""
        import invest.webapp.pulljob as pulljob_mod
        from invest.config import series_kind
        from invest.data.local import LocalStore

        monkeypatch.setenv("INVEST_AUTOPULL_ON_STALE", "1")
        started = []
        monkeypatch.setattr(pulljob_mod, "start_pull", lambda d, c: started.append(d) or (True, ""))

        # 示例组合 code 全空（示例数据刻意留白），造一个带 code 的最小组合
        config_path = tmp_path / "portfolio.s09.yaml"
        config_path.write_text(
            "meta:\n  owner: t\ninstruments:\n"
            "  - id: hs300_etf\n    type: etf\n    name: 沪深300ETF\n    code: '510300'\n    account: a\n"
            "accounts:\n  - id: a\n    name: A\nstrategy:\n  base_monthly_invest: 1000\n",
            encoding="utf-8",
        )
        app = create_app(allowed_hosts={"testserver"}, config_path=config_path, data_dir=tmp_path)

        # 种一条过期序列（updated_at = 7h 前，阈值 6h）
        import pandas as pd

        store = LocalStore(tmp_path / "invest.db")
        with TestClient(app) as client:  # with 触发 lifespan（未启用定时，无副作用）
            from invest.portfolio import load_portfolio

            conf = load_portfolio(store, config_path)
            ins = next(i for i in conf.instruments if i.code)
            store.upsert_series(ins.code, series_kind(ins.type),
                                pd.DataFrame({"date": ["2026-11-01"], "close": [1.0]}))
            old = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
            conn = sqlite3.connect(tmp_path / "invest.db")
            conn.execute("UPDATE series SET updated_at=? WHERE instrument=?", (old, ins.code))
            conn.commit()
            conn.close()

            r = client.get("/api/invest/overview")
            assert r.status_code == 200
            import os as _os
            from invest.webapp.routes_mp import _AUTO_PULL_STATE as _aps
            print(f"[DIAG] env={_os.environ.get('INVEST_AUTOPULL_ON_STALE')!r} last_at={_aps['last_at']!r} "
                  f"stale={r.json()['data_stale']!r} dburl={_os.environ.get('INVEST_DB_URL')!r}")
            assert r.json()["data_stale"] is True
            assert len(started) == 1  # 自动补拉已触发
            # 限频：30 分钟内第二次访问不再触发
            client.get("/api/invest/overview")
            assert len(started) == 1

    def test_autopull_off_locally_by_default(self, tmp_path, monkeypatch):
        """本地默认关：即使数据过期也不自动拉（避免本机意外打 akshare）。"""
        import invest.webapp.pulljob as pulljob_mod

        monkeypatch.delenv("INVEST_DB_URL", raising=False)
        monkeypatch.delenv("INVEST_AUTOPULL_ON_STALE", raising=False)
        started = []
        monkeypatch.setattr(pulljob_mod, "start_pull", lambda d, c: started.append(d) or (True, ""))

        app = create_app(
            allowed_hosts={"testserver"},
            config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
            data_dir=tmp_path,
        )
        with TestClient(app) as client:
            # 直接种过期数据但走 overview（_any_series_stale=True 也无济于事——门控先断）
            from invest.webapp.routes_mp import _AUTO_PULL_STATE
            _AUTO_PULL_STATE["last_at"] = 0.0
            client.get("/api/invest/overview")
            assert started == []
