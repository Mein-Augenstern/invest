"""周报生成后台任务：模式与 pulljob 一致（内存单句柄 + 状态轮询）。

生成含 AI 解读时耗时可达 60s，同步等待必超时——接口只负责触发，前端轮询 status。
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
    file: str = ""
    log: list[str] = field(default_factory=list)


_job = _Job()
_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def start_report(data_dir, config_path, with_ai: bool = False) -> tuple[bool, str]:
    with _lock:
        if _job.status == "running":
            return False, "已有周报生成任务进行中"
        _job.status = "running"
        _job.started = _now()
        _job.finished = ""
        _job.file = ""
        _job.log = [f"{time.strftime('%H:%M:%S')} 开始生成周报（AI解读: {'开' if with_ai else '关'}）"]
    t = threading.Thread(target=_run, args=(data_dir, config_path, with_ai), daemon=True)
    t.start()
    return True, ""


def _run(data_dir, config_path, with_ai: bool) -> None:
    # 局部导入便于测试 monkeypatch invest.reporting.build_weekly_report_md
    try:
        from datetime import datetime
        from pathlib import Path

        from ..portfolio import load_portfolio
        from ..data.local import LocalStore
        from ..ledger.trades import load_trades
        from ..reporting import build_weekly_report_md

        store = LocalStore(Path(data_dir) / "invest.db")
        conf = load_portfolio(store, config_path)
        trades = load_trades(Path(data_dir) / "trades.csv")
        report = build_weekly_report_md(conf, store, trades, with_ai=with_ai)
        out_dir = Path(data_dir) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"weekly-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        (out_dir / name).write_text(report, encoding="utf-8")
        with _lock:
            _job.file = name
            _job.log.append(f"{time.strftime('%H:%M:%S')} 已保存 {name}")
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
            "file": _job.file,
            "log": _job.log[-15:],
        }
