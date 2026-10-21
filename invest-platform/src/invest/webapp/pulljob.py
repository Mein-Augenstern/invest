"""手动拉数后台任务：内存单句柄 + 状态轮询（单用户，无需任务队列）。

拉数是分钟级网络任务，同步等待必然超时——接口只负责"触发"，前端轮询 status。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Job:
    status: str = "idle"  # idle | running | done | error
    started: str = ""
    finished: str = ""
    log: list[str] = field(default_factory=list)


_job = _Job()
_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def start_pull(data_dir, config_path) -> tuple[bool, str]:
    with _lock:
        if _job.status == "running":
            return False, "已有拉数任务进行中"
        _job.status = "running"
        _job.started = _now()
        _job.finished = ""
        _job.log = []
    t = threading.Thread(target=_run, args=(data_dir, config_path), daemon=True)
    t.start()
    return True, ""


def _run(data_dir, config_path) -> None:
    # 局部导入便于测试 monkeypatch invest.pipeline.run_pull
    try:
        from pathlib import Path

        from ..portfolio import load_portfolio
        from ..data.akshare_provider import AkshareProvider
        from ..data.local import LocalStore
        from ..pipeline import run_pull

        def log(msg: str) -> None:
            with _lock:
                _job.log.append(f"{time.strftime('%H:%M:%S')} {msg}")

        conf = load_portfolio(LocalStore(Path(data_dir) / "invest.db"), config_path)
        store = LocalStore(Path(data_dir) / "invest.db")
        run_pull(conf, store, AkshareProvider(), log=log)
        # S4：拉数成功即评估信号（纪律链闭环：数据新鲜→信号新鲜，不依赖本机 cron）
        try:
            from ..ledger.trades import load_trades as _lt
            from ..reporting import evaluate_and_store_signals as _ev

            new_count = _ev(conf, store, _lt(Path(data_dir) / "trades.csv"))
            log(f"[OK] 信号评估完成（新增 {new_count} 条）")
        except Exception as e:  # noqa: BLE001 - 评估失败不影响拉数结果
            log(f"[WARN] 拉数后信号评估失败: {type(e).__name__}")
        with _lock:
            _job.status = "done"
    except Exception as e:  # noqa: BLE001 - 失败可见
        with _lock:
            _job.log.append(f"{time.strftime('%H:%M:%S')} [FAIL] {type(e).__name__}: {e}")
            _job.status = "error"
    finally:
        with _lock:
            _job.finished = _now()


def status() -> dict:
    with _lock:
        return {
            "status": _job.status,
            "started": _job.started,
            "finished": _job.finished,
            "log": _job.log[-15:],
        }
