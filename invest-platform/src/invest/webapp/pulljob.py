"""手动拉数后台任务：内存单句柄 + 状态轮询（单用户，无需任务队列）。

拉数是分钟级网络任务，同步等待必然超时——接口只负责"触发"，前端轮询 status。
S09 起"拉数+评估"核心下沉到 scheduler.pull_job.pull_and_evaluate（与定时任务
共用），store 走 default_store：本地 SQLite / 部署 MySQL 随环境（修掉旧实现
硬编码 LocalStore、MySQL 部署下拉数写错库的问题）。
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
    # 局部导入便于测试 monkeypatch invest.pipeline.run_pull / invest.reporting.evaluate_and_store_signals
    try:
        from ..data.mysql_store import default_store
        from ..scheduler.pull_job import pull_and_evaluate

        def log(msg: str) -> None:
            with _lock:
                _job.log.append(f"{time.strftime('%H:%M:%S')} {msg}")

        # default_store：本地 SQLite / 部署 MySQL（INVEST_DB_URL），与读路径同库
        pull_and_evaluate(data_dir, config_path, default_store(data_dir), log=log)
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
